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
./start.sh                # 一键：环境自检 → 按需建 venv / 装依赖 → 拉起前后端 → 自动打开浏览器
./start.sh --check        # 只做依赖自检与版本核查（不安装、不启动、不 open）
./start.sh --no-install   # 跳过依赖安装直接启动
./start.sh --no-open      # 启动但不自动打开浏览器
./start.sh --force        # 强制重新安装后端/前端依赖
./restart.sh              # 日常纯重启：清理旧进程 → 后端 → 等就绪 → 前端（不查依赖、不开浏览器）
./stop.sh                 # 按端口精确关闭本项目前后端
```

职责划分：`start.sh` 管环境与配置准备（以及开浏览器），进程管理仍委托 `restart.sh`（不重复实现）；
三者都 source 同一个 `.dev-ports.env`，不要在其中写死端口。

> 若系统 PATH 中找不到 `node`，可在项目根创建 `.node-path` 文件，写入本机 Node 的 `bin`
> 目录绝对路径，脚本会自动回退使用（含本机路径，已被 `.gitignore` 忽略）。

**新设备 / 首次运行**：直接 `./start.sh`。`backend/.venv` 缺失或不可用时会从零建（候选解释器
python3.12 → 3.13 → 3.11 → 3.10 → python3 逐个试、装成为止；3.12 排最前是因为它是 CI 钉的版本、
预编译轮子覆盖最稳）；`node_modules` 缺失会自动 `npm install`；`backend/.env` 缺失会从模板生成
（不覆盖已有文件）。两个依赖方向都按**内容指纹缓存**幂等（后端 `backend/.venv/.requirements-ok`、
前端 `node_modules/.package-lock-ok`），第二次起秒级跳过；`--force` 绕过缓存强装。
pip 连不上默认索引时会**自动改走清华镜像重试一次**（本机网络实测：Python 直连 pypi.org 全断、
清华可用）；npm 的 tarball 地址已固定进 `package-lock.json`（npmmirror），无需额外配置。

⚠️ 本节上面「后端」那段 `python3 -m venv .venv` **不要照抄就以为能起**，
原因见下面那条解释器约束：PATH 上的 `python3` 与本机跑得住的那套基座不是同一个东西。

> **历史与实测**：`start.sh` 曾于 10-07 下线、10-11 收尾删除（「留到项目结束统一重写」；本体可从
> `git log --all --oneline -- start.sh` 找回，四个开关名逐字沿用旧版）。**10-11 已重写回归**，同日实测：
> ① 本仓库全流程两跑 —— 首跑完成 pip 校验 + npm 刷新 + 拉起 + 开浏览器；二跑走指纹缓存两侧全跳过
> （约 23s，耗时都在 `restart.sh` 的就绪等待与 typecheck）。② 「从零建环境」端到端 —— 在同机 `/tmp`
> 克隆 + 端口隔离（`BACKEND_PORT=8011 FRONTEND_PORT=3401 ./start.sh`，`.dev-ports.env` 支持环境变量
> 覆盖）跑通：建 venv → 全量装依赖（pypi 直连失败自动落清华）→ 生成 `backend/.env` → 拉起 → 双端口
> 探活；`--force` / `--no-install` 同场补测通过。
> 另实测：本机 3.13 / 3.14 的解释器在本机网络下 pip 拉不到索引（3.12 正常，原因未深究）——
> 这是**本机网络环境**问题、不是依赖约束；新设备以 `./start.sh --check` 输出为准。

### 本机 Python 解释器约束（10-11 start.sh 重写已逐条落实）

这条理由原先**只写在 `start.sh` 第 40–43 行的注释里**，重写脚本前先挪进本文、免得随脚本一起消失
（10-11 重写已完成，约束仍以本文为单一出口）。下面每条都标了它现在的验证方式，不再以那段注释为证据：

- 部分嵌入式 Python（本机是 TRAE 工具链那一类）会往环境里注入 `PYTHONPATH`（混入其它版本的
  site-packages）与 `PYTHONHOME`，导致解释器／venv 行为异常 ⇒ 拉起后端前必须
  `unset PYTHONPATH PYTHONHOME PYTHONSTARTUP` 并对同名变量 `export -n`，别泄漏进后端进程。
- **`.venv` 在这台机器上做不到隔离，是当场可验的事实而不是推断**：`backend/.venv/bin/python --version`
  = 3.10.20，`sys.prefix` 指向 `.venv` 而 `sys.base_prefix` 指向
  `~/Library/Application Support/TRAE SOLO CN/…/python@3.10/…`，并且 `import fastapi` 解析到的是
  **基座解释器**的 `…/python@3.10/…/site-packages/fastapi/`。所以看到 `.venv/bin/python -m uvicorn`
  能起来，**不等于**依赖装在 venv 里 —— 排查后端 import 问题时按这条读，别拿"venv 里找不到包"当证据。
- ⚠️ 原注释那句「本机仅剩 python3.10 可用」**今天已不成立**（PATH 上 `python3` = 3.14.6，另有
  `~/.local/bin/python3.12`），别在重写脚本时把它抄回去；本节「环境要求」写的 `Python ≥ 3.9（CI 钉 3.12）`
  与本机的 3.10 基座是**三个不同的数**，别混成一个。
- 依赖是否就绪靠指纹缓存 `backend/.venv/.requirements-ok` 判断（幂等、第二次起秒开），
  要绕过它重装得显式 `--force`（该开关 10-11 已随 `start.sh` 重写补回）。

---

## 2. 云端后端（三选一）

后端以 **Dockerfile** 为共同构建产物，三个平台只是宿主不同：

| 路径 | 清单文件 | 持久化 |
|---|---|---|
| Railway | [railway.json](../railway.json)（DOCKERFILE builder，卷 `evergreen_data` → `/data/evergreen.db`） | 有卷，重启不丢 |
| Render | [render.yaml](../render.yaml)（服务名 `evergreen-worker`） | free 实例**无持久磁盘**，重启即丢 SQLite |
| 自管云主机 / 容器 | [deploy/README.md](../deploy/README.md)（`setup-vm.sh` + `docker-compose.yml` + nginx + systemd） | 自己挂盘 |

三者共同的环境变量：`APP_HOST=0.0.0.0`、`APP_PORT=8000`（**容器内端口**，与宿主映射端口无关）、
`EVERGREEN_DB_PATH=/data/evergreen.db`（**旧名 `VERDA_DB_PATH` 仍被读取**，两个都设时新名优先 ⇒
2026-10-11 改名前的部署不改控制台也能继续跑）、`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL*`、`BOCHA_API_KEY`。
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
`restart.sh` / `stop.sh` 都 source 它；`vite.config.ts` 在不经脚本直接启动时
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
