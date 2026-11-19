---
name: verify-app
description: Boot the app, drive a named user flow, and produce evidence. Use before claiming any user-facing change is done.
---

# 什么时候用

在说“完成”之前。任何用户可见的改动，都要先跑一条 flow。

# 一条命令

```bash
npm run verify -- --flow <id>
```

# 前置条件

- 依赖已安装。
- `.env.test` 存在（可从 `.env.example` 复制）。
- 端口空闲。
- 应用已启动，或先运行 `bash harness/verify/bin/boot.sh`。

# 安装

```bash
npm install
npm install -D playwright tsx @types/node
npx playwright install chromium
```

如果 pnpm 报 `ERR_PNPM_IGNORED_BUILDS`，先运行 `pnpm approve-builds --all`。

# 步骤

1. `npm run verify:doctor`
2. `bash harness/verify/bin/boot.sh`（如果应用还没起）
3. `npm run verify -- --flow <id>`
4. 看 `report.json` 和截图

# 证据

- `harness/verify/artifacts/<run>/report.json`
- `home.png`（或对应 flow 的截图）
- 可选：录屏、console/network log

# 完成

- 所有硬断言通过。
- 证据文件存在。
- `report.json` 里 `status: pass`。

# 失败处理

- 启动失败：附 `dev.log`，不要先改业务代码。
- flow 失败：附截图和 trace，先判断是 app bug、map 过期，还是 harness 不稳定。
- 不允许无 trace 地重试超过一次。
