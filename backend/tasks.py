"""任务注册表：活跃任务进度表 + 取消标记。"""
import threading
from typing import Dict

from .models import Message, FINAL_STATES


class TaskRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cancelled: set = set()
        # task_id -> 最新 ProgressMessage，用于前端重连时同步
        self.active_tasks: Dict[str, Message] = {}

    # ---- 取消 ----
    def cancel(self, task_id: str) -> None:
        with self._lock:
            self._cancelled.add(task_id)

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def clear_cancel(self, task_id: str) -> None:
        with self._lock:
            self._cancelled.discard(task_id)

    # ---- 活跃任务表 ----
    def update(self, msg: Message) -> None:
        with self._lock:
            if msg.status in FINAL_STATES:
                self.active_tasks.pop(msg.task_id, None)
            else:
                self.active_tasks[msg.task_id] = msg

    def snapshot(self, project: str = None) -> list:
        with self._lock:
            vals = list(self.active_tasks.values())
        if project:
            vals = [m for m in vals if m.project == project]
        return [m.dump() for m in vals]


registry = TaskRegistry()
