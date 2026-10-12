"""全局配置。所有路径、端口、外部服务地址集中在此，方便本地部署调参。"""
import os
from pathlib import Path

# 项目根目录（默认 /workspace），所有本地数据都落在 data/ 下，不经过任何第三方服务器
BASE_DIR = Path(os.environ.get("WORKBENCH_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "workbench.db"

# 服务绑定：0.0.0.0 便于手机在同一局域网访问
HOST = os.environ.get("WORKBENCH_HOST", "0.0.0.0")
PORT = int(os.environ.get("WORKBENCH_PORT", "8080"))
# 前端（Streamlit）访问后端时用的地址
API_BASE = os.environ.get("WORKBENCH_API", f"http://127.0.0.1:{PORT}")

# 可选访问密码（空表示不校验）
ACCESS_PASSWORD = os.environ.get("WORKBENCH_PASSWORD", "")
# 是否开启访问认证：配置了密码即为 True（由 WORKBENCH_PASSWORD 派生）
AUTH_REQUIRED = bool(ACCESS_PASSWORD)

# 进度节流：默认 500ms 一次，避免前端频繁重绘
PROGRESS_THROTTLE_MS = int(os.environ.get("PROGRESS_THROTTLE_MS", "500"))

# 本地大模型（oMLX / OpenAI 兼容接口）。未配置或连不上时自动回退到内置规则引擎。
OMLX_BASE_URL = os.environ.get("OMLX_BASE_URL", "")
OMLX_API_KEY = os.environ.get("OMLX_API_KEY", "")
OMLX_MODEL = os.environ.get("OMLX_MODEL", "local-model")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))

# 协调员对话上下文管理：超过阈值自动压缩为「历史记忆摘要」
CONTEXT_MAX_TOKENS = int(os.environ.get("CONTEXT_MAX_TOKENS", "3000"))
CONTEXT_KEEP_TURNS = int(os.environ.get("CONTEXT_KEEP_TURNS", "6"))
CONTEXT_SUMMARY_MAX_CHARS = int(os.environ.get("CONTEXT_SUMMARY_MAX_CHARS", "600"))

# 分层记忆：长期项目档案（结论/待办/偏好/关键数据）
CONTEXT_PROFILE_MAX_CHARS = int(os.environ.get("CONTEXT_PROFILE_MAX_CHARS", "800"))
# 每积累多少轮新对话就刷新一次长期档案（保证协调员持续跟进项目）
CONTEXT_PROFILE_REFRESH_TURNS = int(os.environ.get("CONTEXT_PROFILE_REFRESH_TURNS", "4"))
# 上下文硬盘缓存友好：稳定前缀（system + 项目档案 + 摘要）顺序与内容保持稳定，
# 便于 oMLX / vLLM 等推理服务命中前缀 KV 缓存，避免重复计算
CONTEXT_STABLE_PREFIX = os.environ.get("CONTEXT_STABLE_PREFIX", "1") == "1"

# 各 Agent 连接器（留空则使用内置本地模拟实现，仍会产生真实文件产物）
WORKBUDDY_URL = os.environ.get("WORKBUDDY_URL", "")
WORKBUDDY_CMD = os.environ.get("WORKBUDDY_CMD", "")
DOUBAO_BASE_URL = os.environ.get("DOUBAO_BASE_URL", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_MODEL = os.environ.get("DOUBAO_MODEL", "doubao-seed-1-6")
TRAE_URL = os.environ.get("TRAE_URL", "")

AGENT_META = {
    "user":        {"name": "我", "avatar": "🙋"},
    "coordinator": {"name": "协调员", "avatar": "🧠"},
    "workbuddy":   {"name": "Workbuddy", "avatar": "⚙️"},
    "doubao":      {"name": "豆包", "avatar": "✍️"},
    "trae":        {"name": "Trae", "avatar": "🛠️"},
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
