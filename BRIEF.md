# Brief

## 需求

朋友在 B 站视频评论区 @ 我的账号，bot 看完这条视频，把「视频截图 + 分章总结」排版成一张图，私信发回给 @ 我的人。

## 谁 / 什么时候用

我自己 + 1~2 个朋友。看到长视频、想快速知道「讲了什么、值不值得看」的时候用。

## 第一版

1. 轮询「@我的」通知，解析出 BV 号
2. `yt-dlp` 下载最低可用清晰度（480p）
3. `ffmpeg` 抽 12 帧 + 取字幕（无字幕时降级为纯画面理解）
4. DeepSeek V4.1 Flash 看帧 + 文本，输出结构化 JSON
5. HTML 模板 → Playwright 截图，输出单张 1080×1440 PNG
6. 用 ego-browser（本机已登录的 ego lite）打开私信，上传图并发送
7. SQLite 去重 + 白名单 + 每日限额；失败落 `failed` 表，不静默吞掉

## 先不做

Web UI、多用户/多租户、云端部署、支付、多模型切换、评论自动回复、自建 ASR、多图轮播。

## 技术

- Python 3.14：`yt-dlp` / `ffmpeg` / `Jinja2` / Playwright 截图 / `sqlite3`
- Node 26：只用于 ego-browser 桥接（`ego-browser nodejs` 走 stdin）和验证 harness（tsx）

备选：全 Node/TS。放弃理由是 Python 侧音视频处理脚本更成熟，且现有骨架已按 Python 落地。

## 假设

- 单机常驻，用户已在本机 ego lite 登录 B 站
- 每天 ≤ 20 条，单条视频 ≤ 30 分钟
- 对方已关注 bot 账号，避免 `21047` 单条限制和「未关注人消息」折叠箱

## 待定

- DeepSeek 官方 API 是否接受多图 `image_url` 输入。先按 OpenAI 兼容实现，失败自动降级纯文本
- 480p 关键帧在 1080 宽卡片里的可读性，需要实拍验证后再定抽帧尺寸
- ego-browser 在私信页的选择器稳定性（B 站前端改版会失效）
- 是否需要在评论区补一句「已私信」兜底
