#!/usr/bin/env bash
# 一键启动：后端 FastAPI（8080） + 前端 Streamlit（8501）
set -e
cd "$(dirname "$0")"
export WORKBENCH_HOME="${WORKBENCH_HOME:-$(pwd)}"
export WORKBENCH_PORT="${WORKBENCH_PORT:-8080}"

# 优先使用项目内虚拟环境：代码用到 Python 3.10+ 语法，系统 python3 可能版本过低
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "[1/2] 启动后端 http://0.0.0.0:${WORKBENCH_PORT} ($PY)"
"$PY" -m uvicorn backend.main:app --host 0.0.0.0 --port "${WORKBENCH_PORT}" &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

sleep 1
echo "[2/2] 启动前端 http://0.0.0.0:8501"
# headless：跳过 Streamlit 首次运行的邮箱交互提示，保证脚本可非交互启动
"$PY" -m streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
