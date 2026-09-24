#!/usr/bin/env bash
# =============================================================================
# 常青圈 · 15 分钟生活圈智能体检 —— 一键启动脚本
#
# 定位：从零到跑全自动。首次使用或依赖缺失时自动完成
#   （后端 venv 创建 / pip 安装 · 前端 npm install），之后幂等秒开。
# 职责划分：
#   start.sh   本脚本            —— 环境自检 + 依赖准备 + 拉起服务 + 打开浏览器
#   restart.sh 既有脚本          —— 进程清理 + 后台启动 + 就绪检查（被本脚本复用）
#   stop.sh    既有脚本          —— 关闭服务
#
# 用法：
#   ./start.sh                一键启动（自检 → 按需安装 → 启动 → 自动打开浏览器）
#   ./start.sh --check        只做依赖自检与版本核查，不启动、不安装、不 open
#   ./start.sh --no-install   跳过依赖安装，直接启动（适合依赖已就绪）
#   ./start.sh --no-open      启动但不自动打开浏览器
#   ./start.sh --force        强制重新安装后端/前端依赖（即使看起来已就绪）
#   ./start.sh -h | --help    查看帮助
# 说明：请务必在项目根目录（脚本所在目录）执行；可从任意路径调用。
# =============================================================================
set -u

# ---------------------------------------------------------------------------
# 常量：目录 / 路径（基于脚本真实位置，可被任意路径调用）；端口见 .dev-ports.env
# ---------------------------------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "$0")"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
# 端口单一真值源（与 restart.sh/stop.sh 共用；支持环境变量覆盖）
# shellcheck source=.dev-ports.env
. "$ROOT/.dev-ports.env"
LOG_DIR="$ROOT/.run-logs"
REQ_FILE="$BACKEND_DIR/requirements.txt"
REQ_DEV="$BACKEND_DIR/requirements-dev.txt"
VENV_DIR="$BACKEND_DIR/.venv"
REQ_MARK="$VENV_DIR/.requirements-ok"     # 已安装依赖的指纹缓存
FRONTEND_LOCK="$FRONTEND_DIR/package-lock.json"

# 清理污染环境变量：部分嵌入式 Python（如本机 TRAE 工具链）会注入
# PYTHONPATH（混入他版本 site-packages）与 PYTHONHOME，导致解释器/venv 行为异常。
# 统一卸载，避免向后端进程泄漏。本机仅剩 python3.10 可用且其 venv 无法隔离，
# 故后端依赖统一装入其自身 site，`.venv` 仅作“运行入口 facade”（见后端段注释）。
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true
export -n PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true

# 默认开关
DO_INSTALL=1
DO_OPEN=1
FORCE=0
CHECK_ONLY=0

# 配色（仅允许 tty 时启用）
if [ -t 1 ]; then
  C_G="\033[32m"; C_Y="\033[33m"; C_R="\033[31m"; C_B="\033[36m"; C_0="\033[0m"
else
  C_G=""; C_Y=""; C_R=""; C_B=""; C_0=""
fi
ok()   { printf "${C_G}[ OK ]${C_0} %s\n" "$*"; }
warn() { printf "${C_Y}[WARN]${C_0} %s\n" "$*"; }
err()  { printf "${C_R}[FAIL]${C_0} %s\n" "$*" >&2; }
che()  { printf "${C_B}[CHK ]${C_0} %s\n" "$*"; }

print_help() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --check|--dry-run)    CHECK_ONLY=1 ;;
    --no-install)         DO_INSTALL=0 ;;
    --no-open|--no-browser) DO_OPEN=0 ;;
    --force)              FORCE=1 ;;
    -h|--help)            print_help ;;
    *) warn "未知参数: $1（使用 --help 查看用法）"; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# 1. 环境自检：定位 Node（与 restart.sh 同一套逻辑：优先 .node-path 的 22.x）
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  常青圈 一键启动"
echo "  工作目录: $ROOT"
echo "============================================================"

NODE_BIN=""
if command -v node >/dev/null 2>&1; then
  NODE_BIN="$(dirname "$(command -v node)")"
elif [ -f "$ROOT/.node-path" ]; then
  c="$(cat "$ROOT/.node-path")"
  [ -x "$c/node" ] && NODE_BIN="$c"
fi
if [ -n "$NODE_BIN" ]; then
  export PATH="$NODE_BIN:$PATH"
  if ! command -v npm >/dev/null 2>&1; then
    # .node-path 只有 node、没有 npm 时，回到系统 npm 但显式告警版本匹配风险
    warn "定位到 Node($NODE_BIN) 但缺少 npm，将使用系统 npm。"
  fi
fi
export PATH

echo ""
echo "==> 环境自检"
if command -v node >/dev/null 2>&1; then
  che "Node: $(command -v node)  v$(node -v 2>/dev/null | sed 's/v//')"
else
  err "未找到 Node/npm。前端无法启动。"
  warn "安装 Node ≥22（或创建项目根目录 .node-path 指向安装目录）后重试。"
  NODE_MISSING=1
fi
if command -v npm >/dev/null 2>&1; then
  che "npm:  v$(npm -v 2>/dev/null)"
fi
if command -v python3 >/dev/null 2>&1; then
  che "python3: $(command -v python3)  $(python3 -V 2>&1 | cut -d' ' -f2)"
else
  err "未找到 python3，后端无法启动。"
  NODE_MISSING=1
fi
# 端口占用提示（不强制拦截，restart.sh 会自行清理）
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn "端口 $port 已被占用，启动时将自动清理旧进程（如有本项目残留）。"
  fi
done
if [ "${NODE_MISSING:-0}" = "1" ]; then
  echo ""
  exit 1
fi
[ "$CHECK_ONLY" = "1" ] && { echo ""; ok "自检完成（--check 模式，未启动服务）。"; exit 0; }

# ---------------------------------------------------------------------------
# 2. 后端依赖准备（幂等：按 requirements*.txt 指纹缓存，未变化则跳过）
# ---------------------------------------------------------------------------
echo ""
echo "==> 后端依赖准备"
req_fingerprint() { cat "$REQ_FILE" "${REQ_DEV:-/dev/null}" 2>/dev/null | shasum | cut -d' ' -f1; }

# 校验一个 Python 解释器是否可用（能 import encodings 才算健康）
python_usable() { [ -x "$1" ] && "$1" -c "import encodings" >/dev/null 2>&1; }

# 挑选可用解释器：env 指定 → 系统默认 python3 → 常规 python3.x（逐一探测可用性）
pick_python() {
  local cand
  for cand in \
    "${PYTHON:-}" \
    "$(command -v python3 2>/dev/null)" \
    "$(command -v python3.12 2>/dev/null)" \
    "$(command -v python3.13 2>/dev/null)" \
    "$(command -v python3.11 2>/dev/null)"; do
    [ -n "$cand" ] && python_usable "$cand" && { echo "$cand"; return 0; }
  done
  return 1
}

# 运行入口是否可用（.venv/bin/python 存在且能运行）。
# 注意：本机异常 Python 环境下 venv 无法隔离，故 `.venv` 被用作“运行入口 facade”，
# 其 bin/python 符号链接到 pick_python 选中的真实解释器；`restart.sh` 仍用
# `.venv/bin/python -m uvicorn` 启动后端，因此无需改动 restart.sh。
run_python_ok() { [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c "import sys" >/dev/null 2>&1; }

# 建立/修复运行入口 facade（指向真实解释器，供 restart.sh 沿用）
ensure_facade() {
  if ! run_python_ok; then
    mkdir -p "$VENV_DIR/bin"
    ln -sf "$1" "$VENV_DIR/bin/python"
    ln -sf "$1" "$VENV_DIR/bin/python3"
    ln -sfn "$1" "$VENV_DIR/bin/python3.10" 2>/dev/null || true
    "$1" -V > "$VENV_DIR/.python-version" 2>/dev/null || true
    warn "已建立后端运行入口 ${VENV_DIR#${BACKEND_DIR}/}bin/python → $1"
  fi
}

# 临时目录：健康复查与安装排他锁都会用到
mkdir -p "$LOG_DIR"

# 选取后端解释器（无论是否安装都先确定；运行也依赖它）
PY="$(pick_python)"
if [ -z "$PY" ]; then
  err "未找到可用的 Python 解释器。请安装 Python ≥3.9 后重试。"
  exit 1
fi

if [ "$DO_INSTALL" = "1" ]; then
  needs_backend_install=1
  if run_python_ok && [ -f "$REQ_MARK" ] \
     && [ "$(cat "$REQ_MARK")" = "$(req_fingerprint)" ] && [ "$FORCE" = "0" ]; then
    needs_backend_install=0
  fi
  backend_install() {
    local pip_install
    pip_install() {
      if "$PY" -m pip install --quiet -r "$REQ_FILE"; then return 0; fi
      # PEP 668「externally-managed」环境（如 uv / 部分系统解释器）拒绝全局安装：
      # 交由用户承担风险，使用 --break-system-packages 兜底重试一次。
      warn "默认 pip 安装被拒（可能为 externally-managed 环境），尝试 --break-system-packages 重试……"
      "$PY" -m pip install --quiet --break-system-packages -r "$REQ_FILE"
    }
    if command -v flock >/dev/null 2>&1; then
      ( flock 9
        ensure_facade "$PY"
        pip_install ) 9>"$LOG_DIR/backend-install.lock" || return 1
    else
      ensure_facade "$PY"
      pip_install || return 1
    fi
    req_fingerprint > "$REQ_MARK"
  }
  if [ "$needs_backend_install" = "1" ]; then
    echo "  后端依赖有更新或未就绪（或解释器不可用），准备安装……"
    backend_pyver=""
    backend_pyver="$( "$PY" -V 2>&1 | awk '{print $2}' )"
    echo "  后端解释器: $PY  (${backend_pyver:-?})"
    ensure_facade "$PY"
    backend_install || { err "后端依赖安装失败。"; exit 1; }
    ok "后端依赖已就绪。"
  else
    echo "  后端依赖已就绪（指纹一致），跳过安装。"
    ensure_facade "$PY"
  fi
else
  if run_python_ok; then
    echo "  --no-install：沿用现有后端解释器与依赖。"
  else
    err "后端运行入口不可用（.venv/bin/python 无法运行）且 --no-install。请去掉 --no-install 重试。"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 3. 前端依赖准备（幂等：比对 lock 文件，未变化则跳过）
# ---------------------------------------------------------------------------
echo ""
echo "==> 前端依赖准备"
needs_frontend_install=1
if [ "$DO_INSTALL" = "1" ]; then
  if [ -d "$FRONTEND_DIR/node_modules" ] && [ -f "$FRONTEND_DIR/node_modules/.package-lock.json" ] \
     && [ "$FRONTEND_LOCK" -ot "$FRONTEND_DIR/node_modules/.package-lock.json" ] && [ "$FORCE" = "0" ]; then
    needs_frontend_install=0
  fi
  if [ "$needs_frontend_install" = "1" ]; then
    echo "  安装前端依赖 (npm install) ..."
    ( cd "$FRONTEND_DIR" && npm install ) || { err "前端依赖安装失败。"; exit 1; }
    ok "前端依赖已就绪。"
  else
    echo "  前端依赖已缓存（package-lock 未变），跳过安装。"
  fi
elif [ -d "$FRONTEND_DIR/node_modules" ]; then
  echo "  --no-install：沿用现有 node_modules（若依赖不全，前端 dev 可能异常）。"
else
  err "前端无 node_modules 且 --no-install，无法启动。请去掉 --no-install 重试。"
  exit 1
fi

# ---------------------------------------------------------------------------
# 4. 复用 restart.sh 完成真实启动（清理旧进程 → 后端 :8010 → 就绪检查 → 前端 :3400）
# ---------------------------------------------------------------------------
echo ""
if [ ! -f "$ROOT/restart.sh" ]; then
  err "缺少 restart.sh（负责进程管理），请确认项目文件完整。"
  exit 1
fi
echo "==> 复用 restart.sh 拉起前后端服务"
# restart.sh 内部 set -u 且用相对逻辑，直接委托；它的退出码用于决定是否开浏览器
"$ROOT/restart.sh"
rc=$?

# ---------------------------------------------------------------------------
# 5. 就绪兜底检查 + 自动打开浏览器
# ---------------------------------------------------------------------------
if [ "$rc" != "0" ]; then
  err "restart.sh 异常退出（rc=$rc），请查看上方日志：$LOG_DIR"
  exit "$rc"
fi

echo ""
echo "==> 健康复查（端口监听）"
frontend_up=0; backend_up=0
for _ in $(seq 1 15); do
  lsof -nP -iTCP:$FRONTEND_PORT -sTCP:LISTEN >/dev/null 2>&1 && frontend_up=1
  lsof -nP -iTCP:$BACKEND_PORT -sTCP:LISTEN >/dev/null 2>&1 && backend_up=1
  [ "$frontend_up" = "1" ] && [ "$backend_up" = "1" ] && break
  sleep 1
done

echo ""
echo "============================================================"
if [ "$backend_up" = "1" ]; then
  ok "后端已就绪   http://127.0.0.1:$BACKEND_PORT   (日志: $LOG_DIR/backend.log)"
else
  warn "后端端口 $BACKEND_PORT 未监听，请查看 $LOG_DIR/backend.log"
fi
if [ "$frontend_up" = "1" ]; then
  ok "前端已就绪   http://localhost:$FRONTEND_PORT   (日志: $LOG_DIR/frontend.log)"
else
  warn "前端端口 $FRONTEND_PORT 未监听，请查看 $LOG_DIR/frontend.log"
fi
echo "  关闭服务:    ./stop.sh"
echo "============================================================"

if [ "$DO_OPEN" = "1" ] && [ "$frontend_up" = "1" ]; then
  url="http://localhost:$FRONTEND_PORT"
  echo ""
  echo "==> 自动打开浏览器: $url"
  if command -v open >/dev/null 2>&1; then
    open "$url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1
  else
    warn "未找到可用的浏览器打开命令，请手动访问 $url"
  fi
elif [ "$DO_OPEN" = "0" ]; then
  echo ""
  echo "（--no-open：已跳过自动打开浏览器，请手动访问 http://localhost:$FRONTEND_PORT/）"
fi

echo ""
exit 0