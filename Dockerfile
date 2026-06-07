# ============================================================
# Python Run Panel - 单容器多阶段构建 Dockerfile
# 阶段一：构建前端 (Node.js)
# 阶段二：运行环境 (Python 3.11 Slim)
# ============================================================

# ---------- 阶段一：前端构建 ----------
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend

# 复制前端依赖清单并安装
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --registry=https://registry.npmmirror.com 2>/dev/null || npm install

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ---------- 阶段二：最终运行镜像 ----------
FROM python:3.11-slim

LABEL maintainer="python-run-panel"
LABEL description="基于 Web 的容器化 Python 项目托管与进程管理面板"

# 换用清华 apt 镜像源加速下载
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# 安装必要的系统工具（lsof 用于检测进程监听端口）
# 清华源偶发 502，失败时回退到默认 Debian 源重试
RUN apt-get update && \
    (apt-get install -y --no-install-recommends --fix-missing \
    bash \
    curl \
    procps \
    lsof \
    python3-venv \
    || ( \
      sed -i 's/mirrors.tuna.tsinghua.edu.cn/deb.debian.org/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null && \
      apt-get update && \
      apt-get install -y --no-install-recommends bash curl procps lsof python3-venv \
    )) && \
    rm -rf /var/lib/apt/lists/*

# 创建工作目录和 workspace
RUN mkdir -p /app /data/workspace

WORKDIR /app

# 复制并安装 Python 依赖
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制后端源码
COPY backend/ /app/backend/

# 从构建阶段复制前端静态文件
COPY --from=frontend-builder /build/static /app/static

# 复制启动脚本
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# 暴露管理面板端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV WORKSPACE_DIR=/data/workspace
ENV STATIC_DIR=/app/static
ENV PANEL_PASSWORD=admin

# 健康检查
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 启动应用
ENTRYPOINT ["/app/start.sh"]
