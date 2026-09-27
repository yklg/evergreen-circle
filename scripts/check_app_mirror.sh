#!/usr/bin/env bash
# backend/app → api/app 部署镜像一致性校验（M1 起替代「交付时人工检查」）。
#
# 约定：api/app 是 backend/app 的可裁剪镜像——
#   - api/index.py 自带 serverless 入口，backend/app/main.py（本地 uvicorn 入口）不镜像；
#   - 运行时数据（*.db*、__pycache__）不属于代码真相源。
# 除上述白名单外任何差异 → 非零退出并列出差异文件。
#
# 用法：仓库根执行 `scripts/check_app_mirror.sh`；改完后端先 `cp` 同步再跑本脚本。
set -euo pipefail
cd "$(dirname "$0")/.."

# 比对对象必须先存在。缺了就是**没有可比对象**，此时打「✓ 一致」是假绿 ——
# 2026-09-26 实测：`diff` 的失败被 `|| true` 吞进命令替换，脚本先哭 `diff: api/app:
# No such file or directory`、再打「✓ 镜像一致」并 exit 0（`set -e`/`pipefail` 都救不回来，
# 因为退出码在 `||` 处已经被消化）。
if [[ ! -d api/app ]]; then
  echo "SKIP: api/app 不存在 —— backend→api 部署镜像约定已废（后端只有 backend/ 一份真相），本脚本无对象可比"
  exit 0
fi

OUT=$(diff -rq backend/app api/app \
  --exclude=__pycache__ \
  --exclude='*.db*' \
  --exclude='.git' |
  grep -v '^Only in backend/app: main.py$' || true)

if [[ -n "$OUT" ]]; then
  echo "✗ api/app 镜像与 backend/app 不一致："
  echo "$OUT"
  echo "同步示例：cp backend/app/core/<file>.py api/app/core/"
  exit 1
fi
echo "✓ api/app 与 backend/app 镜像一致（main.py 入口差异属预期）"
