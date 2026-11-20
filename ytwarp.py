#!/usr/bin/env python3
"""yt-dlp + Cloudflare WARP：在「出口 IP 被 YouTube 风控」的机器上下载 YouTube 视频。

典型场景：Oracle Cloud / 各类 VPS 的 IP 段被 YouTube 标记，任何请求都会返回
「Sign in to confirm you're not a bot」。Cloudflare WARP 的 proxy 模式只在本地
开一个 SOCKS5（默认 127.0.0.1:40000），把出口换成干净的消费者 IP，不改全局路由。

设计原则
--------
* **默认不需要 cookie**。公开视频 + WARP 生效时无需任何登录态。
* 只有确实需要登录态时才给 ``--cookies``；并且永远先把凭证复制成临时快照，
  再交给 yt-dlp —— yt-dlp 在退出时会回写 cookiefile，直接给原文件会丢掉
  HttpOnly 登录 cookie（SID / HSID / SSID / SAPISID / LOGIN_INFO ...），
  也可能影响浏览器保持登录。原文件全程只读，绝不删除、绝不改写。
* 不推荐 ``--cookies-from-browser``（Chrome 127+ 的 App-Bound Encryption
  会让自动提取失效，且可能锁定/改写浏览器 profile）。需要时请显式开启。

用法
----
    python ytwarp.py doctor                       # 环境体检 + 判断是否需要 cookie
    python ytwarp.py https://www.youtube.com/watch?v=VIDEO_ID
    python ytwarp.py -f "bv*[height<=1080]+ba/b" URL
    python ytwarp.py --audio-only --subs URL
    python ytwarp.py --print-command URL        # 只打印 yt-dlp 命令，不执行
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PROXY = "socks5://127.0.0.1:40000"
DEFAULT_FORMAT = "bv*+ba/b"
DEFAULT_MERGE = "mkv"
DEFAULT_OUTPUT = "downloads/%(title).200B [%(id)s].%(ext)s"
DEFAULT_SUB_LANGS = "zh-Hans,zh-Hant,en,ja,ko"
DEFAULT_RETRIES = 5
PROBE_VIDEO_ID = "dQw4w9WgXcQ"
ENV_PREFIX = "YTWARP_"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- 配置
def load_dotenv(path: Path | str = ".env") -> None:
    """把 .env 读入 os.environ；已存在的显式环境变量优先（不覆盖）。"""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith(ENV_PREFIX):
            os.environ.setdefault(key, value)


def env(name: str, default: str = "") -> str:
    return os.environ.get(ENV_PREFIX + name, default)


def wipe_node_options() -> None:
    """沙箱注入的 NODE_OPTIONS 会让 yt-dlp-ejs 拉起的 node 读不到自己的脚本。"""
    if env("KEEP_NODE_OPTIONS").lower() not in ("1", "true", "yes"):
        os.environ.pop("NODE_OPTIONS", None)


def yt_dlp_cmd() -> list[str]:
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if exe:
        return [exe]
    return [sys.executable, "-m", "yt_dlp"]


def split_extra_args(text: str) -> list[str]:
    """解析透传参数；Windows 下保留反斜杠路径（posix=True 会吃掉 \\）。"""
    if not text.strip():
        return []
    if os.name != "nt":
        return shlex.split(text)
    return [p.strip().strip('"').strip("'") for p in shlex.split(text, posix=False)]


def cli_supports_js_runtimes(base: list[str]) -> bool:
    try:
        r = subprocess.run(
            base + ["--help"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        return "--js-runtimes" in (r.stdout or "")
    except Exception:
        return False


def detect_js_runtime(mode: str = "auto") -> str | None:
    if mode == "none":
        return None
    if mode in ("node", "deno"):
        return mode if shutil.which(mode) else None
    try:
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        return None
    if shutil.which("deno"):
        return "deno"
    if shutil.which("node"):
        return "node"
    return None


def make_cookie_snapshot(source: Path) -> Path:
    """复制 cookie 凭证到临时目录；yt-dlp 只接触这份副本。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="ytwarp-cookies-"))
    dst = tmp_dir / "cookies.txt"
    shutil.copyfile(source, dst)
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass
    return dst


# --------------------------------------------------------------------------- 命令构造
def build_command(o: dict, urls: list[str]) -> list[str]:
    """纯函数：把解析好的选项转成 yt-dlp 命令行（便于测试）。"""
    cmd = list(o["base"])
    cmd += ["--ignore-config", "--no-warnings"]
    if o["playlist"]:
        if o["playlist_end"]:
            cmd += ["--playlist-end", str(o["playlist_end"])]
    else:
        cmd += ["--no-playlist"]
    cmd += [
        "--socket-timeout", "30",
        "--retries", str(o["retries"]),
        "--fragment-retries", str(o["retries"]),
        "--user-agent", USER_AGENT,
    ]
    # 永远显式给 --proxy：空字符串表示强制直连并忽略环境代理，
    # 避免机器上的 http_proxy 把请求又带回被风控的出口。
    cmd += ["--proxy", o["proxy"]]
    if o["cookies"]:
        cmd += ["--cookies", str(o["cookies"])]
    if o["cookies_from_browser"]:
        cmd += ["--cookies-from-browser", o["cookies_from_browser"]]
    if o["ffmpeg"]:
        cmd += ["--ffmpeg-location", o["ffmpeg"]]
    if o["js"] and o["js_supported"]:
        cmd += ["--js-runtimes", o["js"]]
    if o["audio_only"]:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        cmd += ["-f", o["format"]]
        if o["merge"]:
            cmd += ["--merge-output-format", o["merge"]]
    if o["subs"]:
        cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", o["sub_langs"]]
        if o["embed_subs"]:
            cmd += ["--embed-subs"]
    if o["thumbnail"]:
        cmd += ["--write-thumbnail"]
    if o["limit_rate"]:
        cmd += ["--limit-rate", o["limit_rate"]]
    cmd += ["-o", o["output"]]
    if o["list_formats"]:
        cmd += ["-F"]
    if o["simulate"]:
        cmd += ["--simulate", "--skip-download"]
    cmd += list(o["extra"])
    cmd += list(urls)
    return cmd


def resolve_options(args, base: list[str], cookie_tmp: Path | None) -> dict:
    proxy = "" if args.no_proxy else (args.proxy or env("PROXY", DEFAULT_PROXY))
    cookies_browser = args.cookies_from_browser or env("COOKIES_FROM_BROWSER")
    if cookies_browser:
        print(
            "[warn] --cookies-from-browser 会读取浏览器 profile；"
            "Chrome 127+ 的 App-Bound Encryption 下通常无效，且可能锁定/改写登录 cookie。"
            "推荐改用 Cookie-Editor 导出 + --cookies。",
            file=sys.stderr,
        )
    return {
        "base": base,
        "proxy": proxy,
        "cookies": str(cookie_tmp) if cookie_tmp else "",
        "cookies_from_browser": cookies_browser,
        "format": args.format or env("FORMAT", DEFAULT_FORMAT),
        "merge": args.merge or env("MERGE", DEFAULT_MERGE),
        "output": args.output or env("OUTPUT", DEFAULT_OUTPUT),
        "sub_langs": args.sub_langs or env("SUB_LANGS", DEFAULT_SUB_LANGS),
        "retries": args.retries if args.retries is not None else int(env("RETRIES", str(DEFAULT_RETRIES)) or DEFAULT_RETRIES),
        "limit_rate": args.limit_rate or env("LIMIT_RATE"),
        "ffmpeg": args.ffmpeg or env("FFMPEG"),
        "playlist": args.playlist,
        "playlist_end": args.playlist_end,
        "audio_only": args.audio_only,
        "subs": args.subs,
        "embed_subs": args.embed_subs,
        "thumbnail": args.thumbnail,
        "js": detect_js_runtime(args.js_runtime or env("JS_RUNTIME", "auto")),
        "js_supported": cli_supports_js_runtimes(base),
        "list_formats": args.list_formats,
        "simulate": args.simulate,
        "extra": split_extra_args(args.extra_args or env("EXTRA_ARGS")),
    }


# --------------------------------------------------------------------------- 子命令
def download_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ytwarp.py",
        description="yt-dlp + Cloudflare WARP 下载 YouTube 视频（默认无需 cookie）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python ytwarp.py doctor\n"
            "  python ytwarp.py https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "  python ytwarp.py -f 'bv*[height<=1080]+ba/b' --merge mp4 URL\n"
            "  python ytwarp.py --audio-only --subs URL\n"
            "  python ytwarp.py --no-proxy URL          # 家宽直连，不用 WARP\n"
        ),
    )
    ap.add_argument("urls", nargs="*", help="YouTube 视频/播放列表 URL（也支持 video id）")
    ap.add_argument("--proxy", default=None, help="代理 URL，默认 socks5://127.0.0.1:40000")
    ap.add_argument("--no-proxy", action="store_true", help="强制直连并忽略环境代理")
    ap.add_argument("--cookies", default=None, help="Netscape cookies.txt；默认不使用（只读快照）")
    ap.add_argument("--cookies-from-browser", default=None,
                     help="显式启用 yt-dlp 的浏览器 cookie 读取（不推荐，见 README）")
    ap.add_argument("-o", "--output", default=None, help="输出模板")
    ap.add_argument("-f", "--format", default=None, help="yt-dlp -F 格式选择，默认 bv*+ba/b")
    ap.add_argument("--merge", default=None, help="合并容器，默认 mkv（mp4/webm 可选）")
    ap.add_argument("--audio-only", action="store_true", help="只提取音频并转 mp3")
    ap.add_argument("--subs", action="store_true", help="下载人工/自动字幕")
    ap.add_argument("--sub-langs", default=None, help="字幕语言，默认 zh-Hans,zh-Hant,en,ja,ko")
    ap.add_argument("--no-embed-subs", dest="embed_subs", action="store_false", default=True,
                     help="不把字幕封装进视频（保存为独立 .vtt/.srt）")
    ap.add_argument("--thumbnail", action="store_true", help="同时保存封面")
    ap.add_argument("--limit-rate", default=None, help="限速，例如 2M")
    ap.add_argument("--retries", type=int, default=None, help="重试次数，默认 5")
    ap.add_argument("--playlist", action="store_true", help="允许下载播放列表（默认关闭）")
    ap.add_argument("--playlist-end", type=int, default=None, help="播放列表截取条数")
    ap.add_argument("--js-runtime", choices=["auto", "node", "deno", "none"], default=None,
                    help="JS challenge runtime，默认自动探测")
    ap.add_argument("--ffmpeg", default=None, help="ffmpeg 所在目录")
    ap.add_argument("--extra-args", default=None, help='额外 yt-dlp 参数，如 "--write-info-json"')
    ap.add_argument("-F", "--list-formats", action="store_true", help="只列出可用格式")
    ap.add_argument("--simulate", action="store_true", help="只解析不下载")
    ap.add_argument("--print-command", action="store_true", help="只打印生成的 yt-dlp 命令")
    return ap


def doctor_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ytwarp.py doctor", description="环境体检并判断是否需要 cookie")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--cookies", default=None)
    ap.add_argument("--probe", nargs="?", const=PROBE_VIDEO_ID, default=PROBE_VIDEO_ID,
                     metavar="VIDEO_ID", help="用一个公开视频探测；默认 dQw4w9WgXcQ")
    ap.add_argument("--no-probe", dest="probe", action="store_const", const=None,
                     help="跳过 YouTube 探测，只检查本机环境")
    return ap


def cmd_doctor(a: argparse.Namespace) -> int:
    wipe_node_options()
    base = yt_dlp_cmd()
    proxy = "" if a.no_proxy else (a.proxy or env("PROXY", DEFAULT_PROXY))
    print("yt-dlp-warp doctor")
    print("-" * 56)
    try:
        r = subprocess.run(base + ["--version"], capture_output=True, text=True, timeout=15)
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        print("yt-dlp        :", lines[0] if lines else "unknown")
    except Exception as exc:
        print("yt-dlp        : 未找到（%s）" % type(exc).__name__)
    for tool in ("ffmpeg", "ffprobe", "node", "deno", "curl"):
        print("%-13s : %s" % (tool, shutil.which(tool) or "未安装"))
    try:
        import yt_dlp_ejs  # noqa: F401
        print("yt-dlp-ejs   : 已安装")
    except ImportError:
        print("yt-dlp-ejs   : 未安装（YouTube JS challenge 可能只剩图片格式）")
    js = detect_js_runtime(env("JS_RUNTIME", "auto"))
    print("JS runtime   :", js or "未启用")
    js_ok = cli_supports_js_runtimes(base)
    print("--js-runtimes:", "支持" if js_ok else "当前 yt-dlp 不支持（已跳过）")

    if proxy:
        u = urlparse(proxy)
        host, port = u.hostname or "127.0.0.1", u.port or 40000
        try:
            with socket.create_connection((host, port), timeout=3):
                print("WARP 端口     : %s:%s 可连接 ✓" % (host, port))
        except OSError as exc:
            print("WARP 端口     : %s:%s 不可连接 ✗ (%s)" % (host, port, exc))
            print("               → 先运行 scripts/setup-warp-linux.sh 或 setup-warp-windows.ps1")
        if shutil.which("curl"):
            try:
                r = subprocess.run(
                    ["curl", "-s", "--max-time", "15", "--socks5-hostname", f"{host}:{port}",
                     "https://www.cloudflare.com/cdn-cgi/trace"],
                    capture_output=True, text=True, timeout=20,
                )
                trace = dict(
                    line.split("=", 1) for line in (r.stdout or "").splitlines()
                    if "=" in line
                )
                print("WARP 出口     : warp=%s ip=%s loc=%s" % (
                    trace.get("warp", "?"), trace.get("ip", "?"), trace.get("loc", "?")))
            except Exception as exc:
                print("WARP 出口     : 检测失败 (%s)" % type(exc).__name__)
        else:
            print("WARP 出口     : 未安装 curl，跳过 trace 检测")
    else:
        print("WARP 端口     : 已禁用代理（直连）")
    print("当前代理配置  :", proxy or "(直连)")
    print("-" * 56)

    if not a.probe:
        print("按 --no-probe 要求跳过 YouTube 探测。")
        return 0

    url = a.probe if "://" in a.probe else f"https://www.youtube.com/watch?v={a.probe}"
    cmd = base + [
        "--ignore-config", "--no-warnings", "--no-playlist",
        "--socket-timeout", "30", "--proxy", proxy,
        "--simulate", "--skip-download", "--dump-json", url,
    ]
    if js and js_ok:
        cmd += ["--js-runtimes", js]
    if a.cookies:
        snapshot = make_cookie_snapshot(Path(a.cookies).expanduser())
        cmd += ["--cookies", str(snapshot)]
    else:
        snapshot = None
    print("探测公开视频  :", url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except Exception as exc:
        print("结论          : 探测异常 (%s)" % exc)
        return 1
    finally:
        if snapshot:
            shutil.rmtree(snapshot.parent, ignore_errors=True)
    out = (r.stdout or "") + (r.stderr or "")
    low = out.lower()
    if r.returncode == 0:
        title = ""
        for line in (r.stdout or "").splitlines():
            try:
                title = json.loads(line).get("title", "")
                break
            except Exception:
                continue
        print("结论          : 解析成功 ✓ %s" % title)
        print("                → 当前出口可用，**不需要 cookie**。")
        return 0
    if "sign in to confirm" in low or "not a bot" in low or "confirm you’re not a bot" in low:
        print("结论          : 仍被机器人校验拦截 ✗")
        print("                → 先确认 WARP 已 connect（warp=on）；仍失败再考虑补 cookie。")
    elif "private video" in low or "age" in low and "restricted" in low:
        print("结论          : 视频需要登录/年龄验证 → 这类内容**必须 cookie**。")
    elif "unable to extract" in low or "no video formats" in low:
        print("结论          : 拿不到格式列表 → 检查 yt-dlp 版本、yt-dlp-ejs 与 node/deno。")
    else:
        print("结论          : 解析失败（yt-dlp 退出码 %s）" % r.returncode)
    print("错误摘要      :", " ".join(out.split())[:300])
    return 1


# --------------------------------------------------------------------------- 入口
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    load_dotenv()
    wipe_node_options()
    if argv and argv[0] == "doctor":
        return cmd_doctor(doctor_parser().parse_args(argv[1:]))

    ap = download_parser()
    args = ap.parse_args(argv)
    if not args.urls:
        ap.print_help()
        return 2
    if args.urls and "://" not in args.urls[0] and len(args.urls[0]) == 11:
        args.urls[0] = "https://www.youtube.com/watch?v=" + args.urls[0]

    base = yt_dlp_cmd()
    cookie_src_value = args.cookies or env("COOKIES")
    cookie_tmp = None
    if cookie_src_value:
        src = Path(cookie_src_value).expanduser()
        if not src.is_file():
            print("[ytwarp] cookies 文件不存在：%s" % src, file=sys.stderr)
            return 2
        cookie_tmp = make_cookie_snapshot(src)
        print("[ytwarp] 已生成只读 cookie 快照（原文件不会被 yt-dlp 回写）")

    try:
        o = resolve_options(args, base, cookie_tmp)
        cmd = build_command(o, args.urls)
        if args.print_command:
            print(shlex.join(cmd))
            return 0
        Path(o["output"]).parent.mkdir(parents=True, exist_ok=True)
        print("[ytwarp]", shlex.join(cmd))
        return subprocess.run(cmd).returncode
    finally:
        if cookie_tmp:
            shutil.rmtree(cookie_tmp.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
