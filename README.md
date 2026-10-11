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

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKBENCH_HOME` | 项目根目录 | 数据根目录 |
| `WORKBENCH_HOST` / `WORKBENCH_PORT` | `0.0.0.0` / `8080` | 后端绑定 |
| `WORKBENCH_API` | `http://127.0.0.1:8080` | 前端访问后端的地址 |
| `WORKBENCH_PASSWORD` | 空 | 可选访问密码 |
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

## 目录结构

```
backend/
  main.py        FastAPI 路由 + WebSocket 多房间总线
  bus.py         统一消息出口（落库 → 广播）
  models.py      消息结构体（含 visibility / progress 字段）
  db.py          SQLite：群聊全量、私聊过滤、进度历史、记忆
  projects.py    项目目录管理（自动建 public/private、归档）
  progress.py    ProgressReporter（节流 / 分阶段 / 取消 / 耗时）
  tasks.py       活跃任务表（重连同步、取消标记）
  memory.py      分层记忆与上下文压缩
  llm.py         oMLX / OpenAI 兼容适配器（连不上回退规则引擎）
  agents/        coordinator / workbuddy / doubao / trae
frontend/
  app.py         双视图主界面 + 自动刷新
  ui.py          文本 / 文件 / 进度条渲染组件
  styles.py      响应式 CSS（PC 分栏 / 手机底部导航）
  ws_client.py   后台 WebSocket 客户端（自动重连）
  api.py         REST 客户端
run.sh           一键启动
```

## 技术栈

Python 3 · FastAPI · Uvicorn · WebSocket · SQLite · Streamlit · Pydantic

## 更多文档

- 架构与数据流（含流程图）：[docs/architecture.md](docs/architecture.md)
- 环境变量示例：[.env.example](.env.example)
- 许可证：[MIT](LICENSE)

