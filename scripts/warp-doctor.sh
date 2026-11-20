#!/usr/bin/env bash
# 单独检查 WARP 是否真的在换出口（不依赖 Python）。
#   bash scripts/warp-doctor.sh [port]
set -uo pipefail

PORT="${1:-${WARP_PORT:-40000}}"
echo "== WARP doctor (port ${PORT}) =="

if (exec 3<>/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
    exec 3<&- 3>&-
    echo "[ok] 127.0.0.1:${PORT} 正在监听"
else
    echo "[fail] 127.0.0.1:${PORT} 未监听 → 先运行 scripts/setup-warp-linux.sh"
    exit 1
fi

echo
echo "-- 直连出口 --"
curl -s --max-time 12 https://www.cloudflare.com/cdn-cgi/trace | grep -E "^(ip|loc|warp)=" || true
echo
echo "-- 经 WARP SOCKS5 出口 --"
curl -s --max-time 15 --socks5-hostname "127.0.0.1:${PORT}" \
    https://www.cloudflare.com/cdn-cgi/trace | grep -E "^(ip|loc|warp)=" || true

echo
if command -v warp-cli >/dev/null 2>&1; then
    echo "-- warp-cli status --"
    warp-cli status || true
fi

echo
echo "结论：第二段出现 warp=on 且 ip 与直连不同，说明代理已生效。"
echo "若 yt-dlp 仍报 'Sign in to confirm you're not a bot'，再运行： python ytwarp.py doctor"
