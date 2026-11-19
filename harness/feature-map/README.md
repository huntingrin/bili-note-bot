# Feature Map

一个功能一个文件，从用户视角写。

## 规则

- 回答：是什么、怎么到达、看到什么、会出什么错。
- 写稳定的入口（命令名、参数），不要依赖终端文案。
- 不写实现细节；实现会变，用户路径更稳定。
- 改了用户可见入口，就在同一次改动里更新对应文件。
- 保持 `last_verified` 是最新的。

## 文件模板

看 `features/render-card.md`。

## 命名

- 文件：`<feature>.md`，例如 `auth.md`、`projects.md`。
- `id`：`feature.action`，例如 `project.create`。
- 跨功能流放 `flows/`，例如 `onboarding.md`。
