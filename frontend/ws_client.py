"""前端 WebSocket 客户端（后台线程）。

在 Streamlit 的脚本执行模型下，用一个后台线程维持长连接，把收到的消息
写入线程安全队列；界面片段每次刷新时从队列取增量，实现毫秒级同步。
连接支持自动重连。
"""
import json
import queue
import threading
import time
from typing import Dict, Optional, Tuple
from urllib.parse import quote

from backend import config

from . import api

# (session_id, project, token) -> WSClient
_clients: Dict[Tuple[str, str, str], "WSClient"] = {}
_lock = threading.Lock()


class WSClient:
    def __init__(self, project: str, token: Optional[str] = None) -> None:
        self.project = project
        # 连接所用令牌；令牌变更后由 get_client 用新 key 建立新连接
        self.token = token or None
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self._stop = False
        self.connected = False
        self._ws = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _url(self) -> str:
        base = config.API_BASE.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{base}/ws/{self.project}"
        if self.token:
            url += f"?token={quote(self.token)}"
        return url

    def _run(self) -> None:
        from websockets.sync.client import connect
        backoff = 0.5
        while not self._stop:
            try:
                with connect(self._url(), open_timeout=5, close_timeout=2) as ws:
                    self._ws = ws
                    self.connected = True
                    backoff = 0.5
                    while not self._stop:
                        try:
                            raw = ws.recv(timeout=1)
                        except TimeoutError:
                            try:
                                ws.send("ping")
                            except Exception:
                                break
                            continue
                        if raw:
                            try:
                                self.queue.put(json.loads(raw))
                            except json.JSONDecodeError:
                                pass
            except Exception:
                self.connected = False
                time.sleep(backoff)
                backoff = min(backoff * 2, 5)
            finally:
                self.connected = False
                self._ws = None

    def drain(self, on_message) -> int:
        n = 0
        while True:
            try:
                msg = self.queue.get_nowait()
            except queue.Empty:
                break
            on_message(msg)
            n += 1
        return n

    def stop(self) -> None:
        self._stop = True
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass


def get_client(session_id: str, project: str) -> WSClient:
    """获取（或创建）指定会话+项目的 WebSocket 客户端。

    缓存 key 包含当前令牌，令牌变更后会新建连接，避免复用旧鉴权连接。
    参数：
        session_id: Streamlit 会话 ID。
        project: 项目名称。
    返回值：对应 WSClient 实例。
    """
    token = api.get_token() or ""
    key = (session_id, project, token)
    with _lock:
        client = _clients.get(key)
        if client is None:
            client = WSClient(project, token)
            client.start()
            _clients[key] = client
        return client


def drop_session(session_id: str) -> None:
    with _lock:
        for key in [k for k in _clients if k[0] == session_id]:
            _clients.pop(key).stop()
