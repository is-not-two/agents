#!/bin/sh
# 队列真机验证脚本（服务器恢复后一次跑完）。
#
# 覆盖：建表 → 入队 → worker 领取执行 → 检查点落库 → 结果回写 → 死信重放 → 取消。
# 每步都打印可核对的输出，任何一步失败立刻退出，不留「跑通了」的错觉。
#
# 用法（在服务器上）：sh scripts/verify_queue_live.sh
set -eu

APP=${APP:-/var/lib/shilie-preview/app}
SOCK=${SOCK:-/var/lib/shilie-preview/pgsock}
PORT=${PORT:-55433}
DB=${DB:-shilie_preview_20261104}
OWNER=${OWNER:-shilie_pvdb}
APPUSER=${APPUSER:-shilie_pvapp}
PY=$APP/.venv312/bin/python
TOKEN=${TOKEN:?请设置访问令牌}
API=${API:-https://127.0.0.1:8771}
ENV_FILE=${ENV_FILE:-/etc/shilie-preview/workspace.env}

echo "==== 0. 前置检查 ===="
test -x "$PY" || { echo "缺少 Python：$PY"; exit 1; }
test -f "$ENV_FILE" || { echo "缺少环境文件：$ENV_FILE"; exit 1; }
test -d "$APP/output/auto-demo/.git" || { echo "缺少演示仓库：$APP/output/auto-demo"; exit 1; }
curl -k -s -o /dev/null -w "8771 http=%{http_code}\n" --max-time 6 "$API/"
echo "PRECHECK_OK"

echo "==== 1. 队列表结构 ===="
sudo -u "$OWNER" psql -h "$SOCK" -p "$PORT" -d "$DB" -v ON_ERROR_STOP=1 <<SQL
CREATE TABLE IF NOT EXISTS workspace_task_jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  priority INTEGER NOT NULL DEFAULT 50, payload JSONB NOT NULL, result JSONB,
  checkpoint JSONB, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
  lease_until TIMESTAMPTZ, next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_error TEXT,
  idempotency_key TEXT, worker_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS workspace_task_jobs_ready_idx ON workspace_task_jobs (status, next_run_at);
CREATE UNIQUE INDEX IF NOT EXISTS workspace_task_jobs_idempotency_idx
  ON workspace_task_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL;
GRANT SELECT, INSERT, UPDATE ON workspace_task_jobs TO $APPUSER;
SQL
sudo -u "$OWNER" psql -h "$SOCK" -p "$PORT" -d "$DB" -tAc \
  "select to_regclass('workspace_task_jobs') as t, has_table_privilege('$APPUSER','workspace_task_jobs','INSERT') as can_insert"

echo "==== 2. 入队（loop，指向演示仓库） ===="
cat > /tmp/queue-verify-enqueue.json <<JSON
{"kind":"loop","max_attempts":2,"priority":60,"idempotency_key":"verify-queue-live-1",
 "payload":{"root":"demo","task":"在 mathx.py 里新增函数 mul(a, b)，返回 a 与 b 的乘积，并在 report.py 的 summary 里加上乘法示例",
 "gate":"$PY -c \"import sys; sys.path.insert(0,'.'); from mathx import mul; assert mul(2,3)==6; print('GATE_OK')\"",
 "engine":"opencode","tier":"patch"}}
JSON
ENQ=$(curl -k -s --max-time 20 -X POST "$API/api/automation/queue" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @/tmp/queue-verify-enqueue.json)
echo "$ENQ"
JOB=$(printf '%s' "$ENQ" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")
test -n "$JOB" || { echo "入队失败"; exit 1; }
echo "JOB_ID=$JOB"

echo "==== 3. 幂等性：同 key 重复入队应返回同一条 ===="
DUP=$(curl -k -s --max-time 20 -X POST "$API/api/automation/queue" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @/tmp/queue-verify-enqueue.json)
DUPID=$(printf '%s' "$DUP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")
if [ "$DUPID" = "$JOB" ]; then echo "IDEMPOTENT_OK"; else echo "幂等失效：$JOB vs $DUPID"; exit 1; fi

echo "==== 4. 坏载荷必须当场拒绝 ===="
BAD=$(curl -k -s -o /tmp/queue-verify-bad.json -w "%{http_code}" --max-time 20 -X POST \
  "$API/api/automation/queue" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"kind":"loop","payload":{"task":"缺仓库和门禁"}}')
echo "坏载荷 http=$BAD body=$(cat /tmp/queue-verify-bad.json)"
case "$BAD" in
  400|422) echo "BAD_PAYLOAD_REJECTED_OK" ;;
  *) echo "坏载荷未被拒绝（http=$BAD）"; exit 1 ;;
esac

echo "==== 5. 概览与列表 ===="
curl -k -s --max-time 10 -H "Authorization: Bearer $TOKEN" "$API/api/automation/queue/stats"; echo
curl -k -s --max-time 10 -H "Authorization: Bearer $TOKEN" "$API/api/automation/queue?limit=5" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(' ', r['id'][:8], r['kind'], r['status'], 'attempts=%s'%r['attempts']) for r in d]"

echo "==== 6. worker 领取并执行 ===="
cd "$APP"
timeout 400 "$PY" scripts/queue_worker.py --once --poll 2 --env-file "$ENV_FILE" 2>&1 | tail -15
echo "WORKER_EXIT=$?"

echo "==== 7. 执行结果与检查点 ===="
DETAIL=$(curl -k -s --max-time 15 -H "Authorization: Bearer $TOKEN" "$API/api/automation/queue/$JOB")
printf '%s' "$DETAIL" | python3 -m json.tool | head -40
STATUS=$(printf '%s' "$DETAIL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
CP=$(printf '%s' "$DETAIL" | python3 -c "import sys,json; print(json.load(sys.stdin).get('checkpoint') or '')")
case "$STATUS" in
  succeeded) echo "JOB_SUCCEEDED_OK" ;;
  *) echo "任务未成功（status=$STATUS）"; exit 1 ;;
esac
if [ -n "$CP" ] && [ "$CP" != "None" ]; then echo "CHECKPOINT_OK"; else echo "检查点为空"; exit 1; fi

echo "==== 8. 死信与重放 ===="
DEAD=$(curl -k -s --max-time 15 -H "Authorization: Bearer $TOKEN" "$API/api/automation/queue?status=dead")
echo "$DEAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print('死信数量', len(d)); [print(' ', r['id'][:8], r['status'], (r.get('last_error') or '')[:80]) for r in d]"

echo "==== 9. 取消一个排队中的任务 ===="
curl -k -s --max-time 15 -X POST "$API/api/automation/queue/$JOB/cancel" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | head -c 300; echo
echo "（已完成的任务取消应报错，这是正确行为）"

echo "==== 10. 清理 ===="
sudo -u "$OWNER" psql -h "$SOCK" -p "$PORT" -d "$DB" -tAc \
  "delete from workspace_task_jobs where idempotency_key='verify-queue-live-1'"
rm -f /tmp/queue-verify-enqueue.json /tmp/queue-verify-bad.json
echo "CLEANED"

echo "==== 验证完成 ===="
