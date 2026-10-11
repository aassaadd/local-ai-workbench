"""后端 REST 客户端。"""
from typing import List, Optional
from urllib.parse import quote

import requests

from backend import config

BASE = config.API_BASE
TIMEOUT = 5


def get_config() -> dict:
    try:
        return requests.get(f"{BASE}/api/config", timeout=TIMEOUT).json()
    except Exception:
        return {"api_base": BASE, "agents": {}, "progress_throttle_ms": 500}


def health() -> bool:
    try:
        return requests.get(f"{BASE}/health", timeout=2).ok
    except Exception:
        return False


def list_projects() -> List[dict]:
    try:
        return requests.get(f"{BASE}/api/projects", timeout=TIMEOUT).json()
    except Exception:
        return []


def create_project(name: str) -> dict:
    r = requests.post(f"{BASE}/api/projects", json={"name": name}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_messages(project: str, view: str = "group", limit: int = 200) -> List[dict]:
    try:
        r = requests.get(f"{BASE}/api/projects/{quote(project)}/messages",
                         params={"view": view, "limit": limit}, timeout=TIMEOUT)
        return r.json()
    except Exception:
        return []


def active_tasks(project: str) -> List[dict]:
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/tasks",
                            timeout=TIMEOUT).json()
    except Exception:
        return []


def get_memory(project: str) -> dict:
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/memory",
                            timeout=TIMEOUT).json()
    except Exception:
        return {}


def update_memory(project: str, profile: dict) -> dict:
    r = requests.put(f"{BASE}/api/projects/{quote(project)}/memory",
                     json=profile, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def clear_memory(project: str) -> None:
    requests.post(f"{BASE}/api/projects/{quote(project)}/memory/clear", timeout=TIMEOUT)


def send_message(project: str, content: str) -> Optional[dict]:
    r = requests.post(f"{BASE}/api/projects/{quote(project)}/messages",
                      json={"content": content}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def cancel_task(task_id: str) -> None:
    try:
        requests.post(f"{BASE}/api/tasks/{quote(task_id)}/cancel", timeout=TIMEOUT)
    except Exception:
        pass


def list_files(project: str, scope: str = "public") -> List[dict]:
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/files",
                            params={"scope": scope}, timeout=TIMEOUT).json()
    except Exception:
        return []


def file_url(project: str, name: str, scope: str = "public", download: int = 0) -> str:
    return (f"{BASE}/api/projects/{quote(project)}/files/{quote(name)}"
            f"?scope={scope}&download={download}")
