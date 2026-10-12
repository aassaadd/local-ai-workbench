"""项目目录管理：每个项目自动生成 public/ 与 private/ 子目录。"""
import re
import shutil
from pathlib import Path
from typing import List

from . import config

_NAME_RE = re.compile(r"^[\w\u4e00-\u9fa5\- ]{1,40}$")


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise ValueError("项目名仅支持中英文、数字、下划线、短横线和空格，长度 1-40")
    return name


def project_dir(name: str) -> Path:
    return config.PROJECTS_DIR / name


def imports_dir(name: str) -> Path:
    """返回项目的导入目录（与 public/private 并列的 imports/）。

    功能：定位项目下的 imports/ 子目录，用于存放本地导出的聊天记录文件。
    参数：name —— 项目名。
    返回值：imports 目录的 Path 对象（不保证已存在）。
    """
    return project_dir(name) / "imports"


def create_project(name: str) -> dict:
    name = _safe_name(name)
    root = project_dir(name)
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "private").mkdir(parents=True, exist_ok=True)
    (root / "imports").mkdir(parents=True, exist_ok=True)
    return {"name": name, "path": str(root)}


def list_projects() -> List[dict]:
    config.ensure_dirs()
    out = []
    for p in sorted(config.PROJECTS_DIR.iterdir()):
        if p.is_dir():
            out.append({"name": p.name, "path": str(p)})
    return out


def ensure_project(name: str) -> dict:
    root = project_dir(name)
    if not root.exists():
        return create_project(name)
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "private").mkdir(parents=True, exist_ok=True)
    (root / "imports").mkdir(parents=True, exist_ok=True)
    return {"name": name, "path": str(root)}


def folder(name: str, scope: str) -> Path:
    if scope not in ("public", "private"):
        raise ValueError("scope 必须是 public 或 private")
    ensure_project(name)
    return project_dir(name) / scope


def list_files(name: str, scope: str = "public") -> List[dict]:
    d = folder(name, scope)
    files = []
    for f in sorted(d.iterdir()):
        if f.is_file():
            st = f.stat()
            files.append({
                "name": f.name,
                "scope": scope,
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    return files


def safe_file_path(name: str, scope: str, filename: str) -> Path:
    d = folder(name, scope).resolve()
    target = (d / filename).resolve()
    if d != target.parent:
        raise ValueError("非法文件名")
    return target


def archive_project(name: str) -> None:
    """归档：移动到 data/_archived/。"""
    src = project_dir(name)
    if not src.exists():
        raise ValueError("项目不存在")
    dst_dir = config.DATA_DIR / "_archived"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst_dir / name))
