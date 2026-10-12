# 本地 AI 协作工作台

纯本地运行的多人（多 Agent）协作工作台：**FastAPI + Streamlit**，数据全部落在本机，不经过任何第三方服务器。核心是「协调员带你干项目」——你只跟协调员一对一沟通，中间所有 Agent 的执行过程在一个只读的内部群里全程透明。

## 特性

- **双视图隔离**：协调员私聊窗（只收结果类消息）+ 内部 Agent 群聊窗（全量过程，只读）。消息按 `visibility` 分级，前端自动过滤。
- **群聊内进度实时展示**：同一任务只在群里占**一条**进度消息，原地上新不刷屏；支持分阶段、百分比、状态标识、耗时、任务取消。
- **统一进度上报**：所有 Agent 走同一套 `ProgressReporter`，新增 Agent 无需改前端。
- **分层上下文记忆**：长期项目档案（目标/结论/待办/偏好）+ 滚动摘要 + 近期原文窗口；超阈值自动压缩，稳定前缀对前缀 KV 缓存友好。
- **记忆可编辑**：前端面板可查看、手动修正、清空协调员的长期记忆。
- **多端同源**：绑定 `0.0.0.0`，PC 与手机浏览器访问同一地址，界面自适应（PC 左右分栏 / 手机底部导航）。
- **可插拔 Agent**：协调员、Workbuddy、豆包、Trae 四个连接器；外部服务未配置时回退为内置本地实现，仍产出真实文件。协调员对接 oMLX（OpenAI 兼容）本地模型。
- **本地导出文件导入**：支持把本地导出的聊天记录（CSV / JSON / TXT）导入项目，解析为统一记录并据此生成客户意向摘要等产物；不再使用随机假数据。
- **访问认证**：设置 `WORKBENCH_PASSWORD` 后，REST 接口、WebSocket 连接与文件下载全链路校验令牌；密码留空则开箱即用、不鉴权。
- **能力注册表（可插拔任务）**：可执行任务集中登记在 `backend/capabilities.py`（名称 / 说明 / 关键词 / 执行器），协调员据表路由；新增能力无需改动路由代码。

## 快速开始

```bash
git clone https://github.com/aassaadd/local-ai-workbench.git
cd local-ai-workbench
pip install -r requirements.txt
./run.sh
```

- 前端：http://localhost:8501
- 后端：http://localhost:8080
- 手机（同一 WiFi）：`http://<本机局域网IP>:8501`

首次启动会自动创建 `data/`（SQLite 库与项目目录），该目录已在 `.gitignore` 中排除，不会提交。

## 界面结构

```
PC（宽度 > 768px）                     手机（宽度 ≤ 768px）
┌─────────┬──────────────────────┐     ┌──────────────────────┐
│ 项目列表 │ 🔹与协调员 ○内部群聊  │     │ 📂 项目A          ⋮  │
│ 项目A    │                      │     │  消息流（自适应宽度） │
│ 项目B    │  消息流（气泡）       │     │                      │
│          │                      │     ├──────────────────────┤
│ 设置     │  输入框（仅私聊可见）  │     │ 💬 私聊    🧑🤝🧑 群聊 │
└─────────┴──────────────────────┘     └──────────────────────┘
```

- **私聊视图**：只渲染 `visibility=all` 的消息（最终结果、需确认的问题、告警），有输入框。
- **内部群聊视图**：渲染全部消息（任务分发、进度、中间文件、Agent 间沟通），只读、无输入框。

## 进度系统

状态与颜色：

| 状态 | 颜色 | 说明 |
|---|---|---|
| pending | 灰 | 已派发，等待执行 |
| running | 蓝 | 执行中，进度条动画 |
| success | 绿 | 完成，100% |
| failed | 红 | 失败，展示错误原因 |
| cancelled | 灰 | 已取消 |

上报默认按 `PROGRESS_THROTTLE_MS`（500ms）节流；任务完成后进度与耗时落库 `progress_history`，可回溯。

## 上下文与记忆

装配顺序（稳定前缀，便于前缀缓存命中）：

```
system 提示词 → 项目档案 → 滚动摘要 → 近期原文 N 轮
```

压缩规则：token 估算超过 `CONTEXT_MAX_TOKENS` 时，把较早轮次压成摘要并持久化；始终保留最近 `CONTEXT_KEEP_TURNS` 轮原文。每积累 `CONTEXT_PROFILE_REFRESH_TURNS` 轮新对话刷新一次长期档案。有本地模型时用 LLM 抽取/摘要，未配置时规则式兜底。

## 导入聊天记录

核心产物（如客户意向摘要）建立在**本地导入的真实导出文件**上，不再随机生成假数据。支持 CSV / JSON / TXT 三种格式。

两种导入方式：

1. **前端上传**：在侧栏的「导入聊天记录」上传区选择文件，上传后写入该项目 `data/projects/<项目>/imports/`。
2. **直接放置**：把导出文件直接复制到 `data/projects/<项目>/imports/` 目录即可，系统按文件名/内容自动识别。

统一记录结构（解析后的内部表示）：

```json
{"contact": "姓名", "company": "公司", "msgs": [{"role": "user|contact", "text": "内容", "time": 秒级时间戳}], "time": 秒级时间戳}
```

**同一联系人的多行会自动合并为一个会话**（按 `contact` 聚合，`msgs` 按 `time` 排序）。三种格式的字段说明：

| 格式 | 结构 |
|---|---|
| CSV | 表头 `contact,company,role,text,time`；`role` 取 `user` / `contact`，`time` 为 `YYYY-MM-DD HH:MM:SS` |
| JSON | `{"records": [{"contact","company","msgs":[{"role","text","time"}],"time"}, ...]}`（也兼容顶层数组） |
| TXT | 按会话分节（如 `联系人: 张三` 起始），节内每行一条消息 |

示例文件见 `samples/`：

- `samples/chat_export_sample.csv`：销售场景多联系人导出，覆盖高 / 中 / 低意向。
- `samples/chat_export_sample.json`：另一批联系人，字段结构与上表一致。

新项目无数据时可在前端点击「载入示例数据」，把 `samples/` 内的示例文件写入该项目 `imports/`，随后即可跑通摘要流程。

## 访问认证

默认（`WORKBENCH_PASSWORD` 为空）不校验任何请求，前端不显示登录界面，开箱即用。

设置 `WORKBENCH_PASSWORD` 后，以下链路都需携带令牌：

- **REST 接口**：请求头 `X-Auth-Token: <密码>`；未携带或错误返回 `401`。
- **WebSocket**：连接地址附带查询参数，如 `ws://host:8080/ws/<项目>?token=<密码>`。
- **文件下载**：`<a>` 直链无法自定义请求头，支持 `?token=<密码>` 查询参数校验。

前端在未认证时会先展示密码输入，校验通过后将令牌写入会话状态，后续请求自动附带。

## 扩展一个新能力

可执行任务集中登记在 `backend/capabilities.py`，协调员（`agents/coordinator.py`）查表路由，**新增能力只需在注册表登记，无需改动路由逻辑**。

在注册表中追加一条能力即可：

- `key`：能力唯一标识（如 `chat_summary`）。
- `title`：展示名称。
- `description`：能力说明，供本地模型选择与关键词打分参考。
- `keywords`：关键词列表，无本地模型时用于打分兜底。
- `handler`：执行器，负责派发对应 Agent 并推进进度。

配置了本地模型时，协调员让模型输出 `{"capability": "...", "args": {...}}` 直接派发；未配置模型时按关键词/说明打分选择，无命中则回退通用对话并列出可用能力清单。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKBENCH_HOME` | 项目根目录 | 数据根目录 |
| `WORKBENCH_HOST` / `WORKBENCH_PORT` | `0.0.0.0` / `8080` | 后端绑定 |
| `WORKBENCH_API` | `http://127.0.0.1:8080` | 前端访问后端的地址 |
| `WORKBENCH_PASSWORD` | 空 | 访问密码；**非空时真正生效**，REST（`X-Auth-Token` 头）/ WebSocket（`?token=`）/ 文件下载（`?token=`）均需令牌，留空则开箱即用不鉴权 |
| `OMLX_BASE_URL` / `OMLX_API_KEY` / `OMLX_MODEL` | 空 | 协调员本地模型（OpenAI 兼容） |
| `DOUBAO_BASE_URL` / `DOUBAO_API_KEY` / `DOUBAO_MODEL` | 空 | 豆包连接器 |
| `WORKBUDDY_URL` / `WORKBUDDY_CMD` | 空 | Workbuddy 连接器 |
| `TRAE_URL` | 空 | Trae 连接器 |
| `PROGRESS_THROTTLE_MS` | `500` | 进度上报节流 |
| `CONTEXT_MAX_TOKENS` | `3000` | 压缩触发阈值 |
| `CONTEXT_KEEP_TURNS` | `6` | 保留的近期原文轮数 |
| `CONTEXT_SUMMARY_MAX_CHARS` | `600` | 摘要字数上限 |
| `CONTEXT_PROFILE_MAX_CHARS` | `800` | 项目档案字数上限 |
| `CONTEXT_PROFILE_REFRESH_TURNS` | `4` | 每 N 轮刷新长期档案 |
| `CONTEXT_STABLE_PREFIX` | `1` | 稳定前缀（前缀缓存友好） |

数据目录说明：

- `samples/`：仓库内置的示例导出文件（`chat_export_sample.csv` / `chat_export_sample.json`），可通过前端「载入示例数据」一键写入项目 `imports/` 试跑。
- `data/projects/<项目>/imports/`：项目导入数据目录，存放本地导出的聊天记录文件（CSV / JSON / TXT），首次创建项目时自动建立。

## 目录结构

```
backend/
  main.py          FastAPI 路由 + WebSocket 多房间总线
  bus.py           统一消息出口（落库 → 广播）
  models.py        消息结构体（含 visibility / progress 字段）
  db.py            SQLite：群聊全量、私聊过滤、进度历史、记忆
  auth.py          访问认证（令牌校验依赖 + WebSocket token 校验）
  projects.py      项目目录管理（自动建 public/private/imports、归档）
  importer.py      本地导出文件解析（CSV / JSON / TXT → 统一记录）
  capabilities.py  能力注册表（可插拔任务：名称/说明/关键词/执行器）
  progress.py      ProgressReporter（节流 / 分阶段 / 取消 / 耗时）
  tasks.py         活跃任务表（重连同步、取消标记）
  memory.py        分层记忆与上下文压缩
  llm.py           oMLX / OpenAI 兼容适配器（连不上回退规则引擎）
  agents/          coordinator / workbuddy / doubao / trae
frontend/
  app.py           双视图主界面 + 自动刷新
  ui.py            文本 / 文件 / 进度条渲染组件
  styles.py        响应式 CSS（PC 分栏 / 手机底部导航）
  ws_client.py     后台 WebSocket 客户端（自动重连）
  api.py           REST 客户端
samples/           示例导出文件（CSV / JSON）
run.sh             一键启动
```

## 技术栈

Python 3 · FastAPI · Uvicorn · WebSocket · SQLite · Streamlit · Pydantic

## 更多文档

- 架构与数据流（含流程图）：[docs/architecture.md](docs/architecture.md)
- 环境变量示例：[.env.example](.env.example)
- 许可证：[MIT](LICENSE)

