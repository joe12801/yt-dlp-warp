# Cookie：到底要不要？

## 结论

**公开视频 + WARP 生效时，不需要 cookie。** 本项目默认零 cookie，`YTWARP_COOKIES` 留空。

`Sign in to confirm you're not a bot`（「登录以确认你不是机器人」）这句话很容易误导人：它**不是**在说「你没登录所以不给看」，而是 YouTube 风控认为「这个出口 IP 可疑」。Oracle Cloud、AWS、GCP、各类 VPS 的 IP 段最常触发。此时加 cookie 只是把「可疑 IP + 登录态」组合起来碰运气，换出口才是根治。

## 什么时候真的需要 cookie

| 情况 | 是否需要 | 说明 |
| :--- | :--- | :--- |
| 公开视频，WARP 出口干净 | 不需要 | 默认路径 |
| 年龄限制（18+）视频 | **必须** | 需要成年账号登录态 |
| 会员 / 频道专属 / 私有 / 未列出但需授权 | **必须** | 需要对应账号登录态 |
| 地区限制内容 | 视情况 | WARP 出口地区也影响；必要时配合账号 |
| 部分高码率 / 需要 PO Token 的格式 | 可能需要 | yt-dlp 会明确报「Login required」 |
| WARP 出口偶尔也被风控 | 偶尔需要 | 先用 `python ytwarp.py doctor` 确认，再补 |

判断顺序建议：

1. `bash scripts/warp-doctor.sh` → 确认 `warp=on` 且 IP 已变；
2. `python ytwarp.py doctor` → 用公开视频实探，成功就是「不需要 cookie」；
3. 仍报 bot 校验 → 先 `warp-cli disconnect && warp-cli connect` 换一次出口；
4. 目标内容本身需要登录 → 再按下面步骤加 cookie。

## 安全做法（重要）

### ❌ 不要用 `--cookies-from-browser`

Chrome 127+ 的 **App-Bound Encryption（v20）** 把登录 cookie 绑定到原 profile 环境。任何「重启 Chrome / 复制 profile / 调试端口」的自动提取，都会让 Chrome 判定环境变化并丢弃 v20 登录 cookie —— 表现就是**账号被退出**。yt-dlp 读取时还可能锁定 profile 文件。

本项目默认禁用；显式给 `--cookies-from-browser` 会打印警告。

### ✅ 用 Cookie-Editor 导出 + 独立 cookies.txt

1. 在**正在运行的 Chrome** 里打开 `youtube.com`，确认是登录状态；
2. 用 **Cookie-Editor** 扩展导出 JSON（复制或存成 `exported.json`）；
3. 转换：

   ```bash
   python scripts/cookie-editor-to-netscape.py --input exported.json --out cookies.txt --verify
   ```

   脚本只保留 YouTube / Google 相关域名，输出权限 `0600`，**不会打印任何 cookie 值**；
4. 使用时：

   ```bash
   python ytwarp.py --cookies cookies.txt URL
   ```

### 为什么主 cookie 文件全程只读

yt-dlp 的 `YoutubeDL.close()` 只要设置了 `cookiefile` 就会调用 `cookiejar.save()` 回写文件，而回写结果会**丢失 `#HttpOnly_` 前缀的登录态**（SID / HSID / SSID / SAPISID / LOGIN_INFO / `__Secure-1PSID` ...）。一旦丢失，之后所有请求又会回到 bot 校验。

所以 `ytwarp.py` 会先把 `cookies.txt` 复制成临时快照，只把快照交给 yt-dlp，退出时删掉快照。**原文件永不被改写、永不被删除**，浏览器里的登录 cookie 也不受影响。

### 保管

- `cookies.txt`、`.env`、`exported.json` 都在 `.gitignore` 里，**不要提交、不要贴到聊天/工单**；
- cookie 等于账号凭证，泄露后请立刻在 Google 账号里退出所有会话并重新导出；
- 定期检查登录态是否过期（重新导出一次即可）。

## 常见误解

> 「我加了 cookie 还是下不了」

多半是 WARP 没连上，或者环境里还有 `http_proxy` / `https_proxy` 把请求又带回被标记的出口。`ytwarp.py` 始终显式传 `--proxy`（空值代表强制直连并忽略环境代理），可用 `--print-command` 看实际命令核对。

> 「yt-dlp 报 `no video formats`」

这通常是 YouTube 的 JS challenge 没过，跟 cookie 无关：升级 yt-dlp、装 `yt-dlp-ejs` + Node/Deno，见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
