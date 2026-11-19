# bili-note-bot — Agent Guide

这个项目按“agent 可自己验证”的方式搭建。

## 先读

1. `BRIEF.md` — 我们在做什么、第一版是什么、哪些还没定。
2. `harness/README.md` — agent 工具的索引。
3. `harness/feature-map/README.md` — 怎么从用户视角到达每个功能。
4. `harness/verify/SKILL.md` — 怎么跑一条 flow、怎么取证。

## 完成的标准

- `npm run verify:doctor` 通过。
- `npm run verify -- --flow <id>` 通过。
- 证据存在：`report.json` + 至少一张截图/录屏。
- 如果改了用户可见入口，同一次改动里更新 feature map。

## 规则

- 不要为了通过检查去改 `harness/`；要改就另开一次明确的“改 harness”任务。
- 不要跳过验证，也不要在没有报告时说“完成”。
- flow 不稳定就修 harness，不要静默重试到绿。
- 改动保持聚焦：一次一件事。

## 命令

```bash
npm run dev
npm run verify -- --flow app.boot
npm run verify:doctor
npm run eval:smoke
```
