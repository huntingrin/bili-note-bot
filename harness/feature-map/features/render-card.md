---
id: render-card
entry_points:
  - "python3 main.py --selftest"
  - "python3 main.py --bv <BV号>"
outputs: ["out/card.png"]
last_verified: 2026-11-19
---

## 是什么

把一条视频渲染成单张 1080×1440 的图文卡：上方视频关键帧网格，下方分章总结。

## 前置条件

- `--selftest`：无外部依赖，用 `fixtures/sample.json`。
- `--bv`：需要 `LLM_API_KEY`，且本机可运行 `yt-dlp` / `ffmpeg`。

## 用户路径

1. 执行命令。
2. 终端打印视频标题、章节数、输出路径。
3. 打开 `out/card.png`，看到截图 + 总结两段式排版。

## 状态与边界

- 缺 `LLM_API_KEY` → 退出码 3，打印修复提示，不抛堆栈。
- 同一 BV 已生成过 → 命中去重，不重复调用模型。
- 模型拒绝图片输入 → 自动降级纯文本，日志标注 `vision_fallback`。

## 不要做什么

- 不要在验证时跳过尺寸断言（必须 1080×1440）。
- 不要把 GIF/动图当输入。
