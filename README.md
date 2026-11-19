# bilibili_note

你在任意 B 站视频的评论区 @ 这个账号，它会下载这条视频（480p 足够）、抽出若干关键帧、交给多模态模型看完整片，再把「截图网格 + 分章节要点」排成一张 1080×1440 的卡片，通过私信发回给 @ 它的人。

适合长视频：三十分钟的访谈、教程、杂谈，与其快进着找重点，不如先看一张图决定值不值得看。

轮询 B 站「@我的」通知 → 下载 **480p** → 多模态总结 → 渲染单张 **1080×1440** 图文卡 → 私信发回给 @ 我的人。

- **总结模型**：OpenAI 兼容接口，默认 DeepSeek V4.1 Flash（`LLM_MODEL=deepseek-flash`）
- **交付**：`ego-browser` 驱动本机已登录的 B 站账号（**不需要 cookie**），旧的 cookie+wbi 实现保留为 `DELIVERY=api` 兜底
- **自动去重**：SQLite 记录 `bv → 卡片 / 发送状态`，同一 BV 永不重复跑模型
- **默认 dry-run**：没有 `--send` 就不会发任何私信

```
@我的通知 ──► 白名单/去重 ──► yt-dlp 480p ──► 12 帧均匀抽帧
                                                  │
    ego 私信发图 ◄── 1080×1440 PNG 卡片 ◄── LLM 结构化 JSON 总结
```

## 前置条件

1. **Python 3.11+**
2. **ego lite**：本机装好并**在它的浏览器里登录 bilibili.com**（默认交付通道靠它）
3. **ffmpeg**（抽帧 / 合并音视频）
4. **LLM API Key**（默认指向 `https://api.deepseek.com/v1`）

## 快速开始

```bash
cd bilibili_note
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium     # 渲染卡片用；已装可跳过
cp .env.example .env                      # 填 LLM_API_KEY 即可
```

只要求 `python3` 在 PATH 上：`main.py` 发现依赖缺失会自动 `exec` 到 `./.venv/bin/python`。

### 先跑只读探针

```bash
python3 main.py --browser-check
```

只用 ego 打开 `message.bilibili.com/#/at`，打印**是否已登录 / 抓到几条 @ / 第一条摘要**，绝不点击发送。
登录态来自 ego lite 的浏览器，本工具不碰 cookie。

### 三条常用命令

```bash
python3 main.py --selftest                    # 离线出图，不需要任何凭据
python3 main.py --at                          # 只拉 @ 通知并打印
python3 main.py --dry-run --bv BV1xx411c7mD   # 只跑生成，打印将要发送的内容
```

产物：`out/card.png`（selftest）与 `out/<BV>.png`（真实任务）。

## 第一次真实联调

顺序不能颠倒：

1. **朋友评论并 @ 你**。两种入口都支持，但落点不同：
   - 在**别人的视频**下 @ 你 → 「@ 我的」tab（`x/msgfeed/at`）
   - 在**你自己的视频**下评论并 @ 你 → 「回复我的」tab（`x/msgfeed/reply`）
   回复通道只认正文里带 `@<BOT_UNAME>` 的评论（在 `.env` 里配 `BOT_UNAME`），
   不会把「所有对我视频的评论」都当成请求。
2. `python3 main.py --at` —— 确认能解析出 `bv=BV...`、`mid=...`。
   两个通道会合并去重（同一 BV + 同一 mid 只算一条）。
3. `python3 main.py --loop --send` —— 开始常驻轮询并真实发送（`POLL_INTERVAL=300`）。
   发送前建议先用 `--dry-run` 看一眼将要发出的图片路径。

 单个补发时可以用 `--to` 指定收件人，并用 `--expect-uname` 做发送前断言：

```bash
python3 main.py --bv BV1xx --to 1234567 --expect-uname "示例账号" --send
```

  会话页昵称不一致会**中止且不发图**；已标记 `sent` 的 BV 不会重复发送（除非 `--force`）。

联调期注意：

- 首次私信**只发图片**（B 站对未关注/未回复的人只放行 1 条），文字稿不会发；
- `DAILY_LIMIT=10` 是每日真实发送上限；`ALLOW_MIDS` 留空时任何人 @ 都会处理，会打 warning；
- 发送失败会写 `data/bili_note.db` 的 `failures` 表并提示「需人工在评论区回复」。

## 命令

| 命令 | 作用 |
| --- | --- |
| `python3 main.py --browser-check` | 只读探针：登录态 + @ 条数（不发送） |
| `python3 main.py --at` | 只拉取并打印通知（@ + 回复两个通道，带白名单标记） |
| `python3 main.py --bv BV1xx` | 只处理一个视频：下载 + 抽帧 + 总结 + 渲染 |
| `python3 main.py --bv BV1xx --send` | 生成并通过 ego 发送 |
| `--to MID` / `--expect-uname NAME` | 指定收件人并断言会话昵称（不一致则中止） |
| `python3 main.py` | 轮询一次，逐条走完整流程（默认 dry-run） |
| `python3 main.py --send` | 轮询一次并真实发送 |
| `python3 main.py --loop --send` | 常驻轮询 |
| `python3 main.py --selftest` | 离线渲染自检（内置 fixture） |
| `--force` | 忽略 SQLite 缓存重新生成该 BV 的卡片 |
| `--verbose` | 打印调试日志与异常堆栈 |

退出码：`0` 成功，`1` 运行期错误，`2` 依赖缺失，`3` 配置/凭据缺失。

## 配置（.env）

| 变量 | 说明 |
| --- | --- |
| `LLM_BASE_URL` | OpenAI 兼容根地址，默认 `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 必填（除 `--selftest`/`--browser-check`） |
| `LLM_MODEL` | 默认 `deepseek-flash` |
| `DELIVERY` | `ego`（默认，免 cookie）或 `api`（旧实现） |
| `EGO_BIN` | 可选，`ego-browser` 绝对路径 |
| `ALLOW_MIDS` | 白名单 mid，逗号分隔；留空 = 不限制（会打 warn） |
| `DAILY_LIMIT` | 每日真实发送上限，默认 3；超限只记日志不发送 |
| `POLL_INTERVAL` | `--loop` 间隔秒数，默认 600 |
| `MAX_DURATION_MIN` | 超过该时长的视频跳过，默认 30 |
| `MAX_RETRIES` | 单步重试次数，上限 2 |
| `FRAME_COUNT` | 抽帧数（10~12），默认 12 |
| `SESSDATA` / `BILI_JCT` / `DEDEUSERID` | **仅 `DELIVERY=api` 需要** |

## 模型层

- 走 `POST {LLM_BASE_URL}/chat/completions`，图片用 `image_url` + `data:image/jpeg;base64,...`；
- 强制 `response_format={"type":"json_object"}`，只接受结构化 JSON；
- **降级**：若返回 4xx 且报文提到 image / vision / multimodal，自动去掉图片重试一次，日志打 `vision_fallback`；
  端点拒绝 `response_format` 时也会去掉它重试（`json_mode_fallback`）。
- 模型输出会被夹取到合法形状（3~5 章 × 2~3 要点，时间戳统一为秒）。

```json
{
  "title": "...", "up_name": "...", "duration": 213,
  "chapters": [{"heading": "...", "points": ["..."], "timestamp": 46}],
  "frames": [{"ts": 12, "reason": "..."}]
}
```

## 画质与抽帧

- yt-dlp：`bv*[height<=480]+ba/b[height<=480]/bv*+ba/b`，并 `format_sort=res:480`；
- ffmpeg 按视频时长**均匀**取 12 帧（`ts=(i+0.5)*duration/12`），角标为 `MM:SS`；
- 抽帧不放大：`scale=-2:min(480,ih)`，保持 480p 原始像素。

## 卡片内容

固定 1080×1440 PNG，只有「截图 + 总结」两段：

- 顶部：视频标题、UP 主、时长
- 中部：**12 帧 3 列网格**，每帧左下角 `MM:SS`
- 下部：3~5 个章节，每章 2~3 条要点（要点多时自动切 `dense` 字号，避免溢出）

排版全部在 `templates/card.html`。

## 私信交付（ego）

`send_dm(mid, image)` 的流程：

1. 打开 `https://message.bilibili.com/#/whisper/mid<mid>`
2. 点输入框工具栏的图片按钮 → 拦截文件选择器 → `setFiles([卡片绝对路径])`
3. B 站**选图即发送**（不需要点「发送」），脚本轮询是否出现新的 `data-content-type="picture"` 气泡确认成功

> B 站对「未关注 / 未回复」的人只放行 **1 条**消息，所以只发图片（卡片本身即交付物）。
> 失败会写 `failures` 表并提示「需人工在评论区回复」，不会静默吞掉。

`DELIVERY=api` 时保留旧路径：图床上传 + `send_msg`（`21047` / `21046` / `25003` 处理逻辑不变）。

## 目录结构

```
bilibili_note/
├── main.py                 # CLI：browser-check / selftest / at / bv / loop / send
├── config.py               # .env 解析、路径、通道开关
├── storage.py              # SQLite：videos / at_seen / failures / quota / contacts
├── util.py                 # 错误类型、日志、重试、MM:SS
├── bili/
│   ├── ego.py              # ego-browser：抓 @ / 发图私信（默认通道）
│   ├── at.py               # 旧通道：x/msgfeed/at + BV 提取
│   ├── auth.py wbi.py      # 旧通道：cookie / wbi 签名
│   ├── upload.py send.py   # 旧通道：图床 + send_msg
├── pipeline/
│   ├── download.py         # yt-dlp 480p + 均匀抽帧
│   ├── summarize.py        # OpenAI 兼容多模态 + JSON 归一化 + 降级
│   └── render.py           # Jinja2 → Playwright 截图 1080×1440
├── templates/card.html     # 唯一排版来源
├── fixtures/sample.json    # selftest 用的示例总结（12 帧）
├── tests/                  # 离线单测：summarize 降级 / ego 解析 / 抽帧 / 存储
├── requirements.txt
└── .env.example
```

运行时目录（gitignore）：`data/`、`out/`、`work/`、`logs/`。

## 开发

```bash
python3 -m compileall .                                  # 语法检查
.venv/bin/python -m unittest discover -s tests -t .      # 离线单测
```

## 排查

| 现象 | 处理 |
| --- | --- |
| `未找到 ego-browser` | 安装 ego lite，或用 `EGO_BIN` 指定路径 |
| `ego 浏览器里没有登录 B 站` | 在 ego lite 的浏览器窗口登录 bilibili.com 后重跑 |
| `Playwright 浏览器未安装` | `.venv/bin/playwright install chromium`（会尝试复用已有缓存） |
| 中文变方块 | 需要 PingFang SC / Hiragino Sans GB / Noto Sans CJK；Linux 装 `fonts-noto-cjk` |
| `缺少 LLM_API_KEY` | 在 `.env` 填 `LLM_API_KEY` |
| 端点不支持图片 | 自动 `vision_fallback` 纯文本重试（日志会标注） |
| `未找到 ffmpeg` | `brew install ffmpeg` |
| 想重跑某个 BV | `--bv BV1xx --force` |

## 使用边界

这是**个人自用工具**，不是面向第三方的服务：

- 作者不提供代他人批量总结、代运营或任何托管服务；
- 使用者需自备账号与 API key，自行承担 B 站账号风控、频控与内容合规风险；
- 请只处理你本人收到/被 @ 的通知，不要用它抓取或骚扰他人。
