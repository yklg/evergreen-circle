# 常青圈 EvergreenCircle — 常驻 Worker 镜像
# 承载后台长任务（run_pipeline）与 SSE 思维流。
#
# 架构硬约束：
#   --workers 1  —— runner 的 _running 是「进程内存」任务表，多 worker 会破坏
#                   断连续跑 / 回放 / 取消（见 backend/app/core/runner.py）。
# 构建上下文 = 仓库根；完整依赖必须用 backend/requirements.txt（根目录那份是
# Vercel Serverless 精简版，缺 langgraph/langchain/matplotlib，严禁用于 worker）。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 部分 wheel 可能需编译（langgraph/langchain 依赖树、lxml 等），装完即清保持镜像精简
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用层缓存（requirements.txt 变更频率远低于业务代码）。
# 常青圈 living_circle 域（M1）：空间插值/等值线走 numpy 自实现 IDW + marching-squares，
# 不引入 scipy/shapely 重依赖（AK 演示与镜像体积双赢）——numpy 已随 requirements.txt 锁定。
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码。
# 运行时 DB 产物（data.db / verda.db*）是挂载卷里的，勿入镜像；
# 静态数据 backend/app/data/experts.json 必须随镜像带入。
COPY backend/ ./backend/
WORKDIR /app/backend

# APP_HOST 强制 0.0.0.0（config.py 默认 127.0.0.1 仅适合本机单用户）；
# APP_PORT 由 env 控制（默认 8000）。
# --workers 1           硬约束（见上）。
# --timeout-graceful-shutdown 30  在途 SSE 订阅优雅退出；任务由 runner 独立驱动，
#                                 容器重启后 lifespan 里的 reconcile_orphans() 会把
#                                 DB 残留 running 标 failed，前端悬浮条不会永久转圈。
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8000} --workers 1 --timeout-keep-alive 120 --timeout-graceful-shutdown 30"]
