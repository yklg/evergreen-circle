#!/usr/bin/env bash
# =============================================================================
# 常青圈 EvergreenCircle · 一键启动 —— 新设备从零建环境 → 拉起前后端 → 打开浏览器
#
# 定位：首次/新设备一条命令跑全流程；环境已就绪后再次运行，走指纹缓存秒级跳过安装。
# 职责划分：
#   start.sh   本脚本      —— 环境自检 + 依赖准备（venv / pip / npm）+ 配置准备（.env）+ 开浏览器
#   restart.sh 既有脚本    —— 进程清理 + 后台拉起 + 就绪检查（本脚本委托它启动，不重复实现）
#   stop.sh    既有脚本    —— 关闭服务
#
# 用法：
#   ./start.sh                一键启动（自检 → 按需安装 → 启动 → 自动打开浏览器）
#   ./start.sh --check        只做依赖自检与版本核查：不安装、不启动、不 open
#   ./start.sh --no-install   跳过依赖安装直接启动（依赖未就绪时明确报错）
#   ./start.sh --no-open      启动但不自动打开浏览器
#   ./start.sh --force        强制重新安装后端/前端依赖（即使看起来已就绪）
#   ./start.sh -h | --help    查看帮助
#
# 约定：端口单一真值源 = ./.dev-ports.env（与 restart.sh / stop.sh 共用），本脚本不写死端口。
# Python 解释器约束（为何拉起前要 unset PYTHONPATH 等）的完整说明单一出口在
# docs/DEPLOYMENT.md §1「本机 Python 解释器约束」；本脚本只执行，不重复解释。
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
# shellcheck source=.dev-ports.env
. "$ROOT/.dev-ports.env"
LOG_DIR="$ROOT/.run-logs"
REQ_FILE="$BACKEND_DIR/requirements.txt"
REQ_DEV="$BACKEND_DIR/requirements-dev.txt"
VENV_DIR="$BACKEND_DIR/.venv"
REQ_MARK="$VENV_DIR/.requirements-ok"   # 后端依赖指纹缓存（按内容比对，幂等）
ENV_FILE="$BACKEND_DIR/.env"
ENV_EXAMPLE="$BACKEND_DIR/.env.example"
FRONTEND_LOCK="$FRONTEND_DIR/package-lock.json"
FRONTEND_MARK="$FRONTEND_DIR/node_modules/.package-lock-ok"   # 前端依赖指纹缓存（同上，按内容比对）

# 环境清洁：部分工具链会向环境注入 PYTHONPATH / PYTHONHOME / PYTHONSTARTUP，
# 污染解释器与 venv 行为；统一卸载，避免泄漏进后端进程（理由见 DEPLOYMENT §1）。
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true
export -n PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true

DO_INSTALL=1
DO_OPEN=1
FORCE=0
CHECK_ONLY=0

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
  cat <<'EOF'
常青圈 EvergreenCircle · 一键启动（新设备从零建环境 → 拉起前后端 → 打开浏览器）

用法：
  ./start.sh                一键启动（自检 → 按需安装依赖 → 启动 → 自动打开浏览器）
  ./start.sh --check        只做依赖自检与版本核查：不安装、不启动、不 open
  ./start.sh --no-install   跳过依赖安装直接启动（依赖未就绪时明确报错）
  ./start.sh --no-open      启动但不自动打开浏览器
  ./start.sh --force        强制重新安装后端/前端依赖（即使看起来已就绪）
  ./start.sh -h | --help    查看帮助

端口真值源：./.dev-ports.env（当前后端 :8010 / 前端 :3400）；关闭服务：./stop.sh
EOF
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check|--dry-run)       CHECK_ONLY=1 ;;
    --no-install)            DO_INSTALL=0 ;;
    --no-open|--no-browser)  DO_OPEN=0 ;;
    --force)                 FORCE=1 ;;
    -h|--help)               print_help ;;
    *) warn "未知参数: $1（使用 --help 查看用法）"; exit 2 ;;
  esac
  shift
done

mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# 通用探测：Python 候选 / venv 可用性 / 依赖指纹
# ---------------------------------------------------------------------------
python_usable() {
  [ -n "${1:-}" ] && [ -x "$1" ] \
    && "$1" -c 'import encodings, sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}

# 候选解释器顺序：显式 $PYTHON → 3.12（CI 钉的版本，预编译轮子覆盖最稳）→ 3.13 / 3.11 / 3.10
# → python3 兜底（可能是最新版，个别依赖尚无轮子）。按 realpath 去重后逐个输出候选。
python_candidates() {
  local p rp seen=""
  for p in "${PYTHON:-}" \
           "$(command -v python3.12 2>/dev/null)" \
           "$(command -v python3.13 2>/dev/null)" \
           "$(command -v python3.11 2>/dev/null)" \
           "$(command -v python3.10 2>/dev/null)" \
           "$(command -v python3 2>/dev/null)"; do
    [ -n "$p" ] || continue
    python_usable "$p" || continue
    rp="$(cd "$(dirname "$p")" && pwd -P)/$(basename "$p")"
    case "$seen" in *"|$rp|"*) continue ;; esac
    seen="$seen|$rp|"
    printf '%s\n' "$p"
  done
}

run_python_ok() {
  [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c 'import encodings' >/dev/null 2>&1
}

# stdin → sha1 十六进制（macOS 默认 shasum，Linux 常只有 sha1sum）
sha1_of() {
  if command -v shasum >/dev/null 2>&1; then shasum; else sha1sum; fi | cut -d' ' -f1
}

req_fingerprint() {
  cat "$REQ_FILE" "${REQ_DEV:-/dev/null}" 2>/dev/null | sha1_of
}

frontend_lock_fingerprint() {
  cat "$FRONTEND_LOCK" 2>/dev/null | sha1_of
}

# pip 安装（先默认索引，尊重用户 pip.conf / PIP_INDEX_URL；失败后自动改走清华镜像重试一次）。
# 2026-10-11 实测：本机网络下 Python TLS 直连 pypi.org 全部失败（含 TRAE 基座解释器），
# 清华镜像可用 —— 新设备在同类网络里靠这一步自动兜底。
venv_pip_install() {
  local req="$1"
  if "$VENV_DIR/bin/python" -m pip install -r "$req"; then return 0; fi
  warn "默认 PyPI 索引安装失败，改用清华镜像重试……"
  "$VENV_DIR/bin/python" -m pip install -r "$req" -i https://pypi.tuna.tsinghua.edu.cn/simple
}

# ---------------------------------------------------------------------------
# 1. 环境自检（Node / Python / .env / 端口）
# ---------------------------------------------------------------------------
echo "============================================================"
echo "  常青圈 一键启动"
echo "  工作目录: $ROOT"
echo "============================================================"
echo ""
echo "==> 环境自检"

# Node：PATH 优先；PATH 里找不到时回退项目根 .node-path（机制见 docs/DEPLOYMENT.md §1）
NODE_BIN=""
if command -v node >/dev/null 2>&1; then
  NODE_BIN="$(dirname "$(command -v node)")"
elif [ -f "$ROOT/.node-path" ]; then
  c="$(cat "$ROOT/.node-path")"
  [ -x "$c/node" ] && NODE_BIN="$c"
fi
[ -n "$NODE_BIN" ] && export PATH="$NODE_BIN:$PATH"

RUNTIME_MISSING=0
if command -v node >/dev/null 2>&1; then
  che "Node: $(command -v node)  $(node -v 2>/dev/null)"
  node_major="$(node -v 2>/dev/null | sed 's/^v//; s/\..*//')"
  if [ -n "$node_major" ] && [ "$node_major" -lt 22 ] 2>/dev/null; then
    warn "Node 主版本低于 22（frontend/package.json engines 要求 22.x），vite 可能无法启动。"
  fi
else
  err "未找到 Node/npm，前端无法启动。"
  warn "请安装 Node ≥22；或在项目根创建 .node-path 文件写入 node 的 bin 目录绝对路径后重试。"
  RUNTIME_MISSING=1
fi
if command -v npm >/dev/null 2>&1; then
  che "npm:  $(npm -v 2>/dev/null)"
else
  err "未找到 npm，前端无法启动。"
  RUNTIME_MISSING=1
fi

PY_FIRST="$(python_candidates | head -n 1)"
if [ -n "$PY_FIRST" ]; then
  che "Python: $PY_FIRST  ($("$PY_FIRST" -V 2>&1))"
else
  err "未找到 ≥3.9 的可用 Python，后端无法启动。请安装 Python（建议 3.12）后重试。"
  RUNTIME_MISSING=1
fi

if run_python_ok; then
  che "backend/.venv: $("$VENV_DIR/bin/python" -V 2>&1)"
else
  warn "backend/.venv 不存在或不可用（启动时将自动创建）。"
fi
if [ -f "$ENV_FILE" ]; then
  che "backend/.env: 已存在"
else
  warn "backend/.env 缺失（启动时将自动从 .env.example 生成）。"
fi
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    warn "端口 $port 已被占用，启动时将自动清理旧进程（如有本项目残留）。"
  fi
done

if [ "$RUNTIME_MISSING" = "1" ]; then
  echo ""
  err "运行时缺失，无法继续。装好 Node ≥22 / Python ≥3.9 后重试（见 docs/DEPLOYMENT.md §1）。"
  exit 1
fi

if [ "$CHECK_ONLY" = "1" ]; then
  echo ""
  echo "==> 依赖状态（--check 只报告，不安装）"
  if run_python_ok; then
    if [ -f "$REQ_MARK" ] && [ "$(cat "$REQ_MARK")" = "$(req_fingerprint)" ]; then
      che "后端依赖：已就绪（指纹一致）"
    else
      che "后端依赖：需校验/更新（指纹不一致，启动时会 pip install）"
    fi
  else
    che "后端依赖：未建（启动时会自动创建 backend/.venv 并安装）"
  fi
  if [ -d "$FRONTEND_DIR/node_modules" ] && [ -f "$FRONTEND_MARK" ] \
     && [ "$(cat "$FRONTEND_MARK")" = "$(frontend_lock_fingerprint)" ]; then
    che "前端依赖：已就绪（lock 指纹一致）"
  else
    che "前端依赖：需安装/刷新（启动时会 npm install）"
  fi
  echo ""
  ok "自检完成（--check 模式：未安装、未启动、未打开浏览器）。"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2. 配置准备：backend/.env（仅缺失时由模板生成，绝不覆盖已有文件）
# ---------------------------------------------------------------------------
echo ""
echo "==> 配置准备"
if [ -f "$ENV_FILE" ]; then
  echo "  backend/.env 已存在，保持不动。"
elif [ -f "$ENV_EXAMPLE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  warn "已从模板生成 backend/.env。密钥留空时自动走演示/降级模式可直接体验；"
  warn "启用真实 LLM / 地图能力请在 backend/.env 填入 LLM_API_KEY / BOCHA_API_KEY / BAIDU_* （见 README）。"
else
  warn "backend/.env 缺失且未找到 .env.example，将按代码内建默认启动。"
fi

# ---------------------------------------------------------------------------
# 3. 后端依赖准备（幂等：指纹一致且非 --force 则跳过）
# ---------------------------------------------------------------------------
echo ""
echo "==> 后端依赖准备"

ensure_backend_deps() {
  local py
  if [ "$DO_INSTALL" = "0" ]; then
    if run_python_ok; then
      echo "  --no-install：沿用现有 .venv 与依赖（不做校验安装）。"
      return 0
    fi
    err "后端 .venv 不可用且指定了 --no-install。去掉 --no-install 重试。"
    exit 1
  fi
  if run_python_ok; then
    if [ "$FORCE" = "0" ] && [ -f "$REQ_MARK" ] && [ "$(cat "$REQ_MARK")" = "$(req_fingerprint)" ]; then
      ok "后端依赖已就绪（指纹一致，跳过安装）。"
      return 0
    fi
    echo "  后端依赖需校验/更新（fingerprint 不一致或 --force），开始 pip install ..."
    if venv_pip_install "$REQ_FILE"; then
      venv_pip_install "$REQ_DEV" || warn "requirements-dev.txt 安装失败（仅影响测试，不阻断启动）。"
      req_fingerprint > "$REQ_MARK"
      ok "后端依赖已就绪。"
      return 0
    fi
    warn "pip 安装失败（上方为 pip 输出），沿用现有 .venv 继续启动。"
    warn "网络恢复后可重跑 ./start.sh --force 重装依赖。"
    return 0
  fi
  echo "  后端 .venv 不存在或不可用，开始从零建环境（建 venv + 装依赖）..."
  while IFS= read -r py; do
    echo "  尝试解释器: $py  ($("$py" -V 2>&1))"
    if "$py" -m venv "$VENV_DIR" && venv_pip_install "$REQ_FILE"; then
      venv_pip_install "$REQ_DEV" || warn "requirements-dev.txt 安装失败（仅影响测试，不阻断启动）。"
      req_fingerprint > "$REQ_MARK"
      ok "后端环境已建好：backend/.venv（$("$VENV_DIR/bin/python" -V 2>&1)）"
      return 0
    fi
    warn "该解释器建环境失败，换下一个候选重试……"
  done < <(python_candidates)
  err "未能建起后端环境。请安装 Python ≥3.9（建议 3.12）后重试；"
  err "或手动：cd backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
}

ensure_backend_deps

# ---------------------------------------------------------------------------
# 4. 前端依赖准备（幂等：lock 内容指纹一致则跳过）
#    不用时间戳比较 —— git clone 会把所有文件 mtime 刷成同一刻，`-ot` 会永远
#    判「需刷新」；内容指纹同时还管住 package-lock 的更新。
# ---------------------------------------------------------------------------
echo ""
echo "==> 前端依赖准备"
if [ "$DO_INSTALL" = "0" ]; then
  if [ -d "$FRONTEND_DIR/node_modules" ]; then
    echo "  --no-install：沿用现有 node_modules。"
  else
    err "前端 node_modules 缺失且指定了 --no-install。去掉 --no-install 重试。"
    exit 1
  fi
else
  need_frontend_install=1
  if [ -d "$FRONTEND_DIR/node_modules" ] && [ -f "$FRONTEND_MARK" ] \
     && [ "$(cat "$FRONTEND_MARK")" = "$(frontend_lock_fingerprint)" ] && [ "$FORCE" = "0" ]; then
    need_frontend_install=0
  fi
  if [ "$need_frontend_install" = "1" ]; then
    # tarball 地址已固定进 package-lock.json（npmmirror），新设备无需额外镜像配置。
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
      echo "  安装前端依赖（首次约 1–2 分钟）..."
      ( cd "$FRONTEND_DIR" && npm install ) || { err "前端依赖安装失败（上方为 npm 输出）。"; exit 1; }
      frontend_lock_fingerprint > "$FRONTEND_MARK"
      ok "前端依赖已就绪。"
    else
      echo "  前端依赖需刷新（package-lock 有更新或 --force）..."
      if ( cd "$FRONTEND_DIR" && npm install ); then
        frontend_lock_fingerprint > "$FRONTEND_MARK"
        ok "前端依赖已就绪。"
      else
        warn "npm install 失败，沿用现有 node_modules 继续启动。"
      fi
    fi
  else
    ok "前端依赖已缓存（lock 指纹一致，跳过安装）。"
  fi
fi

# ---------------------------------------------------------------------------
# 5. 拉起前后端（复用 restart.sh：清旧进程 → 后端 → 等就绪 → 前端）
# ---------------------------------------------------------------------------
echo ""
if [ ! -f "$ROOT/restart.sh" ]; then
  err "缺少 restart.sh（负责进程管理），请确认项目文件完整。"
  exit 1
fi
echo "==> 拉起前后端服务（复用 restart.sh）"
bash "$ROOT/restart.sh"
rc=$?
if [ "$rc" != "0" ]; then
  err "restart.sh 异常退出（rc=$rc），请查看上方输出与 $LOG_DIR 下的日志。"
  exit "$rc"
fi

# ---------------------------------------------------------------------------
# 6. 健康复查 + 自动打开浏览器
# ---------------------------------------------------------------------------
echo ""
echo "==> 健康复查（端口监听）"
frontend_up=0; backend_up=0
for _ in $(seq 1 15); do
  lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1 && frontend_up=1
  lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1 && backend_up=1
  [ "$frontend_up" = "1" ] && [ "$backend_up" = "1" ] && break
  sleep 1
done
[ "$backend_up" = "1" ] && ok "后端已就绪   http://127.0.0.1:$BACKEND_PORT   (日志: $LOG_DIR/backend.log)" \
                        || warn "后端端口 $BACKEND_PORT 未监听，请查看 $LOG_DIR/backend.log"
[ "$frontend_up" = "1" ] && ok "前端已就绪   http://localhost:$FRONTEND_PORT   (日志: $LOG_DIR/frontend.log)" \
                         || warn "前端端口 $FRONTEND_PORT 未监听，请查看 $LOG_DIR/frontend.log"

echo ""
echo "============================================================"
echo "  OK - 启动完成"
echo "  预览地址:  http://localhost:$FRONTEND_PORT/"
echo "  后端接口:  http://127.0.0.1:$BACKEND_PORT/  (健康检查 /health)"
echo "  关闭服务:  ./stop.sh"
echo "  日志目录:  $LOG_DIR/"
echo "============================================================"

if [ "$DO_OPEN" = "1" ]; then
  if [ "$frontend_up" = "1" ]; then
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
  else
    warn "前端未就绪，跳过自动打开浏览器；就绪后请手动访问 http://localhost:$FRONTEND_PORT/"
  fi
else
  echo ""
  echo "（--no-open：未自动打开浏览器，请手动访问 http://localhost:$FRONTEND_PORT/）"
fi

echo ""
exit 0
