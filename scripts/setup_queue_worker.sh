#!/bin/sh
# 安装队列 worker 的 systemd 服务（幂等）。
#
# 用法：
#   scripts/setup_queue_worker.sh            # 装预览环境（8771 那一套）
#   scripts/setup_queue_worker.sh --prod     # 装正式环境（8770 那一套）
#
# 注意：正式环境的代码目录名会随 release 变化，ReadWritePaths 必须跟着改，
# 否则服务能起但写不了 output，worker 会在第一笔任务上失败。
set -eu

PROD=0
[ "${1:-}" = "--prod" ] && PROD=1

if [ "$PROD" = "1" ]; then
  APP=${APP:-/opt/shilie/current}
  UNIT=shilie-queue-worker.service
  ENV_FILE=${ENV_FILE:-/etc/shilie/workspace.env}
  PYTHON=${PYTHON:-$APP/.venv/bin/python}
  USER_NAME=${USER_NAME:-shilie}
  GROUP_NAME=${GROUP_NAME:-shilie}
else
  APP=${APP:-/var/lib/shilie-preview/app}
  UNIT=shilie-preview-queue-worker.service
  ENV_FILE=${ENV_FILE:-/etc/shilie-preview/workspace.env}
  PYTHON=${PYTHON:-$APP/.venv312/bin/python}
  USER_NAME=${USER_NAME:-shilie_pvapp}
  GROUP_NAME=${GROUP_NAME:-shilie_pvapp}
fi

TPL="$APP/scripts/shilie-queue-worker.service.tpl"
UNIT_PATH=/etc/systemd/system/$UNIT

echo "== 1/4 检查依赖 =="
for f in "$APP/scripts/queue_worker.py" "$TPL" "$ENV_FILE"; do
  [ -e "$f" ] || { echo "缺少：$f"; exit 1; }
done
[ -x "$PYTHON" ] || { echo "Python 不可执行：$PYTHON"; exit 1; }
echo "应用目录：$APP"

echo "== 2/4 渲染单元 =="
sed -e "s|__APP__|$APP|g" \
    -e "s|__ENV_FILE__|$ENV_FILE|g" \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__USER__|$USER_NAME|g" \
    -e "s|__GROUP__|$GROUP_NAME|g" \
    -e "s|__OPT_SHILIE__|/opt/shilie|g" \
    "$TPL" > "$UNIT_PATH"
echo "写入：$UNIT_PATH"

echo "== 3/4 启用 =="
systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1 || true
systemctl restart "$UNIT" || { echo "启动失败，日志："; journalctl -u "$UNIT" -n 30 --no-pager; exit 1; }

echo "== 4/4 自检 =="
sleep 2
systemctl is-active "$UNIT"
systemctl show "$UNIT" -p MainPID --value
echo "查看日志：journalctl -u $UNIT -f"
