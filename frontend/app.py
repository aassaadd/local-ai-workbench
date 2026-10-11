"""本地 AI 协作工作台 · Streamlit 主界面。

双视图：💬 与协调员私聊（仅结果类消息）/ 🧑‍🤝‍🧑 内部 Agent 群聊（只读全量过程）。
PC 端左右分栏 + 顶部切换；移动端（≤768px）自动切换为底部导航。
消息通过 WebSocket 后台线程实时同步，进度消息按 task_id 原地更新，不刷屏。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from frontend import api, ui, ws_client
from frontend.styles import inject

st.set_page_config(page_title="本地 AI 协作工作台", page_icon="🧠", layout="wide")

VIEW_PRIVATE = "💬 与协调员对话"
VIEW_GROUP = "🧑‍🤝‍🧑 内部 Agent 群聊"


def get_session_id() -> str:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx and ctx.session_id:
            return ctx.session_id
    except Exception:
        pass
    return "default"


def ingest(msg: dict) -> None:
    """progress 消息以 task_id 为键原地更新，其他消息以 msg_id 为键追加。"""
    if msg.get("msg_type") == "progress" and msg.get("task_id"):
        key = f"task:{msg['task_id']}"
    else:
        key = msg.get("msg_id") or id(msg)
    st.session_state["msgs"][key] = msg


def seed_if_needed(project: str) -> None:
    if st.session_state.get("loaded_project") == project:
        return
    st.session_state["msgs"] = {}
    for m in api.get_messages(project, "group", limit=200):
        ingest(m)
    for m in api.active_tasks(project):  # 重连时同步进行中的任务
        ingest(m)
    st.session_state["loaded_project"] = project


@st.fragment(run_every=1.0)
def stream_area(project: str, view: str, session_id: str, meta: dict) -> None:
    client = ws_client.get_client(session_id, project)
    client.drain(ingest)  # 拉取后台线程收到的增量消息

    msgs = list(st.session_state["msgs"].values())  # 保持插入顺序（原地更新不换位）
    if view == VIEW_PRIVATE:
        msgs = [m for m in msgs if m.get("visibility") == "all"]

    if not msgs:
        st.caption("暂无消息，发一句话给协调员试试 👇")
        return

    def cancel(task_id: str) -> None:
        api.cancel_task(task_id)

    for m in msgs:
        ui.render_message(m, meta, cancel_cb=cancel)

    if view == VIEW_GROUP:
        st.caption("🔒 内部群聊为只读视图，仅用于查看完整执行过程")


def render_memory_panel(project: str) -> None:
    """协调员长期记忆面板：可查看、编辑、清空（记忆可编辑）。"""
    mem = api.get_memory(project)
    prof = mem.get("profile") or {}
    last = mem.get("last") or {}
    with st.expander("🧠 协调员记忆（可编辑）", expanded=False):
        st.caption(f"阈值 {mem.get('context_max_tokens', '-')} tokens"
                   f" ｜ 保留最近 {mem.get('keep_turns', '-')} 轮"
                   f" ｜ 前缀稳定 {'开' if mem.get('cache_stable') else '关'}")
        if last:
            st.caption(f"上次装配 {last.get('tokens_before')} → {last.get('tokens_after')} tokens"
                       + ("（已压缩）" if last.get("compressed") else "（未压缩）")
                       + f" ｜ 前缀指纹 {last.get('prefix_hash', '-')}")
            for tier in last.get("plan", []):
                st.markdown(f"<small>· {tier['desc']}：{tier['tokens']} tokens</small>",
                            unsafe_allow_html=True)

        with st.form(key=f"mem_form_{project}"):
            goal = st.text_input("项目目标", value=prof.get("goal", ""))
            facts = st.text_area("关键结论（每行一条）",
                                 value="\n".join(prof.get("facts", [])), height=76)
            todos = st.text_area("待办事项（每行一条）",
                                 value="\n".join(prof.get("todos", [])), height=76)
            prefs = st.text_area("用户偏好（每行一条）",
                                 value="\n".join(prof.get("prefs", [])), height=68)
            c1, c2 = st.columns(2)
            if c1.form_submit_button("保存记忆", use_container_width=True):
                try:
                    api.update_memory(project, {"goal": goal, "facts": facts,
                                                "todos": todos, "prefs": prefs})
                    st.success("已保存")
                    st.rerun()
                except Exception as exc:
                    st.error(f"保存失败：{exc}")
            if c2.form_submit_button("清空记忆", use_container_width=True):
                api.clear_memory(project)
                st.success("已清空")
                st.rerun()

        if mem.get("summary"):
            st.markdown("**滚动摘要**")
            st.markdown(mem["summary"])
        else:
            st.caption("暂无摘要（对话超过阈值后自动生成）")


def main() -> None:
    inject()
    ss = st.session_state
    ss.setdefault("msgs", {})
    ss.setdefault("loaded_project", None)
    session_id = get_session_id()
    cfg = api.get_config()
    meta = cfg.get("agents", {}) or {}

    # ---------------- 侧边栏：项目列表 + 文件 ----------------
    with st.sidebar:
        st.markdown("### 📁 项目列表")
        projs = api.list_projects()
        names = [p["name"] for p in projs] or ["默认项目"]
        if not projs:
            try:
                api.create_project("默认项目")
                names = ["默认项目"]
            except Exception:
                pass
        project = st.selectbox("当前项目", names, key="proj_select",
                               label_visibility="collapsed")
        ss["project"] = project

        with st.expander("➕ 新建项目"):
            new_name = st.text_input("项目名", key="new_proj_name",
                                     placeholder="如：客户跟进")
            if st.button("创建项目", key="btn_create_proj") and new_name.strip():
                try:
                    api.create_project(new_name.strip())
                    st.success(f"已创建：{new_name.strip()}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"创建失败：{exc}")

        st.divider()
        st.markdown("### 📂 项目文件夹")
        scope = st.radio("目录", ["public", "private"], horizontal=True,
                         key="scope", label_visibility="collapsed")
        files = api.list_files(project, scope)
        if not files:
            st.caption("（空）")
        for f in files:
            url = api.file_url(project, f["name"], scope, download=1)
            st.markdown(f"[📎 {f['name']}]({url})  \n<small style='color:#999'>"
                        f"{ui.fmt_size(f['size'])}</span>", unsafe_allow_html=True)

        st.divider()
        render_memory_panel(project)

        st.divider()
        online = api.health()
        st.caption(("🟢 后端在线" if online else "🔴 后端离线") +
                   f"  \n节流 {cfg.get('progress_throttle_ms', 500)}ms" +
                   ("  \n🤖 本地模型已接入" if cfg.get("llm_configured") else "  \n🧩 规则引擎模式"))

    seed_if_needed(project)

    # ---------------- 视图切换 ----------------
    st.markdown(f"#### {project}　<span style='font-size:13px;color:#999'>"
                f"（手机端可访问同一地址，实时同步）</span>", unsafe_allow_html=True)
    view = st.segmented_control(
        "视图", options=[VIEW_PRIVATE, VIEW_GROUP],
        default=VIEW_PRIVATE, key="viewswitch", label_visibility="collapsed",
    ) or VIEW_PRIVATE

    # ---------------- 消息流（自动刷新片段） ----------------
    stream_area(project, view, session_id, meta)

    # ---------------- 输入框：仅私聊视图 ----------------
    if view == VIEW_PRIVATE:
        prompt = st.chat_input("发消息给协调员…（例：把昨天所有外部联系人的聊天记录批量生成客户意向摘要）")
        if prompt:
            try:
                sent = api.send_message(project, prompt)
                if sent:
                    ingest(sent)
                st.rerun()
            except Exception as exc:
                st.error(f"发送失败：{exc}")
    else:
        st.caption("（内部群聊为只读视图，无法发言）")


if __name__ == "__main__":
    main()
