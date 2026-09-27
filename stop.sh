#!/usr/bin/env bash
# 关闭常青圈 EvergreenCircle 的后端与前端（端口见 ./.dev-ports.env，默认后端 :8010 / 前端 :3400）
# 优先按 PID 文件以进程组方式精确关闭（覆盖 npm→vite 子进程），再按端口兜底。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=.dev-ports.env
. "$ROOT/.dev-ports.env"
LOG_DIR="$ROOT/.run-logs"

echo "停止本项目后端/前端进程..."
for name in backend frontend; do
  pidfile="$LOG_DIR/$name.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if [ -n "$pid" ]; then
      echo "  停止 $name (pid/组 $pid)"
      # 按进程组（-PID）kill，连带清掉 npm→vite 子进程
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null
      sleep 1
      kill -9 -- -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done

# 兜底：按端口清理残留（兼容非本脚本启动的进程 / pidfile 已失效的孤儿）
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)"
  if [ -n "$pids" ]; then
    echo "  释放端口 $port: $pids"
    for pid in $pids; do
      kill -- -"$pid" 2>/dev/null   # 进程组优先（覆盖 npm→vite 子进程）
      kill "$pid" 2>/dev/null        # 单进程兜底
    done
    sleep 1
    pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)"
    if [ -n "$pids" ]; then
      for pid in $pids; do
        kill -9 -- -"$pid" 2>/dev/null
        kill -9 "$pid" 2>/dev/null
      done
    fi
  fi
done
echo "已停止。"
