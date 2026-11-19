# Agent Harness

三件套：

- `feature-map/` — 用户怎么到达每个功能。
- `verify/` — 怎么启动、操作、取证、断言。
- `evals/` — 怎么给 agent 和 harness 打分。

## 索引

- `verify/SKILL.md` — 一条命令跑一条 flow。
- `feature-map/README.md` — 地图约定。
- `evals/rubric.md` — 硬门和评分。

## 加一个功能

1. 加 `feature-map/features/<feature>.md`。
2. 加 `verify/flows/<feature>.<action>.ts`。
3. 有风险就加 `evals/cases/NNN-...md`。
4. 需要时更新 `AGENTS.md` 的完成标准。

## 边界

- agent 可以改 `src/`。
- agent 可以读 `harness/`。
- 改 `harness/` 需要单独 review，不要在普通任务里顺手改。
