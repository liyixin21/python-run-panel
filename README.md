# Python Run Panel

基于 Web 的容器化 Python 项目托管与进程管理面板。每个项目拥有独立的虚拟环境与进程生命周期，
支持实时日志、Web 终端、文件管理与依赖安装。

## 功能

- **项目管理**：创建 / 删除项目，自动生成独立 venv，互不干扰
- **进程控制**：启动 / 停止 / 重启，崩溃自动重启，面板启动时自启
- **实时日志**：WebSocket 推送进程 stdout/stderr，支持清屏
- **Web 终端**：基于 PTY 的全双工终端，自动注入项目 venv
- **文件管理**：浏览、上传（含文件夹、拖拽）、在线编辑、删除
- **依赖管理**：一键安装 requirements.txt、单包安装 / 卸载
- **防火墙联动**：检测到监听端口后通过 1Panel API 自动放行

## 快速开始

### Docker（推荐）

```bash
docker compose up -d --build
# 或使用预构建镜像
docker compose -f docker-compose.prod.yml up -d
```

访问 `http://<主机>:8000`，默认账号 `admin` / `admin`，**首次登录后请立即修改密码**。

### 本地开发

需要两个终端：后端提供 API，前端 Vite 提供热更新。

```bash
# 终端 1：后端（监听 8000）
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 2：前端（监听 5173，已配置代理到 8000）
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。

### 本地生产模式

前端构建产物会输出到 `static/`，此时后端可直接托管整个 SPA：

```bash
cd frontend && npm run build && cd ..
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

> 若 `static/` 目录不存在，后端启动时会打印警告，此时只有 API 可用、页面无法访问。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WORKSPACE_DIR` | `./workspace` | 项目与数据库存放目录 |
| `STATIC_DIR` | `./static` | 前端构建产物目录 |
| `PANEL_PASSWORD` | `admin` | 初始管理员密码（仅首次启动生效） |
| `DATABASE_URL` | `sqlite+aiosqlite:///{WORKSPACE_DIR}/panel.db` | 数据库连接串 |
| `TOKEN_EXPIRE_SECONDS` | `86400` | 登录有效期（秒） |
| `CORS_ORIGINS` | 空 | 允许的跨域来源，逗号分隔；留空则不启用 CORS |

## 目录结构

```
backend/
  main.py                 应用入口、路由注册、静态托管
  config.py               全局配置
  database.py             引擎、迁移
  models.py               ORM 模型
  utils.py                密码哈希、路径安全、时间处理
  routers/                API 路由（auth/projects/processes/files/...）
  services/               业务服务（进程、项目、终端、防火墙）
frontend/
  src/views/              页面
  src/components/         组件
  src/composables/        可复用逻辑
  src/config.js           可配置的前端元信息
workspace/                运行时数据（项目、venv、panel.db、tokens.json）
```

## 安全说明

- 所有文件操作都经过 `utils.safe_join` 做路径边界校验，项目名有白名单限制
- WebSocket（日志、终端）均需 token 校验
- 修改密码会撤销全部登录态，需重新登录
- `workspace/` 含数据库、token 与防火墙 API Key，**不要提交到版本库**（已在 `.gitignore` 中）

## 端口自动放行

在「设置」页配置 1Panel 地址与 API Key 后，面板会在检测到项目监听端口时自动调用
1Panel API 放行。代码同时兼容 1Panel 的新版规则接口与旧版端口接口，无需手动切换。

## 许可

见仓库 LICENSE。
