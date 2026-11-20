# 启用 Windows 版 Cloudflare WARP 的 proxy 模式（只开本地 SOCKS5，不改全局路由）。
# 以管理员身份运行：
#   powershell -ExecutionPolicy Bypass -File scripts/setup-warp-windows.ps1
$ErrorActionPreference = 'Stop'
$Port = if ($env:WARP_PORT) { [int]$env:WARP_PORT } else { 40000 }

$cli = "C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
if (-not (Test-Path $cli)) {
    Write-Host '未找到 warp-cli.exe，请先安装官方客户端：' -ForegroundColor Yellow
    Write-Host '  https://1111-releases.cloudflareclient.com/windows/Cloudflare_WARP_Release-x64.msi'
    Write-Host '  静默安装： msiexec /i Cloudflare_WARP.msi /quiet /norestart'
    exit 1
}

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '请以管理员身份运行 PowerShell。' -ForegroundColor Red
    exit 1
}

$svc = Get-Service CloudflareWARP -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host 'CloudflareWARP 服务不存在，请先安装客户端。' -ForegroundColor Red; exit 1 }
if ($svc.Status -ne 'Running') { Start-Service CloudflareWARP; Start-Sleep -Seconds 2 }

$reg = (& $cli registration show 2>&1 | Out-String)
if ($reg -notmatch 'Account type') {
    Write-Host '首次使用，注册免费 WARP 账户…'
    & $cli --accept-tos registration new | Out-Null
}

& $cli mode proxy | Out-Null
& $cli proxy port $Port | Out-Null
& $cli connect | Out-Null
Start-Sleep -Seconds 3

Write-Host '--- warp-cli status ---'
& $cli status

$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listen) {
    Write-Host "SOCKS5 端口 $Port 未监听，请检查 status 与防火墙。" -ForegroundColor Red
    exit 1
}
Write-Host "WARP SOCKS5 已就绪：socks5://127.0.0.1:$Port" -ForegroundColor Green
Write-Host '在 .env 中设置 YTWARP_PROXY=socks5://127.0.0.1:'$Port' 后运行 python ytwarp.py doctor'
Write-Host '验证出口： curl -s --socks5-hostname 127.0.0.1:'$Port' https://www.cloudflare.com/cdn-cgi/trace'
Write-Host ('关闭隧道： & "' + $cli + '" disconnect') -ForegroundColor DarkGray
