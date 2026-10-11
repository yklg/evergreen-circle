#!/usr/bin/env bash
# =============================================================================
# 常青圈 EvergreenCircle · 一键演示模式（无 Key 环境快速展示）
#
# 用途：评审方或新用户在没有百度 AK / LLM API Key 的情况下，快速启动项目并
#      使用内置 fixture 数据演示完整功能链路。
#
# 特性：
#   - 自动检测依赖并提示安装（不强制安装，避免破坏现有环境）
#   - 强制使用 fixture 数据模式（VITE_LC_DATA_MODE=fixture）
#   - 禁用所有外部 API 调用（LLM/百度地图），确保零网络依赖
#   - 自动打开浏览器到工作台首页
#   - 提供清晰的演示路径指引（凯里老街 → 北京劲松 → 对比页）
#
# 用法：
#   ./scripts/run-demo.sh              # 启动演示模式
#   ./scripts/run-demo.sh --check      # 仅检查依赖，不启动
#   ./scripts/run-demo.sh -h           # 查看帮助
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
LOG_DIR="$ROOT/.run-logs"
DEMO_LOG="$LOG_DIR/demo-$(date +%Y%m%d-%H%M%S).log"

# 颜色输出
if [ -t 1 ]; then
  C_G="\033[32m"; C_Y="\033[33m"; C_R="\033[31m"; C_B="\033[36m"; C_0="\033[0m"
else
  C_G=""; C_Y=""; C_R=""; C_B=""; C_0=""
fi
ok()   { printf "${C_G}[ OK ]${C_0} %s\n" "$*"; }
warn() { printf "${C_Y}[WARN]${C_0} %s\n" "$*"; }
err()  { printf "${C_R}[FAIL]${C_0} %s\n" "$*" >&2; }
info() { printf "${C_B}[INFO]${C_0} %s\n" "$*"; }

print_help() {
  cat <<'EOF'
常青圈 EvergreenCircle · 一键演示模式

用途：在无百度 AK / LLM API Key 环境下，使用内置 fixture 数据快速演示完整功能

用法：
  ./scripts/run-demo.sh              启动演示模式（自动打开浏览器）
  ./scripts/run-demo.sh --check      仅检查依赖，不启动服务
  ./scripts/run-demo.sh -h           查看帮助

演示内容：
  1. 工作台：选择凯里老街 / 北京劲松样例社区
  2. 体检地图：查看 5/10/15/20min 等时圈 + POI 分布 + 服务盲区
  3. 报告页：阅读体检单 + 分章报告（医疗/教育/养老/商业）
  4. 对比页：双社区指标对比 + 雷达图叠加
  5. 历史页：查看历次体检记录

注意：此模式下所有数据为内置快照，不调用任何外部 API（百度/智谱等）
EOF
  exit 0
}

CHECK_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    -h|--help)         print_help ;;
    *)                 err "未知参数: $1"; exit 2 ;;
  esac
  shift
done

mkdir -p "$LOG_DIR"

echo "============================================================"
echo "  常青圈 EvergreenCircle · 演示模式"
echo "  工作目录: $ROOT"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# 1. 依赖检查
# ---------------------------------------------------------------------------
info "检查运行依赖..."

MISSING_DEPS=0

# Node.js
if command -v node >/dev/null 2>&1; then
  node_ver="$(node -v 2>/dev/null || echo 'unknown')"
  ok "Node.js: $node_ver"
else
  err "未找到 Node.js（需要 ≥22）"
  warn "请先安装 Node.js: https://nodejs.org/"
  MISSING_DEPS=1
fi

# npm
if command -v npm >/dev/null 2>&1; then
  ok "npm: $(npm -v 2>/dev/null)"
else
  err "未找到 npm"
  MISSING_DEPS=1
fi

# Python 3
if command -v python3 >/dev/null 2>&1; then
  py_ver="$(python3 --version 2>/dev/null | awk '{print $2}')"
  ok "Python 3: $py_ver"
else
  err "未找到 Python 3（需要 ≥3.9）"
  warn "请先安装 Python 3"
  MISSING_DEPS=1
fi

# 前端依赖
if [ -d "$FRONTEND_DIR/node_modules" ]; then
  ok "前端依赖已安装"
else
  warn "前端依赖未安装，运行: cd frontend && npm install"
  MISSING_DEPS=1
fi

# 后端依赖（检查 venv）
if [ -d "$BACKEND_DIR/.venv" ] && [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  ok "后端虚拟环境已创建"
else
  warn "后端虚拟环境未创建，运行: cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  MISSING_DEPS=1
fi

if [ "$MISSING_DEPS" -eq 1 ]; then
  echo ""
  err "部分依赖缺失，无法启动演示模式"
  warn "请先按上述提示安装缺失的依赖后重试"
  exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo ""
  ok "所有依赖检查通过！可以启动演示模式"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2. 准备演示环境变量
# ---------------------------------------------------------------------------
echo ""
info "配置演示模式环境变量..."

# 读取端口配置
if [ -f "$ROOT/.dev-ports.env" ]; then
  # shellcheck source=.dev-ports.env
  . "$ROOT/.dev-ports.env"
else
  BACKEND_PORT="${BACKEND_PORT:-8010}"
  FRONTEND_PORT="${FRONTEND_PORT:-3400}"
fi

# 设置演示模式专属环境变量（覆盖 .env 中的值）
export VITE_LC_DATA_MODE="fixture"       # 强制使用 fixture 数据
export VITE_USE_MOCK="1"                  # 前端 mock 模式
export ENABLE_DEMO_FALLBACK="true"        # 启用降级兜底
export BAIDU_SERVER_AK=""                 # 清空百度 AK（触发降级）
export BAIDU_BROWSER_AK=""                # 清空百度 AK
export LLM_API_KEY=""                     # 清空 LLM Key（触发模板机填）

ok "演示模式已配置："
info "  - 数据来源: 内置 fixture 快照（凯里老街 / 北京劲松）"
info "  - 外部 API: 全部禁用（零网络依赖）"
info "  - AI 解读: 使用规则模板（非真实 LLM）"

# ---------------------------------------------------------------------------
# 3. 停止已有服务（避免端口冲突）
# ---------------------------------------------------------------------------
echo ""
info "清理已有服务..."
if [ -f "$ROOT/stop.sh" ]; then
  bash "$ROOT/stop.sh" >/dev/null 2>&1 || true
  sleep 1
fi

# ---------------------------------------------------------------------------
# 4. 启动后端
# ---------------------------------------------------------------------------
echo ""
info "启动后端服务（端口 $BACKEND_PORT）..."

mkdir -p "$LOG_DIR"
BACKEND_LOG="$LOG_DIR/backend-demo.log"

# 激活虚拟环境并启动
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate 2>/dev/null || true
  unset PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true
  export -n PYTHONPATH PYTHONHOME PYTHONSTARTUP 2>/dev/null || true
  
  # 注入演示环境变量到后端进程
  export VITE_LC_DATA_MODE="$VITE_LC_DATA_MODE"
  export ENABLE_DEMO_FALLBACK="$ENABLE_DEMO_FALLBACK"
  export BAIDU_SERVER_AK=""
  export BAIDU_BROWSER_AK=""
  export LLM_API_KEY=""
  
  exec python -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port "$BACKEND_PORT" \
    --reload 2>&1
) > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# 等待后端就绪
info "等待后端就绪..."
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:${BACKEND_PORT}/" >/dev/null 2>&1; then
    ok "后端已就绪 (PID: $BACKEND_PID)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    err "后端启动超时（30秒）"
    warn "查看日志: tail -f $BACKEND_LOG"
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

# ---------------------------------------------------------------------------
# 5. 启动前端
# ---------------------------------------------------------------------------
echo ""
info "启动前端服务（端口 $FRONTEND_PORT）..."

FRONTEND_LOG="$LOG_DIR/frontend-demo.log"

(
  cd "$FRONTEND_DIR"
  # 注入演示环境变量到前端构建/开发服务器
  export VITE_LC_DATA_MODE="$VITE_LC_DATA_MODE"
  export VITE_USE_MOCK="$VITE_USE_MOCK"
  export VITE_API_BASE="http://127.0.0.1:${BACKEND_PORT}"
  
  exec npm run dev -- --port "$FRONTEND_PORT" --host 127.0.0.1 2>&1
) > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# 等待前端就绪
info "等待前端就绪..."
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
    ok "前端已就绪 (PID: $FRONTEND_PID)"
    break
  fi
  if [ "$i" -eq 30 ]; then
    err "前端启动超时（30秒）"
    warn "查看日志: tail -f $FRONTEND_LOG"
    kill "$FRONTEND_PID" 2>/dev/null || true
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

# ---------------------------------------------------------------------------
# 6. 打开浏览器 + 打印演示指引
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  ✅ 演示模式已启动！"
echo "============================================================"
echo ""
info "访问地址: http://127.0.0.1:${FRONTEND_PORT}"
echo ""

# 尝试自动打开浏览器
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:${FRONTEND_PORT}" 2>/dev/null || true
fi

echo ""
info "═══════════════════════════════════════════════════════════"
info "  推荐演示路径（评审方必看）"
info "═══════════════════════════════════════════════════════════"
echo ""
echo "  1️⃣  工作台（首页）"
echo "      → 点击「凯里老街」或「北京劲松」示例卡"
echo "      → 观察三档体检模式（速览/标准/精细）"
echo ""
echo "  2️⃣  体检地图页"
echo "      → 查看 5/10/15/20min 四级等时圈（彩色多边形）"
echo "      → 观察 POI 分布（医疗/教育/养老/商业分色标注）"
echo "      → 识别服务盲区（灰色区域 = 1km 内无菜市场/药店/小学）"
echo "      → 拖动中心点，体验新旧对比"
echo ""
echo "  3️⃣  报告页"
echo "      → 顶层体检单：总评分 + 雷达图 + 三要素结论"
echo "      → 下层章节：医疗/教育/养老/商业逐章诊断"
echo "      → 亮点卡：每章首部的关键读数要点"
echo ""
echo "  4️⃣  对比页（导航栏「对比」）"
echo "      → 双社区同图叠加（凯里 vs 北京劲松）"
echo "      → 指标对比表 + 双雷达图"
echo "      → 切换三态：同比例尺 / 同中心 / 叠加"
echo ""
echo "  5️⃣  历史页（导航栏「历史」）"
echo "      → 查看历次体检记录列表"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
warn "⚠️  当前为演示模式，所有数据为内置快照（data_origin='fixture'）"
warn "    横幅会标注「内置快照」，不调用任何外部 API"
echo ""
info "停止服务: ./stop.sh"
info "查看日志: tail -f $BACKEND_LOG  或  tail -f $FRONTEND_LOG"
echo ""
info "后台进程: 后端 PID=$BACKEND_PID, 前端 PID=$FRONTEND_PID"
info "退出终端不会停止服务；请使用 ./stop.sh 关闭"
echo ""

# 保存 PID 文件供 stop.sh 使用
echo "$BACKEND_PID" > "$ROOT/.run-logs/backend.pid"
echo "$FRONTEND_PID" > "$ROOT/.run-logs/frontend.pid"

exit 0
