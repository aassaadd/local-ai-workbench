"""全局样式：响应式布局（PC 左右分栏 / 移动端底部导航）+ 进度条组件样式。"""
import streamlit as st

STATUS_COLOR = {
    "pending": "#9ca3af",
    "running": "#3b82f6",
    "success": "#10b981",
    "failed": "#ef4444",
    "cancelled": "#9ca3af",
}

CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-bottom: 1.5rem; max-width: 980px;}

/* 顶部视图切换（segmented control） */
.st-key-viewswitch {margin-bottom: 8px;}
.st-key-viewswitch [data-baseweb="button-group"] {width: 100%;}
.st-key-viewswitch button {flex: 1; font-weight: 600;}

/* 聊天气泡 */
[data-testid="stChatMessage"] {
    background: rgba(128,128,128,0.06);
    border-radius: 12px;
    padding: 8px 12px;
    margin-bottom: 6px;
}

/* ---- 进度卡片 ---- */
.prog-card {
    border: 1px solid rgba(128,128,128,0.25);
    border-left: 4px solid var(--prog-color, #9ca3af);
    border-radius: 10px;
    padding: 10px 12px;
    margin: 4px 0 6px 0;
    background: rgba(128,128,128,0.05);
}
.prog-title {font-weight: 600; font-size: 15px; margin-bottom: 8px;
    display: flex; justify-content: space-between; align-items: center; gap: 8px;}
.prog-phase {font-size: 12px; font-weight: 500; color: var(--prog-color, #9ca3af);
    border: 1px solid var(--prog-color, #9ca3af); border-radius: 999px;
    padding: 1px 8px; white-space: nowrap;}
.prog-bar {height: 9px; border-radius: 999px; background: rgba(128,128,128,0.22);
    overflow: hidden;}
.prog-fill {height: 100%; border-radius: 999px; transition: width .35s ease;
    background: var(--prog-color, #3b82f6);
    background-image: linear-gradient(90deg,
        rgba(255,255,255,.15) 0, rgba(255,255,255,.45) 50%, rgba(255,255,255,.15) 100%);
    background-size: 40px 100%; animation: prog-shimmer 1.2s linear infinite;}
.prog-card.done .prog-fill {animation: none; background-image: none;}
@keyframes prog-shimmer {from {background-position: -40px 0;} to {background-position: 40px 0;}}
.prog-meta {display: flex; justify-content: space-between; gap: 10px;
    margin-top: 6px; font-size: 12.5px; color: #8b8b8b;}
.prog-pct {font-weight: 700; color: var(--prog-color, #3b82f6);}
.prog-err {margin-top: 6px; font-size: 12.5px; color: #ef4444;
    background: rgba(239,68,68,0.08); border-radius: 6px; padding: 6px 8px;}

/* 文件卡片 */
.file-card {display: flex; align-items: center; gap: 8px; padding: 8px 10px;
    border: 1px solid rgba(128,128,128,0.25); border-radius: 10px;
    margin-top: 4px; background: rgba(128,128,128,0.05);}
.file-card a {text-decoration: none; font-weight: 600;}

/* 移动端：底部导航 */
@media (max-width: 768px) {
    .block-container {padding-left: 0.7rem; padding-right: 0.7rem;
        padding-bottom: 92px; max-width: 100%;}
    .st-key-viewswitch {
        position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
        background: var(--background-color, #fff);
        border-top: 1px solid rgba(128,128,128,0.25);
        padding: 8px 10px calc(8px + env(safe-area-inset-bottom)); margin: 0;}
    [data-testid="stChatMessage"] {padding: 6px 8px; border-radius: 10px;}
    .prog-title {font-size: 14px;}
    .prog-meta {font-size: 12px;}
    [data-testid="stSidebar"] {width: 78vw !important;}
}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
