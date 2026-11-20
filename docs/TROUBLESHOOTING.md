# 排查表

| 现象 | 最可能的原因 | 处理 |
| :--- | :--- | :--- |
| `Sign in to confirm you're not a bot` | 出口 IP 被 YouTube 标记 | ① `bash scripts/warp-doctor.sh` 确认 `warp=on`；② `warp-cli disconnect && warp-cli connect` 换出口；③ 再 `python ytwarp.py doctor`。**不要第一时间加 cookie** |
| 装了 WARP 还是 bot 校验 | 环境 `http_proxy` 覆盖了配置；或 WARP 只开了 DNS | `--print-command` 核对 `--proxy` 值；`curl --socks5-hostname ... cdn-cgi/trace` 看 `warp=` |
| `no video formats` / 只有图片格式 | JS challenge 没过 | 升级 `yt-dlp`，装 `yt-dlp-ejs`，并准备 Node.js 或 Deno；`python ytwarp.py doctor` 会列出缺失项 |
| `ProxyError` / `missing dependency` | 缺 PySocks | `python -m pip install PySocks` |
| `ffmpeg not found` / 合并失败 | 缺系统 ffmpeg | `sudo apt install -y ffmpeg`，或 `--ffmpeg /path/to/ffmpeg/bin` |
| `Requested merge output format is not compatible` | 源是 VP9/AV1 + Opus，装不进 mp4 | 默认 `mkv` 最稳；或 `-f "bv*[codec^=avc]+ba[codec^=mp4a]/b" --merge mp4` |
| `Private video. Sign in` / `Age-restricted` | 内容本身要登录 | 这类**必须** cookie，见 [COOKIES.md](COOKIES.md) |
| 加了 cookie 反而更糟 | yt-dlp 回写 cookiefile 丢了 HttpOnly 登录态 | 本项目已用只读临时快照；请确认是通过 `--cookies` 走 `ytwarp.py`，而不是自己直接 `yt-dlp --cookies 原文件` |
| Chrome 账号被退出 | 用了 `--cookies-from-browser` / 复制过 profile | 默认禁用；改用 Cookie-Editor 导出，见 [COOKIES.md](COOKIES.md) |
| `HTTP Error 403` 时好时坏 | WARP 出口偶发被限 | 重连 WARP；`--retries 10`；`--limit-rate 2M` 降速 |
| 下载很慢 / 卡在 fragment | 出口链路抖动 | `--limit-rate`、`--retries`、换 WARP 出口；必要时 `--extra-args "--concurrent-fragments 4"` |

## 一条命令定位

```bash
python ytwarp.py doctor
```

它会依次报告：yt-dlp 版本、ffmpeg / node / deno / curl 是否齐全、`yt-dlp-ejs` 是否安装、WARP 端口能否连接、WARP 出口 `warp=` 与 IP，最后用一个公开视频实探并给出「是否需要 cookie」的结论。

## 看实际执行的命令

```bash
python ytwarp.py --print-command URL
```

把打印出来的命令直接复制去跑，能快速区分是本项目参数拼错，还是 yt-dlp / 网络本身的问题。

## 仍然失败

请收集以下信息（**不要包含 cookie 内容**）：

1. `python ytwarp.py doctor` 完整输出；
2. `python ytwarp.py --print-command URL`；
3. `yt-dlp --version`、`warp-cli status`；
4. 报错最后 20 行（把 cookie / token 值打码）。
