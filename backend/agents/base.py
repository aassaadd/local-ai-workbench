"""Agent 基类与消息发射辅助函数。"""
from pathlib import Path

from ..bus import emit
from ..models import Message, TEXT, FILE, VIS_ALL


async def say(project: str, agent: str, content: str, visibility: str = VIS_ALL) -> Message:
    return await emit(Message(
        project=project, from_agent=agent, msg_type=TEXT,
        content=content, visibility=visibility,
    ))


async def send_file(project: str, agent: str, path: Path, scope: str = "public",
                    visibility: str = VIS_ALL, content: str = "") -> Message:
    size = path.stat().st_size if path.exists() else 0
    return await emit(Message(
        project=project, from_agent=agent, msg_type=FILE,
        file_name=path.name, file_scope=scope, file_size=size,
        content=content, visibility=visibility,
    ))


class BaseAgent:
    name: str = "agent"
    display: str = "Agent"

    def __init__(self, project: str):
        self.project = project
