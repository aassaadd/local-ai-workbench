"""消息渲染组件：文本 / 文件 / 进度（原地更新）。"""
import html

import streamlit as st

from . import api
from .styles import STATUS_COLOR

STATUS_LABEL = {
    "pending": "等待中",
    "running": "执行中",
    "success": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def progress_html(msg: dict) -> str:
    status = msg.get("status", "running")
    color = STATUS_COLOR.get(status, "#9ca3af")
    pct = float(msg.get("percent", 0) or 0)
    done = status in ("success", "failed", "cancelled")
    step = html.escape(msg.get("step", "") or "")
    phase = html.escape(msg.get("phase", "") or "")
    error = msg.get("error_msg", "") or ""
    elapsed = msg.get("elapsed", 0) or 0

    phase_html = f'<span class="prog-phase">{phase}</span>' if phase else ""
    right = f"{STATUS_LABEL.get(status, status)} · {pct:.0f}%"
    if done and elapsed:
        right += f" · 耗时 {elapsed:.1f}s"
    err_html = (f'<div class="prog-err">⚠️ {html.escape(error)}</div>') if error else ""

    return f"""
    <div class="prog-card {'done' if done else ''}" style="--prog-color:{color}">
      <div class="prog-title">
        <span>📊 {html.escape(msg.get('task_name', '任务'))}</span>
        {phase_html}
      </div>
      <div class="prog-bar"><div class="prog-fill" style="width:{pct:.1f}%"></div></div>
      <div class="prog-meta"><span class="prog-step">{step}</span>
        <span class="prog-pct">{right}</span></div>
      {err_html}
    </div>
    """


def _render_file(msg: dict) -> None:
    name = msg.get("file_name", "")
    scope = msg.get("file_scope", "public")
    url = api.file_url(msg["project"], name, scope, download=1)
    size = fmt_size(int(msg.get("file_size", 0) or 0))
    st.markdown(
        f'<div class="file-card">📎 <a href="{url}" target="_blank">'
        f'{html.escape(name)}</a>'
        f'<span style="color:#999;font-size:12px">{size}</span></div>',
        unsafe_allow_html=True,
    )
    if msg.get("content"):
        st.caption(msg["content"])


def render_message(msg: dict, meta: dict, cancel_cb=None) -> None:
    agent = msg.get("from_agent", "agent")
    info = meta.get(agent, {"name": agent, "avatar": "🤖"})
    with st.chat_message(info["name"], avatar=info["avatar"]):
        mtype = msg.get("msg_type")
        if mtype == "progress":
            st.markdown(progress_html(msg), unsafe_allow_html=True)
            if msg.get("status") == "running" and cancel_cb:
                if st.button("⏹ 取消任务", key=f"cancel_{msg.get('task_id')}"):
                    cancel_cb(msg["task_id"])
        elif mtype == "file":
            _render_file(msg)
        else:
            st.markdown(msg.get("content", ""))
