"""后端 REST 客户端。

统一携带鉴权令牌（请求头 X-Auth-Token）；令牌由上层（app.py 登录门）通过
set_token 注入，模块级保存，令牌为空表示后端未启用认证。
"""
from typing import List, Optional
from urllib.parse import quote

import requests

from backend import config

BASE = config.API_BASE
TIMEOUT = 5
# 文件预览读取超时（大文件给多点时间）
FILE_TIMEOUT = 10

# 模块级鉴权令牌：None 或空串表示不鉴权
_token: Optional[str] = None


def set_token(token: Optional[str]) -> None:
    """设置全局鉴权令牌。

    参数：
        token: 访问密码，None 或空串表示不鉴权。
    返回值：无。
    """
    global _token
    _token = token or None


def get_token() -> Optional[str]:
    """获取当前全局鉴权令牌。

    参数：无。
    返回值：令牌字符串；未设置时返回 None。
    """
    return _token


def _headers() -> dict:
    """构造请求头。

    参数：无。
    返回值：令牌非空时返回 {"X-Auth-Token": token}，否则返回空字典。
    """
    token = get_token()
    return {"X-Auth-Token": token} if token else {}


def get_config() -> dict:
    """获取后端配置（该接口不需要令牌）。

    参数：无。
    返回值：配置字典；请求失败时返回兜底默认值。
    """
    try:
        return requests.get(f"{BASE}/api/config", headers=_headers(),
                            timeout=TIMEOUT).json()
    except Exception:
        return {"api_base": BASE, "agents": {}, "progress_throttle_ms": 500}


def verify_auth() -> bool:
    """校验当前令牌是否被后端接受（请求受保护的 /api/projects）。

    用于登录门判断密码是否正确，与 list_projects 不同，这里不会吞掉 401。
    参数：无。
    返回值：状态码 2xx 返回 True；401 或异常返回 False。
    """
    try:
        return requests.get(f"{BASE}/api/projects", headers=_headers(),
                            timeout=TIMEOUT).ok
    except Exception:
        return False


def health() -> bool:
    """探测后端是否在线。

    参数：无。
    返回值：在线返回 True，否则 False。
    """
    try:
        return requests.get(f"{BASE}/health", headers=_headers(), timeout=2).ok
    except Exception:
        return False


def list_projects() -> List[dict]:
    """获取项目列表。

    参数：无。
    返回值：项目字典列表；请求失败时返回空列表。
    """
    try:
        return requests.get(f"{BASE}/api/projects", headers=_headers(),
                            timeout=TIMEOUT).json()
    except Exception:
        return []


def create_project(name: str) -> dict:
    """创建项目。

    参数：
        name: 项目名称。
    返回值：新项目字典。
    """
    r = requests.post(f"{BASE}/api/projects", json={"name": name},
                      headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_messages(project: str, view: str = "group", limit: int = 200,
                 before: Optional[float] = None) -> List[dict]:
    """获取项目消息（按时间正序）。

    参数：
        project: 项目名称。
        view: 视图类型，group=群聊全量，private=私聊（仅 all 可见性）。
        limit: 拉取条数上限。
        before: 仅返回时间戳早于该值的消息，用于分页加载更早历史。
    返回值：消息字典列表；请求失败时返回空列表。
    """
    params = {"view": view, "limit": limit}
    if before is not None:
        params["before"] = before
    try:
        r = requests.get(f"{BASE}/api/projects/{quote(project)}/messages",
                         params=params, headers=_headers(), timeout=TIMEOUT)
        return r.json()
    except Exception:
        return []


def active_tasks(project: str) -> List[dict]:
    """获取项目进行中的任务进度快照。

    参数：
        project: 项目名称。
    返回值：进度消息列表；请求失败时返回空列表。
    """
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/tasks",
                            headers=_headers(), timeout=TIMEOUT).json()
    except Exception:
        return []


def progress_history(project: str, limit: int = 50) -> List[dict]:
    """获取项目进度历史（最近 N 条任务记录）。

    参数：
        project: 项目名称。
        limit: 拉取条数上限。
    返回值：进度记录列表；请求失败时返回空列表。
    """
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/progress-history",
                            params={"limit": limit}, headers=_headers(),
                            timeout=TIMEOUT).json()
    except Exception:
        return []


def list_imports(project: str) -> List[dict]:
    """获取项目已导入的聊天记录文件列表。

    参数：
        project: 项目名称。
    返回值：[{"name","size","mtime","records"}]；请求失败时返回空列表。
    """
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/imports",
                            headers=_headers(), timeout=TIMEOUT).json()
    except Exception:
        return []


def upload_import(project: str, filename: str, data: bytes) -> dict:
    """上传并导入聊天记录文件（multipart，字段名 file）。

    参数：
        project: 项目名称。
        filename: 上传文件名。
        data: 文件二进制内容。
    返回值：{"name","records"}。失败时抛出 HTTPError，调用方可从
            exc.response.json()["detail"] 读取后端 400 错误详情。
    """
    r = requests.post(f"{BASE}/api/projects/{quote(project)}/imports",
                      files={"file": (filename, data)}, headers=_headers(),
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def load_sample(project: str) -> dict:
    """把仓库 samples/ 下的示例导出文件复制进该项目 imports。

    参数：
        project: 项目名称。
    返回值：{"files":[...]}。失败时抛出 HTTPError。
    """
    r = requests.post(f"{BASE}/api/projects/{quote(project)}/imports/sample",
                      headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_file_text(project: str, name: str, scope: str = "public",
                    max_bytes: int = 200000) -> Optional[str]:
    """读取项目文件文本内容，用于在线预览。

    参数：
        project: 项目名称。
        name: 文件名。
        scope: 目录范围，public 或 private。
        max_bytes: 最大读取字节数，超出部分截断。
    返回值：文件文本内容（超长已截断）；请求失败返回 None。
    """
    url = file_url(project, name, scope, download=0)
    try:
        r = requests.get(url, headers=_headers(), timeout=FILE_TIMEOUT)
        if not r.ok:
            return None
        raw = r.content[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
        if len(r.content) > max_bytes:
            text += "\n\n……（内容过长，已截断）"
        return text
    except Exception:
        return None


def get_memory(project: str) -> dict:
    """获取协调员记忆（长期档案 + 滚动摘要 + 装配统计）。

    参数：
        project: 项目名称。
    返回值：记忆状态字典；请求失败时返回空字典。
    """
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/memory",
                            headers=_headers(), timeout=TIMEOUT).json()
    except Exception:
        return {}


def update_memory(project: str, profile: dict) -> dict:
    """人工更新协调员长期项目档案。

    参数：
        project: 项目名称。
        profile: 档案字典（goal/facts/todos/prefs）。
    返回值：更新后的档案字典。
    """
    r = requests.put(f"{BASE}/api/projects/{quote(project)}/memory",
                     json=profile, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def clear_memory(project: str) -> None:
    """清空项目长期记忆（档案 + 摘要）。

    参数：
        project: 项目名称。
    返回值：无。
    """
    requests.post(f"{BASE}/api/projects/{quote(project)}/memory/clear",
                  headers=_headers(), timeout=TIMEOUT)


def send_message(project: str, content: str) -> Optional[dict]:
    """向协调员发送私聊消息。

    参数：
        project: 项目名称。
        content: 消息文本。
    返回值：已落库的用户消息字典。
    """
    r = requests.post(f"{BASE}/api/projects/{quote(project)}/messages",
                      json={"content": content}, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def cancel_task(task_id: str) -> None:
    """请求取消指定任务。

    参数：
        task_id: 任务 ID。
    返回值：无。
    """
    try:
        requests.post(f"{BASE}/api/tasks/{quote(task_id)}/cancel",
                      headers=_headers(), timeout=TIMEOUT)
    except Exception:
        pass


def list_files(project: str, scope: str = "public") -> List[dict]:
    """列出项目目录下的文件。

    参数：
        project: 项目名称。
        scope: 目录范围，public 或 private。
    返回值：文件信息列表；请求失败时返回空列表。
    """
    try:
        return requests.get(f"{BASE}/api/projects/{quote(project)}/files",
                            params={"scope": scope}, headers=_headers(),
                            timeout=TIMEOUT).json()
    except Exception:
        return []


def file_url(project: str, name: str, scope: str = "public", download: int = 0) -> str:
    """构造文件访问直链（用于 <a> 下载或图片预览）。

    参数：
        project: 项目名称。
        name: 文件名。
        scope: 目录范围，public 或 private。
        download: 1=附件下载，0=inline 预览。
    返回值：完整 URL；令牌非空时自动追加 &token=<urlencode>。
    """
    url = (f"{BASE}/api/projects/{quote(project)}/files/{quote(name)}"
           f"?scope={scope}&download={download}")
    token = get_token()
    if token:
        url += f"&token={quote(token)}"
    return url