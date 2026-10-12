"""本地 AI 协作工作台 · Streamlit 主界面。

双视图：💬 与协调员私聊（仅结果类消息）/ 🧑‍🤝‍🧑 内部 Agent 群聊（只读全量过程）。
PC 端左右分栏 + 顶部切换；移动端（≤768px）自动切换为底部导航。
消息通过 WebSocket 后台线程实时同步，进度消息按 task_id 原地更新，不刷屏。
启用访问密码时先展示登录界面。
"""
import html
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


def _err_detail(exc: Exception) -> str:
    """从异常中提取后端返回的错误详情。

    参数：exc 为捕获到的异常（可能是 requests.HTTPError）。
    返回值：后端 detail 文案；无则回退为异常字符串。
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            return str(resp.json().get("detail", exc))
        except Exception:
            return f"{resp.status_code} {resp.text[:200]}"
    return str(exc)


def login_gate(cfg: dict) -> bool:
    """登录门：未启用认证直接放行；启用后校验令牌，未登录则渲染登录界面。

    Streamlit 每次 rerun 都是新的脚本执行态（但 session_state 保留），因此每
    次都需把已存令牌重新注入 api 模块。

    参数：cfg 为 /api/config 返回的配置字典。
    返回值：True 表示已认证、可继续渲染主界面；False 表示已渲染登录界面。
    """
    if not cfg.get("auth_required"):
        api.set_token(None)
        return True

    token = st.session_state.get("token")
    if token:
        api.set_token(token)
        return True

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("## 🧠 本地 AI 协作工作台")
        st.caption("该服务已启用访问密码，请输入以继续。")
        with st.form("login_form"):
            pwd = st.text_input("访问密码", type="password",
                                placeholder="来自 WORKBENCH_PASSWORD")
            if st.form_submit_button("登录", use_container_width=True):
                if not pwd:
                    st.error("请输入密码")
                else:
                    api.set_token(pwd)
                    if api.verify_auth():
                        st.session_state["token"] = pwd
                        st.rerun()
                    else:
                        api.set_token(None)
                        st.error("密码错误")
    return False


def ingest(msg: dict) -> None:
    """progress 消息以 task_id 为键原地更新，其他消息以 msg_id 为键追加。"""
    if msg.get("msg_type") == "progress" and msg.get("task_id"):
        key = f"task:{msg['task_id']}"
    else:
        key = msg.get("msg_id") or id(msg)
    st.session_state["msgs"][key] = msg


def ingest_older(msg: dict) -> bool:
    """分页加载更早消息时去重写入（不覆盖更新的同键消息）。

    参数：msg 为消息字典。
    返回值：True 表示新写入；False 表示已存在且不更旧。
    """
    if msg.get("msg_type") == "progress" and msg.get("task_id"):
        key = f"task:{msg['task_id']}"
    else:
        key = msg.get("msg_id") or id(msg)
    exist = st.session_state["msgs"].get(key)
    if exist is not None and exist.get("timestamp", 0) >= msg.get("timestamp", 0):
        return False
    st.session_state["msgs"][key] = msg
    return True


def seed_if_needed(project: str) -> None:
    """首次进入某项目时加载最近消息与进行中任务（仅在切换项目时重置）。"""
    if st.session_state.get("loaded_project") == project:
        return
    st.session_state["msgs"] = {}
    st.session_state["preview"] = None
    for m in api.get_messages(project, "group", limit=200):
        ingest(m)
    for m in api.active_tasks(project):  # 重连时同步进行中的任务
        ingest(m)
    st.session_state["loaded_project"] = project


@st.fragment(run_every=1.0)
def stream_area(project: str, view: str, session_id: str, meta: dict) -> None:
    client = ws_client.get_client(session_id, project)
    client.drain(ingest)  # 拉取后台线程收到的增量消息

    msgs = list(st.session_state["msgs"].values())
    # 按时间排序：分页加载的更早消息会自然排到顶部
    msgs.sort(key=lambda m: m.get("timestamp", 0))
    if view == VIEW_PRIVATE:
        msgs = [m for m in msgs if m.get("visibility") == "all"]

    keyword = (st.session_state.get("msg_search") or "").strip().lower()
    if keyword:
        msgs = [m for m in msgs if _match_keyword(m, keyword)]

    if not msgs:
        st.caption("暂无消息，发一句话给协调员试试 👇" if not keyword else "没有匹配的消息")
        return

    def cancel(task_id: str) -> None:
        api.cancel_task(task_id)

    for m in msgs:
        ui.render_message(m, meta, cancel_cb=cancel)

    if view == VIEW_GROUP:
        st.caption("🔒 内部群聊为只读视图，仅用于查看完整执行过程")


def _match_keyword(msg: dict, keyword: str) -> bool:
    """判断消息是否命中搜索关键字。

    参数：
        msg: 消息字典。
        keyword: 已小写化的关键字。
    返回值：命中返回 True，否则 False（进度消息匹配任务名 + 步骤）。
    """
    if msg.get("msg_type") == "progress":
        hay = f"{msg.get('task_name', '')} {msg.get('step', '')}"
    else:
        hay = msg.get("content", "")
    return keyword in hay.lower()


def render_import_panel(project: str) -> None:
    """侧栏「导入聊天记录」区：上传导出文件、查看已导入文件、载入示例数据。

    参数：project 为当前项目名称。
    返回值：无。
    """
    with st.expander("📥 导入聊天记录", expanded=False):
        with st.form("import_form", clear_on_submit=True):
            ups = st.file_uploader("选择导出文件（csv / json / txt，可多选）",
                                   type=["csv", "json", "txt"],
                                   accept_multiple_files=True)
            submitted = st.form_submit_button("开始导入", use_container_width=True)
        if submitted and ups:
            for up in ups:
                try:
                    res = api.upload_import(project, up.name, up.getvalue())
                    st.success(f"已导入 {up.name}，共 {res.get('records', 0)} 个会话")
                except Exception as exc:
                    st.error(f"导入 {up.name} 失败：{_err_detail(exc)}")

        imports = api.list_imports(project)
        if imports:
            st.caption(f"已导入 {len(imports)} 个文件")
            for it in imports:
                st.markdown(
                    f"<small>· {html.escape(it['name'])}"
                    f"（{it.get('records', '-')} 会话）</small>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("暂无导入数据")
            if st.button("✨ 载入示例数据", key=f"btn_sample_{project}",
                         use_container_width=True):
                try:
                    api.load_sample(project)
                    st.success("示例数据已载入")
                    st.rerun()
                except Exception as exc:
                    st.error(f"载入失败：{_err_detail(exc)}")


def render_progress_history_panel(project: str) -> None:
    """侧栏「进度历史」面板：展示最近 30 条任务记录。

    参数：project 为当前项目名称。
    返回值：无。
    """
    with st.expander("📊 进度历史", expanded=False):
        hist = api.progress_history(project, 30)
        if not hist:
            st.caption("暂无进度记录")
            return
        for item in hist:
            ui.render_progress_history_item(item)


def render_file_list(project: str, scope: str) -> None:
    """侧栏「项目文件夹」列表：每行提供下载链接与在线预览按钮。

    参数：
        project: 当前项目名称。
        scope: 目录范围（public / private）。
    返回值：无。
    """
    files = api.list_files(project, scope)
    if not files:
        st.caption("（空）")
        return
    for f in files:
        url = api.file_url(project, f["name"], scope, download=1)
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"[📎 {f['name']}]({url})  \n<small style='color:#999'>"
                    f"{ui.fmt_size(f['size'])}</small>", unsafe_allow_html=True)
        if c2.button("👁", key=f"prev_{scope}_{f['name']}", help="在线预览"):
            st.session_state["preview"] = {"scope": scope, "name": f["name"]}
            st.rerun()


def render_preview_panel(project: str) -> None:
    """主区域文件预览面板（有选中文件时渲染，含关闭按钮）。

    参数：project 为当前项目名称。
    返回值：无。
    """
    preview = st.session_state.get("preview")
    if not preview:
        return
    with st.expander(f"👁 预览：{preview['name']}", expanded=True):
        ui.render_preview(project, preview["scope"], preview["name"])
        if st.button("关闭预览", key="close_preview"):
            st.session_state["preview"] = None
            st.rerun()


def render_load_earlier(project: str) -> None:
    """「加载更早」按钮：以当前最早消息时间戳为游标拉取更早的群聊消息。

    参数：project 为当前项目名称。
    返回值：无。
    """
    if st.button("⬆️ 加载更早", key="load_earlier"):
        stamps = [m.get("timestamp", 0) for m in st.session_state["msgs"].values()
                  if m.get("timestamp")]
        before = min(stamps) if stamps else None
        older = api.get_messages(project, "group", limit=200, before=before)
        added = sum(1 for m in older if ingest_older(m))
        st.caption(f"✅ 已加载 {added} 条更早消息" if added else "已到最早消息")


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
    ss.setdefault("preview", None)

    cfg = api.get_config()
    meta = cfg.get("agents", {}) or {}

    # ---------------- 登录门 ----------------
    if not login_gate(cfg):
        return

    session_id = get_session_id()

    # ---------------- 侧边栏：项目列表 + 导入 + 文件 + 进度历史 ----------------
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
        render_import_panel(project)

        st.divider()
        st.markdown("### 📂 项目文件夹")
        scope = st.radio("目录", ["public", "private"], horizontal=True,
                         key="scope", label_visibility="collapsed")
        render_file_list(project, scope)

        st.divider()
        render_progress_history_panel(project)

        st.divider()
        render_memory_panel(project)

        st.divider()
        online = api.health()
        st.caption(("🟢 后端在线" if online else "🔴 后端离线") +
                   f"  \n节流 {cfg.get('progress_throttle_ms', 500)}ms" +
                   ("  \n🤖 本地模型已接入" if cfg.get("llm_configured") else "  \n🧩 规则引擎模式"))

    seed_if_needed(project)

    # ---------------- 视图切换 + 搜索 ----------------
    st.markdown(f"#### {project}　<span style='font-size:13px;color:#999'>"
                f"（手机端可访问同一地址，实时同步）</span>", unsafe_allow_html=True)
    view = st.segmented_control(
        "视图", options=[VIEW_PRIVATE, VIEW_GROUP],
        default=VIEW_PRIVATE, key="viewswitch", label_visibility="collapsed",
    ) or VIEW_PRIVATE

    st.text_input("搜索消息", key="msg_search", placeholder="🔍 搜索消息",
                  label_visibility="collapsed")

    # ---------------- 预览面板 + 加载更早 ----------------
    render_preview_panel(project)
    render_load_earlier(project)

    # ---------------- 消息流（自动刷新片段） ----------------
    stream_area(project, view, session_id, meta)

    # ---------------- 输入框：仅私聊视图可发言 ----------------
    # 说明：st.chat_input 采用「始终渲染 + 按视图禁用」，而非条件渲染。
    # Streamlit 对条件渲染的 chat_input 存在不卸载的怪癖（切到群聊后输入框仍可见），
    # 用 disabled 既能保证群聊只读，又避免该问题。
    prompt = st.chat_input(
        "发消息给协调员…（例：把昨天所有外部联系人的聊天记录批量生成客户意向摘要）",
        disabled=(view != VIEW_PRIVATE),
    )
    if view == VIEW_PRIVATE:
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