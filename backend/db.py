"""SQLite 持久化：消息历史（群聊全量）+ 私聊历史（visibility=all 过滤）+ 进度历史。

采用单表 + visibility 字段实现「双历史库」语义：
  - 群聊历史 = 项目下所有消息
  - 私聊历史 = 项目中 visibility == 'all' 的消息
避免维护两套表带来的写入不一致，查询侧用 visibility 过滤即可。
"""
import json
import sqlite3
import threading
from typing import List, Optional

from . import config
from .models import Message

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def init() -> None:
    global _conn
    config.ensure_dirs()
    _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT UNIQUE,
                project TEXT,
                from_agent TEXT,
                msg_type TEXT,
                timestamp REAL,
                visibility TEXT,
                payload TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_project_ts ON messages(project, timestamp);
            CREATE INDEX IF NOT EXISTS idx_msg_project_vis ON messages(project, visibility, timestamp);

            CREATE TABLE IF NOT EXISTS progress_history (
                task_id TEXT PRIMARY KEY,
                project TEXT,
                task_name TEXT,
                from_agent TEXT,
                status TEXT,
                percent REAL,
                step TEXT,
                error_msg TEXT,
                started_at REAL,
                updated_at REAL,
                finished_at REAL,
                elapsed REAL,
                payload TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_prog_project ON progress_history(project, updated_at);

            CREATE TABLE IF NOT EXISTS memory (
                project TEXT PRIMARY KEY,
                summary TEXT,
                compressed_upto REAL,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS project_profile (
                project TEXT PRIMARY KEY,
                data TEXT,
                updated_at REAL
            );
            """
        )
        _conn.commit()


def _conn_or_init() -> sqlite3.Connection:
    if _conn is None:
        init()
    return _conn


def save_message(msg: Message) -> None:
    """保存消息到对应项目历史（群聊历史保存全量）。"""
    c = _conn_or_init()
    with _lock:
        c.execute(
            "INSERT OR REPLACE INTO messages"
            " (msg_id, project, from_agent, msg_type, timestamp, visibility, payload)"
            " VALUES (?,?,?,?,?,?,?)",
            (msg.msg_id, msg.project, msg.from_agent, msg.msg_type,
             msg.timestamp, msg.visibility, json.dumps(msg.dump(), ensure_ascii=False)),
        )
        c.commit()


def get_messages(project: str, visibility: Optional[str] = None,
                 limit: int = 100, before: Optional[float] = None) -> List[dict]:
    """按时间正序返回最近 limit 条；progress 消息按 task_id 只保留最新一条。"""
    c = _conn_or_init()
    sql = "SELECT payload FROM messages WHERE project=?"
    args: list = [project]
    if visibility == "private":
        sql += " AND visibility='all'"
    if before is not None:
        sql += " AND timestamp < ?"
        args.append(before)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    args.append(limit)
    with _lock:
        rows = c.execute(sql, args).fetchall()
    msgs = [json.loads(r["payload"]) for r in rows]
    msgs.reverse()

    # progress 去重：同一 task_id 只保留最后（最新）一条
    seen: dict = {}
    deduped: List[dict] = []
    for m in msgs:
        if m.get("msg_type") == "progress" and m.get("task_id"):
            tid = m["task_id"]
            if tid in seen:
                deduped[seen[tid]] = m
                continue
            seen[tid] = len(deduped)
        deduped.append(m)
    return deduped


def upsert_progress(msg: Message) -> None:
    """写入/更新进度历史（关键节点可回溯）。"""
    c = _conn_or_init()
    from .models import FINAL_STATES
    now = msg.timestamp
    finished = now if msg.status in FINAL_STATES else None
    with _lock:
        row = c.execute(
            "SELECT started_at, finished_at FROM progress_history WHERE task_id=?",
            (msg.task_id,),
        ).fetchone()
        started_at = row["started_at"] if row else now
        finished_at = finished or (row["finished_at"] if row else None)
        elapsed = msg.elapsed or (finished_at - started_at if finished_at else 0.0)
        c.execute(
            "INSERT OR REPLACE INTO progress_history"
            " (task_id, project, task_name, from_agent, status, percent, step,"
            "  error_msg, started_at, updated_at, finished_at, elapsed, payload)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (msg.task_id, msg.project, msg.task_name, msg.from_agent, msg.status,
             msg.percent, msg.step, msg.error_msg, started_at, now, finished_at,
             elapsed, json.dumps(msg.dump(), ensure_ascii=False)),
        )
        c.commit()


def get_progress_history(project: str, limit: int = 50) -> List[dict]:
    c = _conn_or_init()
    with _lock:
        rows = c.execute(
            "SELECT payload, started_at, finished_at, elapsed FROM progress_history"
            " WHERE project=? ORDER BY updated_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


# ---------------- 对话记忆 ----------------
def get_memory(project: str) -> dict:
    c = _conn_or_init()
    with _lock:
        row = c.execute(
            "SELECT summary, compressed_upto, updated_at FROM memory WHERE project=?",
            (project,),
        ).fetchone()
    if not row:
        return {"summary": "", "compressed_upto": 0.0, "updated_at": 0.0}
    return {"summary": row["summary"] or "", "compressed_upto": row["compressed_upto"] or 0.0,
            "updated_at": row["updated_at"] or 0.0}


def save_memory(project: str, summary: str, compressed_upto: float) -> None:
    import time as _t
    c = _conn_or_init()
    with _lock:
        c.execute(
            "INSERT INTO memory (project, summary, compressed_upto, updated_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(project) DO UPDATE SET summary=excluded.summary,"
            " compressed_upto=excluded.compressed_upto, updated_at=excluded.updated_at",
            (project, summary, compressed_upto, _t.time()),
        )
        c.commit()


def get_chat_turns(project: str, limit: int = 1000) -> List[dict]:
    """返回协调员私聊的对话轮次（user / coordinator 的文本消息），按时间正序。"""
    c = _conn_or_init()
    with _lock:
        rows = c.execute(
            "SELECT payload FROM messages"
            " WHERE project=? AND visibility='all' AND msg_type='text'"
            " ORDER BY timestamp ASC LIMIT ?",
            (project, limit),
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


# ---------------- 项目档案（长期事实） ----------------
def get_profile(project: str) -> dict:
    import time as _t
    c = _conn_or_init()
    with _lock:
        row = c.execute(
            "SELECT data, updated_at FROM project_profile WHERE project=?",
            (project,),
        ).fetchone()
    if not row:
        return {"data": {}, "updated_at": 0.0}
    try:
        data = json.loads(row["data"]) if row["data"] else {}
    except json.JSONDecodeError:
        data = {}
    return {"data": data, "updated_at": row["updated_at"] or 0.0}


def save_profile(project: str, data: dict) -> None:
    import time as _t
    c = _conn_or_init()
    with _lock:
        c.execute(
            "INSERT INTO project_profile (project, data, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(project) DO UPDATE SET data=excluded.data,"
            " updated_at=excluded.updated_at",
            (project, json.dumps(data, ensure_ascii=False), _t.time()),
        )
        c.commit()


def clear_memory(project: str) -> None:
    """清空某项目的长期记忆（摘要 + 档案）。"""
    c = _conn_or_init()
    with _lock:
        c.execute("DELETE FROM memory WHERE project=?", (project,))
        c.execute("DELETE FROM project_profile WHERE project=?", (project,))
        c.commit()
