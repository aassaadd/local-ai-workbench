#!/usr/bin/env bash
# 一键启动：后端 FastAPI（8080） + 前端 Streamlit（8501）
set -e
cd "$(dirname "$0")"
export WORKBENCH_HOME="${WORKBENCH_HOME:-$(pwd)}"
export WORKBENCH_PORT="${WORKBENCH_PORT:-8080}"

echo "[1/2] 启动后端 http://0.0.0.0:${WORKBENCH_PORT}"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "${WORKBENCH_PORT}" &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

sleep 1
echo "[2/2] 启动前端 http://0.0.0.0:8501"
python3 -m streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
