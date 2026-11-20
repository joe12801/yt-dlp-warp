# Cloudflare WARP：原理与配置

## 为什么需要它

YouTube 会对**数据中心 / 云厂商 IP 段**做风控。典型报错：

```
ERROR: [youtube] VIDEO_ID: Sign in to confirm you're not a bot.
       Use --cookies-from-browser or --cookies for the authentication.
```

注意这个提示具有误导性：它建议加 cookie，但根因通常是**出口 IP 被标记**。在 Oracle Cloud 上，即使 Chrome 保持登录、cookie 完整，也照样被拦。

Cloudflare WARP 免费版把流量从 Cloudflare 的消费者出口出去，绕开被标记的 IP。官方 Linux/Windows 客户端支持 **proxy 模式**：只在本机监听一个 SOCKS5 端口（默认 `127.0.0.1:40000`），**不改全局路由、不接管系统网络、不会断 SSH / 远程桌面**。

```
yt-dlp --proxy socks5://127.0.0.1:40000
        │
        ▼
  WARP 本地 SOCKS5 ──► Cloudflare 出口 ──► YouTube
        （其余系统流量完全不变）
```

## 安装与启用

### Linux（Debian / Ubuntu，含 ARM64）

```bash
sudo bash scripts/setup-warp-linux.sh
```

脚本做这些事（兼容新旧 `warp-cli` 语法）：

1. 添加 Cloudflare 官方 apt 源并安装 `cloudflare-warp`；
2. `systemctl enable --now warp-svc`；
3. 幂等注册免费账户（`registration new`，旧版回退 `register`）；
4. `mode proxy` + `proxy port 40000`（旧版回退 `set-mode` / `set-proxy-port`）；
5. `connect`；
6. 用 `https://www.cloudflare.com/cdn-cgi/trace` 验证 `warp=on`。

默认端口可用 `WARP_PORT=40001 sudo bash scripts/setup-warp-linux.sh` 改。

### Windows（管理员 PowerShell）

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-warp-windows.ps1
```

客户端： <https://1111-releases.cloudflareclient.com/windows/Cloudflare_WARP_Release-x64.msi>

### 客户端命令速查

| 目的 | 新版 warp-cli | 旧版 |
| :--- | :--- | :--- |
| 注册 | `warp-cli --accept-tos registration new` | `warp-cli register` |
| 查看注册 | `warp-cli registration show` | — |
| proxy 模式 | `warp-cli mode proxy` | `warp-cli set-mode proxy` |
| 端口 | `warp-cli proxy port 40000` | `warp-cli set-proxy-port 40000` |
| 连接 / 断开 | `warp-cli connect` / `disconnect` | 同 |
| 状态 | `warp-cli status` | 同 |

> 免费 WARP 的 `warp=on` 表示已走隧道；`warp=plus` 是付费 WARP+，效果一样可用。若 trace 显示 `warp=off`，说明只有 DNS 生效、流量未走隧道，需重新 `connect`。

## 验证

```bash
# 只看 WARP
bash scripts/warp-doctor.sh

# 全量体检 + 判断是否需要 cookie
python ytwarp.py doctor

# 手工看出口
curl -s --socks5-hostname 127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|loc|warp)='
curl -s --socks5-hostname 127.0.0.1:40000 https://ipinfo.io/json
```

`ytwarp.py` 会**始终显式传 `--proxy`**：配置为空时传空字符串，强制 yt-dlp 忽略 `http_proxy` / `https_proxy` 环境变量。否则环境里的代理可能把请求又带回被封的出口，出现「明明装了 WARP 还是 bot 校验」。

## 依赖提醒

- `socks5://` 需要 Python 包 **PySocks**（已在 `requirements.txt`）；
- 合并音视频 / 转 mp3 需要系统 **ffmpeg**；
- YouTube 2025+ 的 JS challenge 需要 **yt-dlp-ejs + Node.js 或 Deno**，否则格式列表可能只剩图片；
- `ytwarp.py` 默认会清除注入的 `NODE_OPTIONS`（沙箱 shim 会让 yt-dlp 拉起的 node 读不到脚本）。需要保留时设 `YTWARP_KEEP_NODE_OPTIONS=1`。

## 什么时候可以不装 WARP

家宽 / 干净住宅 IP 通常直连就能用：

```bash
python ytwarp.py --no-proxy URL
```

或把 `.env` 里的 `YTWARP_PROXY` 留空。判断标准仍是 `python ytwarp.py doctor` 能解析成功。
