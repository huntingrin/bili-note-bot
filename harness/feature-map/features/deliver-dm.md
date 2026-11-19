---
id: deliver-dm
entry_points:
  - "python3 main.py --browser-check"
  - "python3 main.py --bv <BV号> --send"
  - "python3 main.py --loop"
outputs: ["data/bili_note.db", "logs/"]
last_verified: 2026-11-19
---

## 是什么

用本机 ego lite（已登录 B 站）读取「@我的」，并把生成好的卡片私信发给对方。

## 前置条件

- 本机 `ego-browser` 可用，且该浏览器里已登录 B 站账号。
- `DELIVERY=ego`（默认）。

## 用户路径

1. `--browser-check`：只读探针，打开消息页，打印登录态和抓到的 @ 条数。
2. `--bv <BV> --send`：生成后发送给指定 mid。
3. `--loop`：定时轮询，命中白名单才处理。

## 状态与边界

- 对方未关注时只能发 1 条（`21047`）：首条必须是图。
- 发送失败写入 `failures` 表，打印「需人工在评论区回复」，不静默吞。
- 每日超过 `DAILY_LIMIT` 只记日志，不发送。

## 不要做什么

- 不要在 `--browser-check` 里点击发送。
- 不要对白名单外的 mid 发起会话。
