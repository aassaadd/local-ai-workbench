# 本地 AI 协作工作台 · 完善为可用产品 Spec

## Why
当前项目"能启动、能演示"，但存在三处硬伤，使它停留在"看起来完整"而非"真正可用"：

1. **数据是假的**：Workbuddy 的 `_generate_local()` 随机生成 110~140 条虚构聊天记录，客户意向摘要建立在假数据上，产物不可信。
2. **协调员是伪智能**：`Coordinator._detect()` 只认两组硬编码关键词（聊天记录 / 整理文件），其余一律走通用对话，"多 Agent 协同"实际只有两条写死流水线。
3. **安全配置未落地**：`WORKBENCH_PASSWORD` 在 `config.py` 定义后从未被任何路由校验，而服务绑定 `0.0.0.0`，同一局域网内任何人都能读取全部消息与下载项目文件。

本轮目标：让核心流程跑在真实导入数据上、让访问控制真正生效、让协调员可扩展地理解需求、并补齐关键交互。

## What Changes
- **新增本地导出文件导入**：支持 CSV / JSON / TXT 聊天记录导入，解析为统一记录结构；新增 `imports/` 目录与上传接口。**（BREAKING）** 移除 Workbuddy 的随机数据生成默认行为。
- **新增访问认证**：`WORKBENCH_PASSWORD` 真正生效，REST + WebSocket + 文件下载全链路鉴权；前端新增登录态；空密码时保持开箱即用。
- **新增能力注册表**：以 `capabilities.py` 描述可执行任务（名称/说明/关键词/参数/执行器），协调员据表路由；有本地模型时用 LLM 选能力，无模型时关键词打分兜底。新增能力不再改路由代码。
- **UI 完善**：进度历史面板、文件在线预览、消息搜索与分页加载。
- **文档**：更新 README；新建《项目修改记录文档.md》并按规范登记条目。

## Impact
- Affected specs: 消息总线与双视图、进度系统、分层记忆（保持向后兼容，不改数据模型语义）
- Affected code:
  - 新增 `backend/auth.py`、`backend/importer.py`、`backend/capabilities.py`
  - 修改 `backend/config.py`、`backend/projects.py`、`backend/main.py`、`backend/agents/workbuddy.py`、`backend/agents/coordinator.py`
  - 修改 `frontend/api.py`、`frontend/ws_client.py`、`frontend/app.py`、`frontend/ui.py`
  - 修改 `README.md`；新增 `项目修改记录文档.md`、`samples/` 示例导出文件

## ADDED Requirements

### Requirement: 本地导出文件导入
系统 SHALL 支持把本地导出的聊天记录文件导入到指定项目，并从导入数据生成后续产物。

#### Scenario: 导入 CSV
- **WHEN** 用户上传列含 `contact,company,role,text,time` 的 CSV
- **THEN** 系统解析为统一记录，同一 `contact` 的多行合并为一个会话，并在内部群上报导入进度与总会话数

#### Scenario: 导入 JSON
- **WHEN** 用户导入 `{"records":[...]}` 或顶层数组形式的 JSON
- **THEN** 系统归一化为统一记录结构；字段缺失时使用安全默认值而非报错中断

#### Scenario: 导入 TXT
- **WHEN** 用户导入按会话分节（如 `联系人: 张三`）的纯文本导出
- **THEN** 系统按分节切分并解析出会话与消息

#### Scenario: 无可用导入数据
- **WHEN** 执行客户意向摘要但该项目 `imports/` 下无匹配日期的数据
- **THEN** 任务以 `failed` 结束并给出明确提示（如"请先导入 20261012 的聊天记录"），**不得生成随机数据**

### Requirement: 访问认证
系统 SHALL 在 `WORKBENCH_PASSWORD` 非空时，对所有业务接口与 WebSocket 连接强制令牌校验。

#### Scenario: 未携带令牌
- **WHEN** 未设置 `X-Auth-Token` 请求受保护接口
- **THEN** 返回 401，且不泄露任何业务数据

#### Scenario: 令牌正确
- **WHEN** 请求头 `X-Auth-Token` 与配置密码一致
- **THEN** 正常返回数据；常量时间比较避免时序攻击

#### Scenario: 文件下载鉴权
- **WHEN** 通过 `<a>` 直链下载文件（无法自定义请求头）
- **THEN** 支持 `?token=` 查询参数校验；令牌错误返回 401

#### Scenario: 未设置密码
- **WHEN** `WORKBENCH_PASSWORD` 为空
- **THEN** 不校验任何请求，前端不显示登录界面，`/api/config` 返回 `auth_required=false`

### Requirement: 能力注册表与路由
系统 SHALL 通过能力注册表描述可执行任务，协调员据此选择能力并执行，新增能力无需修改路由代码。

#### Scenario: 配置了本地模型
- **WHEN** 协调员收到需求且本地模型可用
- **THEN** 由模型输出 `{"capability": "...", "args": {...}}`，据此派发对应 Agent

#### Scenario: 未配置本地模型
- **WHEN** 无本地模型
- **THEN** 按关键词/说明打分选择能力；有命中则执行，无命中回退通用对话

#### Scenario: 无匹配能力
- **WHEN** 需求无法匹配任何已注册能力
- **THEN** 协调员列出当前可用能力清单，引导用户重述

#### Scenario: 扩展新能力
- **WHEN** 开发者新增一个能力实现
- **THEN** 仅需在注册表登记，无需改动 `coordinator.py` 的路由逻辑

### Requirement: 进度历史面板
系统 SHALL 在前端展示项目最近任务的进度历史（状态、耗时、错误、时间）。

#### Scenario: 查看历史
- **WHEN** 用户展开进度历史面板
- **THEN** 展示最近 N 条任务记录，失败任务高亮并可查看错误原因

### Requirement: 文件在线预览
系统 SHALL 支持在页面内预览项目文件，文本/Markdown 渲染内容，图片直接显示。

#### Scenario: 预览文本
- **WHEN** 用户点击文本或 Markdown 文件
- **THEN** 页面内展示内容，无需下载

#### Scenario: 预览图片
- **WHEN** 用户点击图片文件
- **THEN** 页面内直接渲染图片

### Requirement: 消息搜索与分页
系统 SHALL 支持按关键字过滤当前视图消息，并支持加载更早历史。

#### Scenario: 搜索
- **WHEN** 用户输入关键字
- **THEN** 仅展示内容命中的消息（进度消息按任务名/步骤匹配）

#### Scenario: 加载更早
- **WHEN** 用户点击"加载更早"
- **THEN** 通过 `before` 参数拉取更早的消息并追加，避免一次性加载全部历史

### Requirement: 示例数据与文档
系统 SHALL 提供可直接试跑的示例导出文件，并在文档中说明导入格式、认证与能力扩展方式。

#### Scenario: 载入示例
- **WHEN** 新项目无任何导入数据且用户点击"载入示例数据"
- **THEN** 把 `samples/` 中的示例导出文件写入该项目 `imports/`，随后可完整跑通摘要流程

## MODIFIED Requirements

### Requirement: Workbuddy 拉取聊天记录
原行为：未配置 `WORKBUDDY_URL` 时随机生成 110~140 条虚构记录。
新行为：优先使用 `WORKBUDDY_URL` 真实接口；否则读取该项目 `imports/` 下匹配日期的导入数据；均无则任务失败并给出可操作提示。进度上报与文件产物（`chat_<date>.json`）保持不变。

### Requirement: 协调员意图识别
原行为：`_detect()` 硬编码两组关键词，命中即走对应流水线。
新行为：改为查询能力注册表路由，`chat_summary` 与 `file_ops` 作为两个已注册能力保留原有行为，新增能力通过注册扩展。

### Requirement: 前端后端访问
原行为：`api.py` / `ws_client.py` 裸调用后端。
新行为：统一携带鉴权令牌（请求头 / WebSocket 查询参数 / 文件直链查询参数），未认证时先展示登录界面。

## REMOVED Requirements

### Requirement: 随机聊天记录生成
**Reason**: 假数据使核心产物不可信，违背"真正可用"目标。
**Migration**: 改为导入本地真实导出文件；需要快速试跑时使用"载入示例数据"（写入 `samples/` 中的真实示例文件，非运行时随机生成）。