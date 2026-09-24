# 部署说明 · Deployment

本文档说明青野 Verda 的本地运行与 Vercel 云部署，以及 `backend/` 与 `api/` 两份后端代码的同步约定。

---

## 1. 本地部署

### 环境要求

- Node.js ≥ 22.12
- Python ≥ 3.9

### 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env          # 填入 ZHIPU_API_KEY 等密钥
.venv/bin/python -m uvicorn app.main:app --reload --port 8020
```

健康检查：`curl http://localhost:8020/health`
LLM 自检：`curl http://localhost:8020/api/llm/ping`

### 前端

```bash
cd frontend
npm install
npm run dev                    # http://localhost:3500
```

前端开发服务器通过 Vite 代理把 `/api` 转发到后端（见 [vite.config.ts](../frontend/vite.config.ts)），默认代理目标 `http://127.0.0.1:8020`。

### 一键启停脚本（macOS / Linux）

```bash
./restart.sh   # 清理旧进程 → 启动后端(:8020) → 等待就绪 → 启动前端(:3500)
./stop.sh      # 按端口精确关闭本项目前后端
```

> 若系统 PATH 中找不到 `node`，可在项目根目录创建 `.node-path` 文件，写入本机 Node 的 `bin` 目录绝对路径，`restart.sh` 会自动回退使用（该文件含本机路径，已被 `.gitignore` 忽略，不会提交）。

---

## 2. Vercel 云部署

项目已配置好 [vercel.json](../vercel.json)，可直接部署到 Vercel：

```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "frontend/dist",
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/index" },
    { "source": "/health",   "destination": "/api/index" },
    { "source": "/(.*)",     "destination": "/index.html" }
  ]
}
```

部署步骤：

1. 在 [Vercel](https://vercel.com/) 导入本仓库。
2. 在 **Project Settings → Environment Variables** 配置密钥（**切勿**把 `.env` 提交到仓库）：
   - `ZHIPU_API_KEY`（必填）
   - `BOCHA_API_KEY`（联网采集必填）
   - 其余可选：`ZHIPU_MODEL*` / `DOUYIN_COOKIE` / `BILIBILI_COOKIE` / `XHS_COOKIE` / `ENABLE_DEMO_FALLBACK`
3. 触发部署。前端构建产物输出到 `frontend/dist`，`/api/*` 与 `/health` 路由到 Serverless 函数 `api/index.py`。

> **SQLite 与持久化注意**：Vercel Serverless 文件系统是只读的，运行时仅 `/tmp` 可写且不跨实例持久化。云端部署下数据库不具备本地那样的持久能力，适合演示；生产环境建议替换为托管数据库。

---

## 3. `backend/` 与 `api/` 同步约定

这是本项目一个需要明确的工程约定，避免误解为「冗余代码」：

| 目录 | 角色 | 何时使用 |
|---|---|---|
| `backend/` | **本地开发主目录** | 本地运行、调试、单元验证 |
| `api/` | **Vercel 部署镜像** | 仅云端部署使用（Vercel 约定 Serverless 函数置于 `api/`） |

- 两者的 `app/core/*` 业务逻辑保持一致。
- `api/index.py` 是 Vercel 的 Serverless 入口，内部挂载与 `backend/app/main.py` 相同的 FastAPI 应用。
- **修改后端逻辑时，需同步更新两处**（或在发布流程中以 `backend/app` 为准镜像到 `api/app`）。

> 之所以保留两份而非软链接 / 构建期拷贝，是为了让仓库在「克隆即可本地跑」与「连接 Vercel 即可部署」两种场景下都开箱即用，降低新贡献者的上手成本。后续若引入构建步骤，可改为单一来源 + 自动镜像。

---

## 4. 端口约定

| 服务 | 端口 | 配置位置 |
|---|---|---|
| 前端 Vite | 3500 | [vite.config.ts](../frontend/vite.config.ts) · restart.sh / stop.sh |
| 后端 FastAPI（本地脚本） | 8020 | restart.sh · vite 代理目标 |
| 后端 FastAPI（代码默认值） | 8000 | `config.py` 的 `app_port` · `.env` 的 `APP_PORT` |

修改端口时请保持以上各处一致（尤其是 Vite 代理目标与后端实际端口、CORS 白名单 `FRONTEND_ORIGIN`）。
