# Tasks

- [x] Task 1: 落地访问认证与安全（后端 + 前端）
  - [x] SubTask 1.1: `config.py` 增加 `AUTH_REQUIRED`（由 `WORKBENCH_PASSWORD` 派生）
  - [x] SubTask 1.2: 新增 `backend/auth.py`：令牌校验依赖（`secrets.compare_digest`）与 WS token 校验工具
  - [x] SubTask 1.3: `main.py` 给业务路由挂鉴权依赖；`/health` 保持开放；`/api/config` 返回 `auth_required`
  - [x] SubTask 1.4: `main.py` 的 `/ws/{project}` 校验 `?token=`；`/files/{filename}` 支持 `?token=`
  - [x] SubTask 1.5: `frontend/api.py` 统一附带 `X-Auth-Token`，文件直链带 `token`
  - [x] SubTask 1.6: `frontend/ws_client.py` 的 WS URL 附带 token
  - [x] SubTask 1.7: `frontend/app.py` 增加登录态（未认证时展示密码输入，成功后写入 `session_state`）
  - [x] 验证: 空密码时可正常访问；设置密码后未带令牌返回 401、带令牌正常、WS 可连、文件可下载

- [x] Task 2: 新增本地导出文件导入能力
  - [x] SubTask 2.1: `projects.py` 增加 `imports/` 目录（`imports_dir()` 并在 `create/ensure_project` 时创建）
  - [x] SubTask 2.2: 新增 `backend/importer.py`：解析 CSV / JSON / TXT → 统一记录结构 `{contact, company, msgs:[{role,text,time}]}`；按 `contact` 合并
  - [x] SubTask 2.3: `main.py` 新增 `POST /api/projects/{project}/imports`（上传，multipart）与 `GET /api/projects/{project}/imports`（列表）
  - [x] SubTask 2.4: `frontend/api.py` 增加 `upload_import` / `list_imports`
  - [x] SubTask 2.5: `frontend/app.py` 侧栏增加"导入聊天记录"上传区与已导入文件列表
  - [x] 验证: 上传 CSV/JSON/TXT 各一份，`imports/` 出现文件且解析记录数正确

- [x] Task 3: Workbuddy 改造为真实数据源（去假数据）
  - [x] SubTask 3.1: `pull_chat_records(date)` 改为读取 `imports/` 中匹配日期的文件（经 `importer` 解析）
  - [x] SubTask 3.2: 无匹配数据时 `reporter.fail("请先导入 <date> 的聊天记录")` 并抛出可被协调员捕获的异常
  - [x] SubTask 3.3: 删除 `_generate_local()` 随机生成逻辑
  - [x] 验证: 有导入数据时产出 `chat_<date>.json`；无数据时任务失败且提示明确，不产生假记录

- [x] Task 4: 通用任务编排（能力注册表 + 路由）
  - [x] SubTask 4.1: 新增 `backend/capabilities.py`：注册 `chat_summary` / `file_ops` / `chat` 三个能力（名称、说明、关键词、参数、执行器）
  - [x] SubTask 4.2: `coordinator.py` 改为查表路由：`llm.available()` 时用 LLM 输出 `{capability,args}`，否则关键词打分
  - [x] SubTask 4.3: 无匹配能力时回复可用能力清单
  - [x] SubTask 4.4: 保持 `chat_summary` / `file_ops` 的原有产物与消息可见性行为不变
  - [x] 验证: 无模型下"生成客户意向摘要""整理文件"仍走原流程；新增一个能力不改 `coordinator.py` 路由即可被提及

- [x] Task 5: UI 体验完善（可并行）
  - [x] SubTask 5.1: 进度历史面板（接入 `/progress-history`，展示状态/耗时/错误，失败高亮）
  - [x] SubTask 5.2: 文件在线预览（文本/Markdown 渲染，图片直接显示）
  - [x] SubTask 5.3: 消息搜索过滤 + "加载更早"分页（`before` 参数）
  - [x] 验证: 面板可展开并显示历史；点击文本/图片文件可在页面内预览；搜索命中正确；分页可加载更早消息

- [x] Task 6: 示例数据与文档
  - [x] SubTask 6.1: 新增 `samples/` 示例导出文件（CSV 与 JSON 各一）
  - [x] SubTask 6.2: `frontend/app.py` 增加"载入示例数据"动作（把 `samples/` 写入项目 `imports/`）
  - [x] SubTask 6.3: 更新 `README.md`：导入格式、认证说明、能力扩展说明
  - [x] SubTask 6.4: 新建《项目修改记录文档.md》并登记本轮条目（状态：开发中 → 完成后改"修改完成"）
  - [x] 验证: 新项目载入示例后可完整跑通摘要流程；文档内容与实现一致

- [x] Task 7: 端到端验证
  - [x] SubTask 7.1: 冒烟脚本或手工流程：启动后端 → 导入示例 → 客户意向摘要 → 文件整理 → 校验产物存在且内容真实
  - [x] SubTask 7.2: 认证回归：设置密码后前端登录、消息、文件下载、WS 全链路可用
  - [x] 验证: 全流程无异常，产物落在 `data/projects/<项目>/public/`

# Task Dependencies
- Task 2 depends on Task 1（上传接口需鉴权就位）
- Task 3 depends on Task 2
- Task 4 depends on Task 3
- Task 6 depends on Task 2（示例数据格式需先定稿）
- Task 7 depends on Task 1 ~ Task 6
- Task 5 与 Task 1~4 无依赖，可并行推进