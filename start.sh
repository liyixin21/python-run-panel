#!/usr/bin/env bash
# ============================================================
# Python Run Panel 容器启动脚本
# ============================================================

set -e

echo "=========================================="
echo "  Python Run Panel - 容器启动中..."
echo "=========================================="
echo "  工作区目录:  ${WORKSPACE_DIR:-/data/workspace}"
echo "  静态文件:    ${STATIC_DIR:-/app/static}"
echo "  面板端口:    8000"
echo "=========================================="

mkdir -p "${WORKSPACE_DIR:-/data/workspace}"

exec python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --log-level info
