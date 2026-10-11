# 架构说明

## 1. 总体架构

```mermaid
flowchart LR
    U["你（浏览器 · PC/手机）"] -->|":8501"| FE["前端 Streamlit<br/>frontend/app.py"]
    FE <-->|"WebSocket 长连接"| BUS["消息总线<br/>ConnectionManager"]
    FE -->|"REST"| API["后端 FastAPI<br/>backend/main.py"]

    API --> DB[("SQLite<br/>data/workbench.db")]
    API --> PROJ["项目目录<br/>data/projects/*/public|private"]

    CO["协调员 Agent"] --> BUS
    WB["Workbuddy Agent"] --> BUS
    DB2["豆包 Agent"] --> BUS
    TR["Trae Agent"] --> BUS

    CO --> MEM["分层记忆<br/>memory.py"]
    MEM --> DB
    BUS --> DB
    WB --> PROJ
    DB2 --> PROJ
```

- 前端与后端分离：前端只做渲染与交互，状态与数据全在后端。
- 消息统一从总线出口（`bus.py`）发出：**先落库，再广播**，保证历史与实时一致。
- 所有数据落在本地 `data/`，不经过任何第三方服务器。

## 2. 双视图与消息分级

协调员对每条消息标记可见性：`all`（私聊 + 群聊）或 `internal`（仅群聊）。

```mermaid
flowchart TD
    M["消息 BaseMessage<br/>visibility = all | internal"] --> DISP["dispatch_message"]
    DISP --> G["写入群聊历史（全量）"]
    DISP --> C{"visibility == all ?"}
    C -->|是| P["写入私聊历史"]
    C -->|否| X["跳过私聊"]
    G --> BRO["WebSocket 广播"]
    P --> BRO
    X --> BRO
    BRO --> F1["私聊视图：仅渲染 all"]
    BRO --> F2["群聊视图：渲染全部（只读）"]
```

- 用户永远只能与协调员对话，无法在内部群直接发言。
- 两个视图读同一份数据，实时同步；切换项目时两视图一起切换。

## 3. 进度上报与原地更新

```mermaid
sequenceDiagram
    participant A as Agent 任务
    participant R as ProgressReporter
    participant B as 消息总线
    participant F as 前端
    A->>R: update(current, step)
    R->>R: 节流（默认 500ms）
    R->>B: broadcast_progress(task_id, percent, status)
    B->>B: 更新活跃任务表（终态则移除）
    B-->>F: 推送进度消息
    F->>F: 按 task_id 覆盖同一条消息（不新增气泡）
    A->>R: finish() / fail()
    R->>B: 终态消息
    B->>B: 落库 progress_history（含耗时）
    B-->>F: 更新为 100% / 失败原因
```

要点：

- 同一任务在群里**只有一条**进度消息，更新时原地刷新，不刷屏。
- 前端重连时通过活跃任务表补齐所有进行中任务的当前进度。
- 新增 Agent 只需调用 `ProgressReporter`，前端无需改动。

## 4. 分层记忆与上下文压缩

```mermaid
flowchart TD
    S["build_context(project)"] --> L1["读取项目档案 Profile"]
    S --> L2["读取滚动摘要 Summary"]
    S --> L3["读取近期原文窗口 Recent"]
    L1 --> EST["估算 token"]
    L2 --> EST
    L3 --> EST
    EST --> Q{"超过 CONTEXT_MAX_TOKENS ?"}
    Q -->|否| ASM
    Q -->|是| SUM["较早轮次 → 摘要（LLM，失败回退规则式）"]
    SUM --> SAVE["持久化摘要"]
    SAVE --> PROF["刷新长期档案（结论/待办/偏好）"]
    PROF --> TRIM["保留最近 K 轮原文"]
    TRIM --> ASM["装配 messages<br/>system → 档案 → 摘要 → 近期原文"]
    ASM --> OUT["发给本地模型"]
```

- 三层记忆：长期档案（跨会话）、中期摘要、近期原文。
- 前缀（`system + 档案 + 摘要`）内容与顺序稳定，便于推理服务命中前缀 KV 缓存。
- 前端「协调员记忆（可编辑）」面板可查看、修正、清空长期记忆。

## 5. 关键设计取舍

| 决策 | 原因 |
|---|---|
| 消息统一走 `bus.py` 出口 | 落库与广播顺序可控，避免历史/实时不一致 |
| 进度按 `task_id` 原地更新 | 长任务不刷屏，多个任务并行时各自独立 |
| 前端按 `visibility` 过滤而非后端分库返回 | 两个视图共享一份数据，切换零延迟 |
| 外部 Agent 未配置时回退本地实现 | 无依赖即可跑通完整链路，便于验证与二次开发 |
| 记忆分三层而非无限长上下文 | 在有限上下文窗口下兼顾远期脉络与近端精确 |
