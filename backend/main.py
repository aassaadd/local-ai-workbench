"""FastAPI 应用：REST + WebSocket 多房间消息总线。"""
import asyncio
import mimetypes
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    Depends, FastAPI, File, HTTPException, Query, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import auth, config, db, importer, memory, projects
from .agents.coordinator import dispatch_user_message
from .bus import emit, manager
from .models import Message, TEXT, VIS_ALL
from .tasks import registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init()
    if not projects.list_projects():
        projects.create_project("默认项目")
    yield


app = FastAPI(title="本地 AI 协作工作台", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


class ProjectIn(BaseModel):
    name: str


class MessageIn(BaseModel):
    content: str


class ProfileIn(BaseModel):
    goal: str = ""
    facts: str | list[str] = []
    todos: str | list[str] = []
    prefs: str | list[str] = []


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/config")
async def get_config():
    return {
        "api_base": config.API_BASE,
        "progress_throttle_ms": config.PROGRESS_THROTTLE_MS,
        "agents": config.AGENT_META,
        "llm_configured": bool(config.OMLX_BASE_URL),
        "context_max_tokens": config.CONTEXT_MAX_TOKENS,
        "context_keep_turns": config.CONTEXT_KEEP_TURNS,
        "auth_required": config.AUTH_REQUIRED,
    }


# ---------------- 项目 ----------------
@app.get("/api/projects", dependencies=[Depends(auth.require_auth)])
async def api_list_projects():
    return projects.list_projects()


@app.post("/api/projects", dependencies=[Depends(auth.require_auth)])
async def api_create_project(body: ProjectIn):
    try:
        return projects.create_project(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project}/archive", dependencies=[Depends(auth.require_auth)])
async def api_archive_project(project: str):
    try:
        projects.archive_project(project)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------- 消息 ----------------
@app.get("/api/projects/{project}/messages", dependencies=[Depends(auth.require_auth)])
async def api_get_messages(
    project: str,
    view: str = Query("group", pattern="^(group|private)$"),
    limit: int = 100,
    before: float | None = None,
):
    visibility = "private" if view == "private" else None
    return db.get_messages(project, visibility=visibility, limit=limit, before=before)


@app.post("/api/projects/{project}/messages", dependencies=[Depends(auth.require_auth)])
async def api_send_message(project: str, body: MessageIn):
    text = (body.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    projects.ensure_project(project)
    user_msg = Message(project=project, from_agent="user", msg_type=TEXT,
                       content=text, visibility=VIS_ALL)
    await emit(user_msg)
    # 交给协调员异步处理，HTTP 立即返回
    asyncio.create_task(dispatch_user_message(project, text))
    return user_msg.dump()


# ---------------- 活跃任务 / 进度历史 ----------------
@app.get("/api/projects/{project}/tasks", dependencies=[Depends(auth.require_auth)])
async def api_active_tasks(project: str):
    return registry.snapshot(project)


@app.get("/api/projects/{project}/progress-history", dependencies=[Depends(auth.require_auth)])
async def api_progress_history(project: str, limit: int = 50):
    return db.get_progress_history(project, limit)


@app.get("/api/projects/{project}/memory", dependencies=[Depends(auth.require_auth)])
async def api_memory(project: str):
    """协调员记忆：长期项目档案 + 滚动摘要 + 上次上下文装配统计。"""
    return memory.get_state(project)


@app.put("/api/projects/{project}/memory", dependencies=[Depends(auth.require_auth)])
async def api_update_memory(project: str, body: ProfileIn):
    """人工编辑长期项目档案。"""
    return memory.update_profile_manual(project, body.model_dump())


@app.post("/api/projects/{project}/memory/clear", dependencies=[Depends(auth.require_auth)])
async def api_clear_memory(project: str):
    """清空长期记忆（档案 + 摘要）。"""
    memory.clear(project)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel", dependencies=[Depends(auth.require_auth)])
async def api_cancel_task(task_id: str):
    registry.cancel(task_id)
    return {"ok": True}


# ---------------- 文件 ----------------
@app.get("/api/projects/{project}/files", dependencies=[Depends(auth.require_auth)])
async def api_list_files(project: str, scope: str = "public"):
    return projects.list_files(project, scope)


@app.get("/api/projects/{project}/files/{filename}", dependencies=[Depends(auth.require_auth)])
async def api_download_file(project: str, filename: str,
                            scope: str = "public", download: int = 0,
                            token: str | None = Query(default=None)):
    """下载/预览项目文件。

    功能：`<a>` 直链无法自定义请求头，故支持 `?token=` 查询参数鉴权
          （由 require_auth 依赖统一校验，令牌错误返回 401）。
    参数：token —— 查询参数令牌（可选）。
    返回值：文件响应。
    """
    try:
        path = projects.safe_file_path(project, scope, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if download:
        disposition = f"attachment; filename*=UTF-8''{quote(path.name)}"
    else:
        disposition = "inline"
    return FileResponse(path, media_type=media, headers={"Content-Disposition": disposition})


# ---------------- 导入文件 ----------------
@app.get("/api/projects/{project}/imports", dependencies=[Depends(auth.require_auth)])
async def api_list_imports(project: str):
    """列出项目 imports/ 下的导入文件及解析出的会话数。

    功能：读取每个导入文件的会话数（解析失败计 0）。
    参数：project —— 项目名。
    返回值：列表，元素为 {"name","size","mtime","records"}。
    """
    projects.ensure_project(project)
    d = projects.imports_dir(project)
    out = []
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        st = f.stat()
        try:
            records = len(importer.parse_bytes(f.name, f.read_bytes()))
        except Exception:
            records = 0
        out.append({"name": f.name, "size": st.st_size,
                    "mtime": st.st_mtime, "records": records})
    return out


@app.post("/api/projects/{project}/imports", dependencies=[Depends(auth.require_auth)])
async def api_upload_import(project: str, file: UploadFile = File(...)):
    """上传本地导出文件到项目 imports/（同名覆盖）。

    功能：先解析校验，成功后再落盘；解析失败返回 400 并带原因。
    参数：project —— 项目名；file —— 上传的 CSV/JSON/TXT 文件。
    返回值：{"name","records"}；解析失败抛 HTTPException(400)。
    """
    projects.ensure_project(project)
    name = Path(file.filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="缺少文件名")
    data = await file.read()
    try:
        records = importer.parse_bytes(name, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"解析失败：{e}")
    (projects.imports_dir(project) / name).write_bytes(data)
    return {"name": name, "records": len(records)}


@app.post("/api/projects/{project}/imports/sample", dependencies=[Depends(auth.require_auth)])
async def api_load_sample(project: str):
    """把仓库根目录 samples/ 下的示例文件复制到项目 imports/。

    功能：供新项目快速试跑；samples/ 不存在时返回 400。
    参数：project —— 项目名。
    返回值：{"files": [文件名...]}。
    """
    projects.ensure_project(project)
    src = config.BASE_DIR / "samples"
    if not src.exists() or not src.is_dir():
        raise HTTPException(status_code=400, detail="samples/ 目录不存在")
    dst = projects.imports_dir(project)
    files = []
    for f in sorted(src.iterdir()):
        if f.is_file():
            shutil.copy2(f, dst / f.name)
            files.append(f.name)
    return {"files": files}


# ---------------- WebSocket ----------------
@app.websocket("/ws/{project}")
async def ws_endpoint(ws: WebSocket, project: str, token: str | None = Query(default=None)):
    # 先校验令牌再握手：错误令牌直接以 1008 关闭，前端无法建立连接
    if not auth.ws_token_ok(token):
        await ws.close(code=1008)
        return
    await manager.connect(project, ws)
    try:
        # 首帧同步当前活跃任务，供前端重连对齐
        for task in registry.snapshot(project):
            await ws.send_json(task)
        while True:
            # 前端仅保持心跳，收到的内容忽略
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(project, ws)
    except Exception:
        await manager.disconnect(project, ws)
