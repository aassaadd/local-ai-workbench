"""统一的进度上报工具类。

所有 Agent 只需调用 update/finish/fail，不必关心底层 WebSocket 与落库。
默认按 PROGRESS_THROTTLE_MS 节流（默认 500ms），任务完成/失败/取消时强制上报。
"""
import asyncio
import time
from typing import Optional

from . import config
from .bus import emit
from .models import (
    Message, PROGRESS, VIS_INTERNAL, PENDING, RUNNING, SUCCESS, FAILED, CANCELLED,
    new_id,
)
from .tasks import registry


class TaskCancelled(Exception):
    """Agent 在循环中检测到取消时抛出，交由协调员统一收尾。"""


class ProgressReporter:
    def __init__(self, project: str, agent_name: str, task_id: str,
                 task_name: str, total: int = 100, visibility: str = VIS_INTERNAL,
                 phase: str = ""):
        self.project = project
        self.agent = agent_name
        self.task_id = task_id or new_id("task")
        self.task_name = task_name
        self.total = max(total, 1)
        self.current = 0
        self.visibility = visibility
        self.phase = phase
        self._start = time.time()
        self._last_emit = 0.0
        self._throttle = config.PROGRESS_THROTTLE_MS / 1000.0

    # ---- 取消检测：Agent 在循环中调用，命中则上报 cancelled 并中断 ----
    async def guard(self) -> None:
        if registry.is_cancelled(self.task_id):
            await self.cancel()
            raise TaskCancelled(self.task_id)

    @property
    def elapsed(self) -> float:
        return round(time.time() - self._start, 2)

    def _build(self, status: str, step: str = "", error_msg: str = "",
               force_percent: Optional[float] = None) -> Message:
        percent = force_percent if force_percent is not None else \
            round(self.current / self.total * 100, 1)
        return Message(
            msg_id=f"prog_{self.task_id}_{int(time.time() * 1000)}",
            project=self.project,
            from_agent=self.agent,
            msg_type=PROGRESS,
            visibility=self.visibility,
            task_id=self.task_id,
            task_name=self.task_name,
            current=self.current,
            total=self.total,
            percent=percent,
            status=status,
            step=step,
            phase=self.phase,
            error_msg=error_msg,
            elapsed=self.elapsed,
        )

    async def emit_pending(self, step: str = "任务已派发，等待执行") -> None:
        await emit(self._build(PENDING, step, force_percent=0.0))

    async def update(self, current: Optional[int] = None, step: str = "",
                     phase: Optional[str] = None, force: bool = False) -> None:
        if current is not None:
            self.current = max(0, min(current, self.total))
        if phase is not None:
            self.phase = phase
        now = time.time()
        if not force and (now - self._last_emit) < self._throttle:
            return
        self._last_emit = now
        await emit(self._build(RUNNING, step))

    async def set_total(self, total: int, step: str = "") -> None:
        self.total = max(int(total), 1)
        await self.update(self.current, step or f"共 {self.total} 条待处理", force=True)

    async def finish(self, step: str = "任务完成") -> None:
        self.current = self.total
        await emit(self._build(SUCCESS, step, force_percent=100.0))
        registry.clear_cancel(self.task_id)

    async def fail(self, error_msg: str) -> None:
        await emit(self._build(FAILED, "执行失败", error_msg=error_msg))

    async def cancel(self, step: str = "任务已取消") -> None:
        await emit(self._build(CANCELLED, step))
        registry.clear_cancel(self.task_id)
