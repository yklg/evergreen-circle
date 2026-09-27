# 部署说明 · Deployment

本文档说明常青圈 EvergreenCircle 的本地运行、云端部署与端口约定。

**后端只有 `backend/` 一份代码真相**：仓库里曾经并存一份 Vercel Serverless 镜像 `api/`，
该目录已删除（见 §5 历史注记）。当前云端形态是「容器化后端 + 前端静态托管」。

---

## 1. 本地部署

### 环境要求

- Node.js ≥ 22.12（本机若 PATH 里找不到 `node`，见 §1 末的 `.node-path`）
- Python ≥ 3.9（CI 钉 3.12）

### 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env            # 填入 LLM_API_KEY / BOCHA_API_KEY
.venv/bin/python -m uvicorn app.main:app --reload --port 8010
```

健康检查：`curl http://localhost:8010/health`
LLM 自检：`curl http://localhost:8010/api/llm/ping`

密钥变量主名是 `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL`（`app/core/config.py`）。
`ZHIPU_*` 同名系列作为**兼容兜底**仍被读取，但只算遗留通道，新配置不要再写它。
百度地图分两把 key：`BAIDU_SERVER_AK`（后端调用）与 `BAIDU_BROWSER_AK`
（前端 JS API 渲染，需在百度控制台配 Referer 白名单），后者经
`GET /api/life-circle/map-config` 下发给浏览器。

### 前端

```bash
cd frontend
npm install
npm run dev                     # http://localhost:3400
```

开发服务器通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:8010`
（见 [vite.config.ts](../frontend/vite.config.ts)）。

### 一键启停脚本（macOS / Linux）

```bash
./start.sh       # 首次起
./restart.sh     # 清理旧进程 → 启动后端 → 等就绪 → 启动前端
./stop.sh        # 按端口精确关闭本项目前后端
```

三个脚本都 source 同一个 `.dev-ports.env`，不要在其中写死端口。

> 若系统 PATH 中找不到 `node`，可在项目根创建 `.node-path` 文件，写入本机 Node 的 `bin`
> 目录绝对路径，`restart.sh` 会自动回退使用（含本机路径，已被 `.gitignore` 忽略）。

---

## 2. 云端后端（三选一）

后端以 **Dockerfile** 为共同构建产物，三个平台只是宿主不同：

| 路径 | 清单文件 | 持久化 |
|---|---|---|
| Railway | [railway.json](../railway.json)（DOCKERFILE builder，卷 `verda_data` → `/data/verda.db`） | 有卷，重启不丢 |
| Render | [render.yaml](../render.yaml)（服务名 `verda-worker`） | free 实例**无持久磁盘**，重启即丢 SQLite |
| 自管云主机 / 容器 | [deploy/README.md](../deploy/README.md)（`setup-vm.sh` + `docker-compose.yml` + nginx + systemd） | 自己挂盘 |

三者共同的环境变量：`APP_HOST=0.0.0.0`、`APP_PORT=8000`（**容器内端口**，与宿主映射端口无关）、
`VERDA_DB_PATH=/data/verda.db`、`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL*`、`BOCHA_API_KEY`。
密钥一律走平台的环境变量面板，**不要把 `.env` 提交进仓库**。

---

## 3. 前端静态托管

[vercel.json](../vercel.json) 现在**只承担前端静态托管**（`npm run build` → `frontend/dist`）。
它的 `/api/*` → `/api/index` rewrite 属于已废止的 Serverless 镜像方案，在 `api/` 删除后已失效，
保留仅为历史配置 —— 需要反代请在本平台配 rewrite 指向 §2 的 worker 公网地址，
或在构建期设 `VITE_API_BASE=https://<worker 公网地址>`（见
[frontend/.env.example](../frontend/.env.example)）。

⚠️ Vite 在**构建时**内联 `import.meta.env`，运行时改 `.env` 不生效：改 `VITE_API_BASE`
后必须重新部署才生效。

---

## 4. 端口约定

**单一真值源：仓库根 `.dev-ports.env`**（`BACKEND_PORT=8010` / `FRONTEND_PORT=3400`）。
`start.sh` / `restart.sh` / `stop.sh` 都 source 它；`vite.config.ts` 在不经脚本直接启动时
回落到同一组默认值，保证两条启动路径不分裂。

| 场景 | 端口 | 真值位置 |
|---|---|---|
| 前端 Vite（本地开发） | 3400 | `.dev-ports.env` · `vite.config.ts` 回落值 |
| 后端 FastAPI（本地开发） | 8010，仅监听 127.0.0.1 | `.dev-ports.env` · `restart.sh` |
| 后端 FastAPI（容器内） | **8000** | `app/core/config.py` 的 `app_port` · `Dockerfile` · `deploy/docker-compose.yml` · Railway/Render 的 `APP_PORT` |
| 宿主映射端口（自管部署） | 由 compose / nginx 决定 | `deploy/docker-compose.yml` · `deploy/nginx/*.conf` |

⚠️ 「容器内 8000」与「宿主 8010」不是一回事，也不互相要求一致；改端口只改 `.dev-ports.env`
（本地）或部署清单（云端），并同步 CORS 白名单 `FRONTEND_ORIGIN`。

---

## 5. 历史注记：`api/` 双源镜像约定已废止

`api/` 曾是 `backend/` 的 Vercel Serverless 可裁剪镜像（`api/index.py` 挂载同一个 FastAPI 应用），
配套约定是「改后端须同步两处」。该目录已从仓库删除，后端只有 `backend/` 一份真相。

相关的三处守卫在删除后曾长期**假绿**（目录不存在 ⇒ 比对集合为空 ⇒ 恒真通过），
已于 2026-09-26 改为「缺对象即显式 SKIP」：`scripts/check_app_mirror.sh`、
`backend/tests/test_api_mirror_guard.py`、`.github/workflows/ci.yml` 的 api/ 校验 step。
若将来重新引入镜像目录，这些守卫会自动恢复实际比对，无需重写。
