"""统一消息结构体。

设计说明：方案文档里把 text/file/progress 拆成多个类，落到工程实现上，
用「单一模型 + 可选字段」更利于 SQLite 存储与前端统一渲染，新增 Agent
无需改前端。progress 消息用 task_id 做幂等键，天然支持原地更新。
"""
import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field

# 消息类型
TEXT = "text"
FILE = "file"
PROGRESS = "progress"

# 可见性：all = 私聊+群聊都可见；internal = 仅内部群聊可见
VIS_ALL = "all"
VIS_INTERNAL = "internal"

# 进度状态
PENDING = "pending"
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
CANCELLED = "cancelled"
FINAL_STATES = {SUCCESS, FAILED, CANCELLED}


def new_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Message(BaseModel):
    msg_id: str = Field(default_factory=lambda: new_id("msg"))
    project: str
    from_agent: str
    msg_type: str = TEXT
    timestamp: float = Field(default_factory=time.time)
    visibility: str = VIS_ALL

    # text / file
    content: str = ""
    file_name: str = ""
    file_scope: str = "public"  # public | private
    file_size: int = 0

    # progress
    task_id: str = ""
    task_name: str = ""
    current: int = 0
    total: int = 0
    percent: float = 0.0
    status: str = ""
    step: str = ""
    phase: str = ""          # 分阶段，如 "1/2 拉取数据"
    error_msg: str = ""
    elapsed: float = 0.0     # 耗时（秒）

    def dump(self) -> dict:
        return self.model_dump()
