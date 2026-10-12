"""消息渲染组件：文本 / 文件 / 进度（原地更新）。

另含进度历史条目渲染与文件在线预览渲染两个函数，供 app.py 复用。
"""
import html
from datetime import datetime

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

# 可在线预览的文件扩展名分类
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
TEXT_EXTS = {"txt", "md", "json", "csv", "py", "log"}


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


def render_progress_history_item(item: dict) -> None:
    """渲染单条进度历史（任务名 / 状态 / 百分比 / 耗时 / 时间 / 错误）。

    参数：
        item: 进度记录字典（含 task_name、status、percent、elapsed、
              timestamp、error_msg 等字段）。
    返回值：无。
    """
    status = item.get("status", "success")
    label = STATUS_LABEL.get(status, status)
    color = STATUS_COLOR.get(status, "#9ca3af")
    pct = float(item.get("percent", 0) or 0)
    elapsed = item.get("elapsed", 0) or 0
    ts = item.get("timestamp", 0) or 0
    tstr = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S") if ts else "-"
    name = html.escape(item.get("task_name", "任务") or "任务")

    st.markdown(
        f"<div style='border-left:3px solid {color};padding:4px 8px;"
        f"margin-bottom:6px;background:rgba(128,128,128,0.05);border-radius:6px'>"
        f"<b>{name}</b> <span style='color:{color};font-weight:600'>{label}</span>"
        f"<br><small style='color:#999'>{pct:.0f}% · 耗时 {elapsed:.1f}s · {tstr}</small>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if item.get("error_msg"):
        st.error(item["error_msg"])


def render_preview(project: str, scope: str, name: str) -> None:
    """在线预览项目文件：图片直接显示，文本类渲染内容，其余提示下载。

    参数：
        project: 项目名称。
        scope: 目录范围（public / private）。
        name: 文件名。
    返回值：无。
    """
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_EXTS:
        # 图片直接用直链交给浏览器渲染（inline）
        st.image(api.file_url(project, name, scope, download=0))
    elif ext in TEXT_EXTS:
        text = api.fetch_file_text(project, name, scope)
        if text is None:
            st.warning("读取失败，请下载查看")
        elif ext == "md":
            st.markdown(text)
        else:
            st.code(text)
    else:
        st.info("该类型暂不支持预览，请下载查看")
