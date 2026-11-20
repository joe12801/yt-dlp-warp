# yt-dlp-warp

**用 `yt-dlp` + Cloudflare WARP 下载 YouTube 视频**，专门解决「云服务器 / 数据中心 IP 被 YouTube 风控」的问题。把这套已经跑通的方案沉淀成一个独立小项目，以后 `git clone` 下来就能用。

## TL;DR：一定要 COOKIE 吗？

**不一定，绝大多数情况不需要。**

| 场景 | 需要 cookie 吗 |
| :--- | :--- |
| 公开视频 + WARP 生效（出口已换成干净的消费者 IP） | ❌ **不需要**，本项目默认就是零 cookie |
| 公开视频，但 WARP 出口偶尔也被风控 | 偶尔需要（先用 `doctor` 确认，再补） |
| 年龄限制（18+）视频 | ✅ 必须，要登录态 |
| 会员 / 私有 / 仅授权可见 / 地区限制内容 | ✅ 必须，要对应账号登录态 |
| 部分高码率格式、临时要求 PO Token / 登录证明 | 可能需要 |

关键点：**「Sign in to confirm you're not a bot」通常不是因为你没登录，而是因为出口 IP 被标记**。Oracle Cloud、各类 VPS 的 IP 段最常见。这时加 cookie 往往治标不治本，正确做法是先用 Cloudflare WARP 换出口：

```
yt-dlp ──> WARP SOCKS5 (127.0.0.1:40000) ──> Cloudflare 出口 ──> YouTube
```

WARP 官方客户端的 **proxy 模式**只在本地开一个 SOCKS5 端口，不改全局路由、不影响远程桌面/SSH，也不会让整台机器的流量都绕道。

> 本项目默认 **完全不加载 cookie**。只有你显式给 `--cookies` 时才会用，而且会先复制成临时快照交给 yt-dlp —— 原凭证文件全程只读，绝不会被回写或删除，浏览器登录状态不受影响。详见 [docs/COOKIES.md](docs/COOKIES.md)。

## 快速开始

```bash
git clone https://github.com/joe12801/yt-dlp-warp.git
cd yt-dlp-warp
python -m pip install -r requirements.txt
cp .env.example .env

# 1) 安装并启用 WARP（Linux 需要 sudo；Windows 用管理员 PowerShell）
sudo bash scripts/setup-warp-linux.sh
# 或： powershell -ExecutionPolicy Bypass -File scripts/setup-warp-windows.ps1

# 2) 体检：确认 WARP 出口 + 判断当前到底需不需要 cookie
python ytwarp.py doctor

# 3) 下载
python ytwarp.py https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

`doctor` 会打印 WARP 是否连通、出口 `warp=on` 的 IP，并用一个公开视频实际解析一次：

- 解析成功 → 明确告诉你「当前不需要 cookie」；
- 报 `Sign in to confirm you're not a bot` → 先检查 WARP 是否真的连上，再考虑补 cookie。

系统依赖：`ffmpeg`（合并音视频 / 转 mp3）、`Node.js` 或 `Deno`（YouTube JS challenge，配合 `yt-dlp-ejs`）、`curl`（doctor 检测出口）。

## 常用命令

```bash
# 默认：最佳视频 + 最佳音频，合并为 mkv，输出到 downloads/
python ytwarp.py URL

# 只列格式，不下载
python ytwarp.py -F URL

# 1080p 以内，输出 mp4
python ytwarp.py -f "bv*[height<=1080]+ba/b" --merge mp4 URL

# 只要音频（mp3）
python ytwarp.py --audio-only URL

# 连字幕一起下载并封装进视频
python ytwarp.py --subs --sub-langs "zh-Hans,en" URL

# 批量 / 播放列表
python ytwarp.py --playlist --playlist-end 10 PLAYLIST_URL

# 家宽干净出口，不走代理
python ytwarp.py --no-proxy URL

# 只打印生成的 yt-dlp 命令，方便复制或改参数
python ytwarp.py --print-command URL

# 确实需要登录态时（cookies.txt 由 Cookie-Editor 导出转换而来）
python scripts/cookie-editor-to-netscape.py --input exported.json --out cookies.txt
python ytwarp.py --cookies cookies.txt URL
```

优先级：**命令行参数 > 显式环境变量 > `.env` > 内置默认值**。

## 配置

复制 `.env.example` 为 `.env` 后修改。常用项：

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `YTWARP_PROXY` | `socks5://127.0.0.1:40000` | WARP proxy 模式端口 |
| `YTWARP_COOKIES` | 空 | Netscape cookies.txt 路径，**默认不用** |
| `YTWARP_COOKIES_FROM_BROWSER` | 空 | 不推荐，见下 |
| `YTWARP_FORMAT` | `bv*+ba/b` | yt-dlp 格式选择 |
| `YTWARP_MERGE` | `mkv` | 合并容器，`mp4`/`webm` 可选 |
| `YTWARP_OUTPUT` | `downloads/%(title).200B [%(id)s].%(ext)s` | 输出模板 |
| `YTWARP_JS_RUNTIME` | `auto` | `auto` / `node` / `deno` / `none` |
| `YTWARP_EXTRA_ARGS` | 空 | 额外透传参数 |

## 关于 cookie 的安全约定

1. **不要用 `--cookies-from-browser chrome`**：Chrome 127+ 的 App-Bound Encryption（v20）把登录 cookie 绑定到原 profile 环境，自动提取经常失败，还可能让 Chrome 判定环境变化而把账号退出。本项目默认禁用，显式开启会打印警告。
2. 需要登录态时，用浏览器扩展 **Cookie-Editor** 在 `youtube.com` 页面导出 JSON，再用 `scripts/cookie-editor-to-netscape.py` 转成独立的 `cookies.txt`。
3. `ytwarp.py` 把 `cookies.txt` 复制成临时快照再传给 yt-dlp。**原因**：yt-dlp 退出时会回写 cookiefile，而回写会丢掉 `#HttpOnly_` 登录态（SID / HSID / SSID / SAPISID / LOGIN_INFO ...），之后所有请求又会被 bot 校验拦截。原文件永不交给 yt-dlp。
4. `cookies.txt`、`.env` 都在 `.gitignore` 里，**不要提交、不要分享**。

详见 [docs/COOKIES.md](docs/COOKIES.md)、[docs/WARP.md](docs/WARP.md)、[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 项目结构

```
yt-dlp-warp/
├── ytwarp.py                         # 主 CLI（含 doctor 体检）
├── requirements.txt
├── .env.example
├── scripts/
│   ├── setup-warp-linux.sh          # Linux 安装/配置 WARP proxy 模式
│   ├── setup-warp-windows.ps1       # Windows 启用 WARP SOCKS5
│   ├── warp-doctor.sh                # 单独检查 WARP 出口
│   └── cookie-editor-to-netscape.py  # Cookie-Editor JSON → cookies.txt
├── docs/
│   ├── COOKIES.md
│   ├── WARP.md
│   └── TROUBLESHOOTING.md
└── tests/
    └── test_ytwarp.py                # 纯标准库单元测试
```

## 测试

```bash
python -m unittest discover -s tests -v
```

## 合规声明

本项目仅用于下载**你拥有版权或已获授权的内容**，以及个人 / 家庭自用的学习场景。请勿用于公开分发、商业用途或绕过平台方的访问限制。使用 YouTube 相关功能需遵守平台服务条款与所在地法律法规；本项目不提供、也不保证任何第三方平台的会员或付费内容权限。
