#!/usr/bin/env bash
# 常青圈 EvergreenCircle 一键启动 / 重启脚本
# 用法：在项目根目录执行  ./restart.sh
# 端口（后端 8010 / 前端 3400）单一真值源在 ./.dev-ports.env，与 start.sh/stop.sh 共用。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.dev-ports.env
. "$ROOT/.dev-ports.env"
LOG_DIR="$ROOT/.run-logs"
mkdir -p "$LOG_DIR"

# 定位 Node
NODE_BIN=""
if command -v node >/dev/null 2>&1; then
  NODE_BIN="$(dirname "$(command -v node)")"
elif [ -f "$ROOT/.node-path" ]; then
  c="$(cat "$ROOT/.node-path")"
  [ -x "$c/node" ] && NODE_BIN="$c"
fi
if [ -n "$NODE_BIN" ]; then export PATH="$NODE_BIN:$PATH"; fi

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null)"
  if [ -n "$pids" ]; then
    echo "  端口 $port 被占用，正在结束进程: $pids"
    # 同时杀进程组（detached_run 用 setsid，PGID==leader PID），覆盖 npm→vite 子进程；
    # 否则只杀监听的 node 子进程、npm 父进程残留，下次绑定仍会报端口占用。
    for pid in $pids; do
      kill -- -"$pid" 2>/dev/null   # 进程组优先
      kill "$pid" 2>/dev/null        # 单进程兜底
    done
    sleep 1
    pids="$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null)"
    if [ -n "$pids" ]; then
      echo "  强制结束: $pids"
      for pid in $pids; do
        kill -9 -- -"$pid" 2>/dev/null
        kill -9 "$pid" 2>/dev/null
      done
      sleep 1
    fi
  fi
  # 校验：若仍未释放，明确告警（避免新实例绑定失败、留下僵死的 pidfile）
  if lsof -nP -iTCP:$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "  WARNING: 端口 $port 仍被占用，新实例可能无法绑定。"
  fi
}

# 用 python3 os.setsid() 新建独立 session（macOS 无 setsid 命令，故走 python），
# 再 execvp 接管命令：PID 文件即真实服务 PID，其进程组（PGID==该 PID）覆盖 npm→vite 子进程。
# 注意：python 直接后台，不再包 ( ... ) 子 shell —— 否则子 shell 残留在 restart.sh 进程树里，
# 父进程退出时会被连带回收，导致关终端即白屏。
detached_run() {
  local pidfile="$1" logfile="$2" workdir="$3"; shift 3
  python3 -c '
import os, sys
pidfile, logfile, workdir = sys.argv[1], sys.argv[2], sys.argv[3]
cmd = sys.argv[4:]
with open(pidfile, "w") as f:
    f.write(str(os.getpid()))
os.chdir(workdir)
os.setsid()
lf = open(logfile, "a")
os.dup2(lf.fileno(), 1)   # stdout -> logfile
os.dup2(lf.fileno(), 2)   # stderr -> logfile
os.dup2(os.open(os.devnull, os.O_RDONLY), 0)  # stdin  -> /dev/null
os.execvp(cmd[0], cmd)
' "$pidfile" "$logfile" "$workdir" "$@" </dev/null &
}

echo "==> 1/4 清理旧进程"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "==> 2/4 启动后端 (FastAPI :$BACKEND_PORT)"
detached_run "$LOG_DIR/backend.pid" "$LOG_DIR/backend.log" "$ROOT/backend" \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
echo "  后端日志: $LOG_DIR/backend.log"

echo "==> 3/4 等待后端就绪"
ok=0
for i in $(seq 1 30); do
  if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$BACKEND_PORT/health"; then
    ok=1; break
  fi
  sleep 1
done
if [ "$ok" = "1" ]; then
  echo "  后端已就绪 OK  http://127.0.0.1:$BACKEND_PORT/health"
  echo "  LLM 自检: $(curl -s --max-time 60 "http://127.0.0.1:$BACKEND_PORT/api/llm/ping")"
else
  echo "  WARNING: 后端 30s 内未就绪，请查看日志: $LOG_DIR/backend.log"
fi

echo "==> 4/4 启动前端 (Vite :$FRONTEND_PORT)"
if [ -z "$NODE_BIN" ] && ! command -v npm >/dev/null 2>&1; then
  echo "  WARNING: 未找到 Node/npm，跳过前端。"
else
  cd "$ROOT/frontend"
  [ -d node_modules ] || { echo "  安装前端依赖..."; npm install; }
  # 门禁：启动前做一次类型检查。tsconfig.json 为 solution 风格（files:[]+references），
  # 默认 `tsc --noEmit` 不会检查任何文件（假通过）。必须用 -p tsconfig.app.json 真正覆盖 src。
  # 此检查不阻断启动（仅告警），避免本地改动未过 tsc 却直接 dev 再次引入运行时白屏。
  (cd "$ROOT/frontend" && npm run typecheck) \
    || echo "  WARNING: 前端类型检查未通过（详见上方 tsc 输出）。启动仍继续，但请尽快修复以免白屏。"
  detached_run "$LOG_DIR/frontend.pid" "$LOG_DIR/frontend.log" "$ROOT/frontend" \
    npm run dev
  echo "  前端日志: $LOG_DIR/frontend.log"
  echo ""
  echo "============================================================"
  echo "  OK - 启动完成"
  echo "  预览地址:  http://localhost:$FRONTEND_PORT/"
  echo "  后端接口:  http://127.0.0.1:$BACKEND_PORT/"
  echo "  关闭服务:  ./stop.sh"
  echo "============================================================"
fi
