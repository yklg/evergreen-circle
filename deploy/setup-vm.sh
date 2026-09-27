#!/usr/bin/env bash
# 常青圈 EvergreenCircle Worker — 自管云主机一键引导（仅本地/手动执行，不自动跑真机）
#
# 用途：在 Debian/Ubuntu 系云主机（如阿里云 ECS 47.114.101.59）上装 docker、
#       部署 worker、挂 Nginx、注册 systemd 自启。
#
# ⚠️ 执行前须知（务必读）：
#   1. 本脚本会改系统（装包、写 systemd、改 Nginx）——请在你自己的主机上、确认无误后执行。
#   2. 真实密钥与域名在交互提示中填入，脚本绝不硬编码任何密钥。
#   3. 本脚本不连 Vercel、不 push 代码、不触碰本地开发环境。
#   4. 默认把仓库放到 /opt/verda；若路径不同，请改下方 REPO_DIR 或先把仓库放到该处。
set -euo pipefail

REPO_DIR="${VERDA_REPO_DIR:-/opt/verda}"
DOMAIN="${VERDA_DOMAIN:-verda.example.com}"

echo "==> [1/6] 安装 docker（若已装则跳过）"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker 安装失败，请手动安装后重试" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose 插件缺失，请安装 docker-compose-plugin" >&2
  exit 1
fi

echo "==> [2/6] 校验代码位置 $REPO_DIR"
if [ ! -d "$REPO_DIR/deploy" ]; then
  echo "未找到 $REPO_DIR/deploy。请先把仓库 clone/拷贝到 $REPO_DIR，"
  echo "或修改本脚本顶部 VERDA_REPO_DIR，再重新执行。" >&2
  exit 1
fi

echo "==> [3/6] 准备 .env（密钥交互填入，不落盘到镜像）"
ENV_FILE="$REPO_DIR/deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO_DIR/deploy/.env.worker.example" "$ENV_FILE"
  echo "已生成 $ENV_FILE。"
  echo "请现在用编辑器填入 LLM_API_KEY / BOCHA_API_KEY 等真实值，"
  echo "保存后按回车继续（或 Ctrl-C 中止，填完再跑本脚本）。"
  read -r _ </dev/tty
fi
if [ ! -s "$ENV_FILE" ] || grep -q "your_llm_api_key_here" "$ENV_FILE"; then
  echo "检测到 .env 仍是模板占位符，请先填入真实密钥再继续。" >&2
  exit 1
fi

echo "==> [4/6] 构建并启动 worker（compose：workers=1，卷 /data）"
cd "$REPO_DIR/deploy"
docker compose build
docker compose up -d

echo "==> [5/6] 注册 systemd 自启"
cp "$REPO_DIR/deploy/systemd/verda-worker.service" /etc/systemd/system/verda-worker.service
systemctl daemon-reload
systemctl enable --now verda-worker

echo "==> [6/6] 接入 Nginx（请确认域名与证书）"
NGINX_CONF="/etc/nginx/conf.d/verda.conf"
if [ -d /etc/nginx/conf.d ]; then
  cp "$REPO_DIR/deploy/nginx/verda.conf" "$NGINX_CONF"
  sed -i "s/verda.example.com/$DOMAIN/g" "$NGINX_CONF"
  if nginx -t 2>/dev/null; then
    systemctl reload nginx
    echo "Nginx 已接入：curl -i http://$DOMAIN/health 应返回 {\"status\":\"ok\",...}"
  else
    echo "nginx -t 失败，请检查 $NGINX_CONF（域名/证书）后手动 reload nginx" >&2
  fi
else
  echo "未检测到 /etc/nginx/conf.d，跳过 Nginx（你可手动 include deploy/nginx/verda.conf）" >&2
fi

echo "==> 完成。worker 监听 127.0.0.1:8000，由 Nginx 反代对外。"
echo "==> 健康检查：curl -i http://127.0.0.1:8000/health"
echo "==> 查看日志：docker compose -f $REPO_DIR/deploy/docker-compose.yml logs -f"
