"""WebSocket 多房间消息总线 + 统一 emit 入口。

emit() 是所有消息的唯一出口：
  1. 落库（群聊历史全量；visibility=all 进私聊历史）
  2. progress 消息额外更新活跃任务表与进度历史
  3. 广播给该项目的所有前端连接
"""
import asyncio
from typing import Dict, Set

from fastapi import WebSocket

from . import db
from .models import Message, PROGRESS
from .tasks import registry


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, project: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(project, set()).add(ws)

    async def disconnect(self, project: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(project)
            if room:
                room.discard(ws)
                if not room:
                    self._rooms.pop(project, None)

    async def broadcast(self, project: str, payload: dict) -> None:
        room = list(self._rooms.get(project, ()))
        dead = []
        for ws in room:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                r = self._rooms.get(project)
                if r:
                    for ws in dead:
                        r.discard(ws)

    async def broadcast_progress(self, project: str, progress: Message) -> None:
        # 更新内存活跃任务表，前端重连时可通过 /tasks 同步
        registry.update(progress)
        await self.broadcast(project, progress.dump())


manager = ConnectionManager()


async def emit(msg: Message) -> Message:
    """统一消息出口：落库 -> 更新活跃任务表 -> 广播。"""
    db.save_message(msg)  # 群聊历史保存全量；私聊历史用 visibility 过滤查询
    if msg.msg_type == PROGRESS:
        db.upsert_progress(msg)
        await manager.broadcast_progress(msg.project, msg)
    else:
        await manager.broadcast(msg.project, msg.dump())
    return msg
