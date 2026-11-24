#!/bin/sh
# opencode 服务的启停：交给 systemd 管生命周期，循环只当客户端。
#
# 为什么不用 python 直接 spawn：实测从脚本里起的实例手工正常、从进程内起的反复起不来；
# 把进程生命周期交给 init 是正确分层，也顺手解决崩溃重启、日志、孤儿进程。
#
# 用法：
#   opencode_supervisor.sh start <目录> <端口> <HOME> <二进制路径>
#   opencode_supervisor.sh stop  <目录>
#   opencode_supervisor.sh status <目录>
set -u

action=${1:-}
target=${2:-}
shift 2 2>/dev/null || true

if [ -z "$action" ] || [ -z "$target" ]; then
  echo "用法：$0 start|stop|status <目录> [端口] [HOME] [二进制]" >&2
  exit 2
fi

# 单元名用目录哈希，保证同一目录复用、不同目录不打架。
unit="opencode-$(printf '%s' "$target" | md5sum | cut -c1-12)"

case "$action" in
  start)
    port=${1:-4096}
    home=${2:-/root}
    binary=${3:-/opt/shilie/opencode/opencode}
    systemctl stop "$unit.service" >/dev/null 2>&1 || true
    systemd-run --unit="$unit" --collect \
      --working-directory="$target" \
      --setenv=HOME="$home" \
      --property=RuntimeMaxSec=3600 \
      --property=Restart=no \
      "$binary" serve --hostname 127.0.0.1 --port "$port" >/dev/null
    echo "$unit"
    ;;
  stop)
    systemctl stop "$unit.service" >/dev/null 2>&1 || true
    systemctl reset-failed "$unit.service" >/dev/null 2>&1 || true
    echo "$unit"
    ;;
  status)
    systemctl is-active "$unit.service" 2>/dev/null || true
    echo "$unit"
    ;;
  *)
    echo "未知动作：$action" >&2
    exit 2
    ;;
esac
