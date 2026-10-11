"""FastAPI 应用：REST + WebSocket 多房间消息总线。"""
import asyncio
import mimetypes
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, db, memory, projects
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
    }


# ---------------- 项目 ----------------
@app.get("/api/projects")
async def api_list_projects():
    return projects.list_projects()


@app.post("/api/projects")
async def api_create_project(body: ProjectIn):
    try:
        return projects.create_project(body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/projects/{project}/archive")
async def api_archive_project(project: str):
    try:
        projects.archive_project(project)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------- 消息 ----------------
@app.get("/api/projects/{project}/messages")
async def api_get_messages(
    project: str,
    view: str = Query("group", pattern="^(group|private)$"),
    limit: int = 100,
    before: float | None = None,
):
    visibility = "private" if view == "private" else None
    return db.get_messages(project, visibility=visibility, limit=limit, before=before)


@app.post("/api/projects/{project}/messages")
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
@app.get("/api/projects/{project}/tasks")
async def api_active_tasks(project: str):
    return registry.snapshot(project)


@app.get("/api/projects/{project}/progress-history")
async def api_progress_history(project: str, limit: int = 50):
    return db.get_progress_history(project, limit)


@app.get("/api/projects/{project}/memory")
async def api_memory(project: str):
    """协调员记忆：长期项目档案 + 滚动摘要 + 上次上下文装配统计。"""
    return memory.get_state(project)


@app.put("/api/projects/{project}/memory")
async def api_update_memory(project: str, body: ProfileIn):
    """人工编辑长期项目档案。"""
    return memory.update_profile_manual(project, body.model_dump())


@app.post("/api/projects/{project}/memory/clear")
async def api_clear_memory(project: str):
    """清空长期记忆（档案 + 摘要）。"""
    memory.clear(project)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel")
async def api_cancel_task(task_id: str):
    registry.cancel(task_id)
    return {"ok": True}


# ---------------- 文件 ----------------
@app.get("/api/projects/{project}/files")
async def api_list_files(project: str, scope: str = "public"):
    return projects.list_files(project, scope)


@app.get("/api/projects/{project}/files/{filename}")
async def api_download_file(project: str, filename: str,
                            scope: str = "public", download: int = 0):
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


# ---------------- WebSocket ----------------
@app.websocket("/ws/{project}")
async def ws_endpoint(ws: WebSocket, project: str):
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
