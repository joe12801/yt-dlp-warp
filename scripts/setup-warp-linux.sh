#!/usr/bin/env bash
# 在 Debian/Ubuntu（含 ARM64）安装 Cloudflare WARP 官方客户端，并切到「proxy 模式」。
# proxy 模式只监听 127.0.0.1:40000 的 SOCKS5，不改全局路由，SSH/远程桌面不会断。
#
#   sudo bash scripts/setup-warp-linux.sh
#
# 兼容新旧 warp-cli 语法：新版用 `registration new / mode proxy / proxy port`，
# 旧版用 `register / set-mode proxy / set-proxy-port`。
set -euo pipefail

PORT="${WARP_PORT:-40000}"
PROXY_URL="socks5://127.0.0.1:${PORT}"

log() { printf '\n[warp] %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行：sudo bash scripts/setup-warp-linux.sh" >&2
    exit 1
fi

# ---------------------------------------------------------------- 1. 安装客户端
if command -v warp-cli >/dev/null 2>&1; then
    log "已安装 cloudflare-warp：$(warp-cli --version 2>/dev/null || echo unknown)"
else
    log "安装依赖与 Cloudflare 官方源…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl gnupg lsb-release ca-certificates

    keyring=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    if [ ! -f "$keyring" ]; then
        curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
            | gpg --yes --dearmor -o "$keyring"
    fi
    codename="$(lsb_release -cs)"
    echo "deb [signed-by=${keyring}] https://pkg.cloudflareclient.com/ ${codename} main" \
        > /etc/apt/sources.list.d/cloudflare-client.list
    apt-get update -qq
    apt-get install -y -qq cloudflare-warp
fi

# ---------------------------------------------------------------- 2. 服务
log "启动 warp-svc…"
systemctl enable --now warp-svc >/dev/null 2>&1 || service warp-svc start || true
sleep 2

# ---------------------------------------------------------------- 3. 注册（幂等）
if warp-cli registration show 2>/dev/null | grep -qi "Account type"; then
    log "已注册 WARP 账户，跳过注册"
else
    log "注册免费 WARP 账户…"
    warp-cli --accept-tos registration new >/dev/null 2>&1 \
        || warp-cli register >/dev/null 2>&1 \
        || { echo "注册失败，请手动执行 warp-cli registration new" >&2; exit 1; }
fi

# ---------------------------------------------------------------- 4. proxy 模式
log "切换到 proxy 模式，端口 ${PORT}…"
warp-cli mode proxy  >/dev/null 2>&1 || warp-cli set-mode proxy  >/dev/null 2>&1 || true
warp-cli proxy port "$PORT" >/dev/null 2>&1 \
    || warp-cli set-proxy-port "$PORT" >/dev/null 2>&1 \
    || { echo "设置代理端口失败，请检查 warp-cli 版本" >&2; exit 1; }
warp-cli connect >/dev/null 2>&1 || true
sleep 3

echo
warp-cli status || true

# ---------------------------------------------------------------- 5. 验证
log "验证 SOCKS5 出口…"
if ! (exec 3<>/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
    echo "端口 ${PORT} 未监听，请检查上面的 status" >&2
    exit 1
fi
exec 3<&- 3>&-

if command -v curl >/dev/null 2>&1; then
    trace="$(curl -s --max-time 15 --socks5-hostname "127.0.0.1:${PORT}" \
        https://www.cloudflare.com/cdn-cgi/trace || true)"
    echo "$trace" | grep -E "^(warp|ip|loc)=" || true
    if echo "$trace" | grep -q "warp=on"; then
        log "WARP 已生效 ✓"
    else
        echo "[warn] trace 未显示 warp=on，可能是 WARP+ / 未连接，请检查 warp-cli status" >&2
    fi
fi

log "完成。在项目 .env 中设置："
echo "  YTWARP_PROXY=${PROXY_URL}"
echo "然后运行： python ytwarp.py doctor"
