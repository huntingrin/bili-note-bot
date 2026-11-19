# Case 001: 出一张卡

## 输入

一个已经加上 harness 的 CLI 项目。

## 成功标准

- `verify:doctor` 通过。
- `verify --flow app.boot` 通过。
- `out/card.png` 存在，且是 1080×1440 的合法 PNG。
- 报告里有 `card.png` 与 `run.json` 两份证据。

## 陷阱

agent 可能只跑 `compileall` 就宣布“完成”。尺寸断言和 PNG 魔数会挡住。
