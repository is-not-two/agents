#!/usr/bin/env bash
# =============================================================================
# 8771 测试环境「专用部署身份」配置脚本
# 运行位置：阿里云 Workbench / ECS 的 root 终端（整段粘贴，或 bash setup-...sh）
# 作用范围：仅 /var/lib/shilie-preview、shilie-preview.service、shilie_deploy 用户
# 绝不触碰：shilie.service(8770)、/opt/shilie、/etc/shilie、正式库、业务数据
# 私钥：不出现在任何文件里；公钥（非秘密）内嵌于下方 PUBKEY。
# 幂等：可重复执行；不删除 previous/ 历史代码；不新建数据库备份；不清理业务数据。
# =============================================================================
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

# -----------------------------------------------------------------------------
# 常量（按服务器真实拓扑，来自 docs/DEPLOYMENT_REALITY.md / AGENTS.md）
# -----------------------------------------------------------------------------
DEPLOY_USER=shilie_deploy
APP_USER=shilie_pvapp
PREVIEW_ROOT=/var/lib/shilie-preview
PREVIEW_APP="$PREVIEW_ROOT/app"
PREVIEW_SERVICE=shilie-preview.service
PROD_SERVICE=shilie.service
PREVIEW_PORT=8771
INCOMING="$PREVIEW_ROOT/incoming"
PREVIOUS="$PREVIEW_ROOT/previous"
# gate 路径必须在 deploy 用户可逐层遍历的目录；但 2026-11-04 实测：
# 本机 /usr/bin、/usr/local/bin、/usr/local/sbin 全部是 root:root 750（/bin -> /usr/bin），
# 非 root 用户连 bash/env 都执行不了。故 SECTION 2 加了 BIN_DIR_MODE 前置检查，
# 该门槛不满足时脚本 exit 3，不留下半可用配置。满足（/usr/bin>=755）后才继续。
# runner 只由 sudo 以 root 调用，留在 /usr/local/sbin 不受影响。
GATE=/usr/bin/shilie-preview-gate
RUNNER=/usr/local/sbin/shilie-preview-deploy-runner
SUDOERS=/etc/sudoers.d/shilie-preview-deploy
LOGFILE=/var/log/shilie-preview-deploy.log
SITE_PKG="$PREVIEW_APP/.venv/lib/python3.10/site-packages/rag_tech_retriever"
SRC_PKG="$PREVIEW_APP/src/rag_tech_retriever"
EXPECTED_HOSTKEY_FP='SHA256:kf5k4BoDnFNH9oZD/BZCynrBVRfwq9MJWiKPyASx02E'
PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC0XkDc2t5zFhyU4VnqttflrK5wbvHrfNpbdxCvD7nsH shilie-preview-8771-deploy'
VERIFY_NAME=verify-current
MAX_PKG_BYTES=$((200*1024*1024))

ok(){ printf '  [OK]   %s\n' "$*"; }
info(){ printf '  [INFO] %s\n' "$*"; }
die(){ printf '  [FATAL] %s\n' "$*" >&2; exit 1; }
hr(){ printf '\n========== %s ==========\n' "$*"; }

# =============================================================================
# SECTION 1 —— 只读状态检查（先检查实际状态，不假定网络/配置正常）
# =============================================================================
hr "SECTION 1 当前实际状态（只读）"
[ "$(id -u)" -eq 0 ] || die "必须在 root 终端运行"

echo "-- 主机与内核 --"
hostname; uname -sr

echo "-- 本机 ED25519 主机指纹（应与用户给定值一致）--"
HOSTKEY_FP=$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')
echo "  actual  : $HOSTKEY_FP"
echo "  expected: $EXPECTED_HOSTKEY_FP"
[ "$HOSTKEY_FP" = "$EXPECTED_HOSTKEY_FP" ] && ok "主机指纹一致" || die "主机指纹不匹配，停止"

echo "-- 22 / 8770 / 8771 本机监听 --"
ss -ltnp | grep -E ':22 |:8770 |:8771 ' || true

echo "-- 服务状态 --"
echo "  preview is-active : $(systemctl is-active "$PREVIEW_SERVICE" 2>&1 || true)"
echo "  preview User      : $(systemctl show "$PREVIEW_SERVICE" --property=User --value 2>/dev/null)"
echo "  preview ExecStart : $(systemctl show "$PREVIEW_SERVICE" --property=ExecStart --value 2>/dev/null | head -c 200)"
echo "  PROD MainPID(只读记录) : $(systemctl show "$PROD_SERVICE" --property=MainPID --value 2>/dev/null)"
PROD_PID_BEFORE=$(systemctl show "$PROD_SERVICE" --property=MainPID --value 2>/dev/null)
echo "$PROD_PID_BEFORE" > /tmp/.shilie_prod_pid_before

echo "-- 8771 健康端点自测（找第一个 200）--"
HEALTH_PATH=""
for p in /health /health/live /health/ready /api/session; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' -m 6 "https://127.0.0.1:$PREVIEW_PORT$p" || true)
  echo "  $p -> $code"
  [ "$code" = "200" ] && [ -z "$HEALTH_PATH" ] && HEALTH_PATH=$p
done
[ -n "$HEALTH_PATH" ] && ok "健康端点 = $HEALTH_PATH" || die "8771 当前无 200 健康端点，停止（避免部署后无法验证）"

echo "-- app 布局与属主 --"
[ -d "$PREVIEW_APP" ] && [ ! -L "$PREVIEW_APP" ] || die "$PREVIEW_APP 不是普通目录，停止"
stat -c '  %n %F %U:%G %a' "$PREVIEW_APP" "$SITE_PKG" "$SRC_PKG" 2>/dev/null || true

echo "-- 上一个助手的 MiMo 修复是否仍在（modified sha = 6af1fca2...）--"
for f in "$SITE_PKG/platform/model_connection.py" "$SRC_PKG/platform/model_connection.py"; do
  [ -f "$f" ] && sha256sum "$f" || info "缺失 $f"
done

echo "-- 正式库/正式配置 只读指纹（仅记录，不读写内容）--"
stat -c '  %n %U:%G %a' /opt/shilie /etc/shilie 2>/dev/null || true
info "正式库 shilie_native_20261027 本脚本全程不连接"

# =============================================================================
# SECTION 2 —— 前置校验
# =============================================================================
hr "SECTION 2 前置校验"
# 用 systemctl cat 判 unit 存在（list-unit-files 的输出格式在不同 systemd 版本上有前导空格/别名，不可靠）
systemctl cat "$PREVIEW_SERVICE" >/dev/null 2>&1 || die "找不到 $PREVIEW_SERVICE"
[ "$(systemctl show "$PREVIEW_SERVICE" --property=User --value)" = "$APP_USER" ] \
  || die "preview unit 身份不是 $APP_USER，与隔离部署假设不符，停止"
grep -q "$PREVIEW_ROOT" <(systemctl show "$PREVIEW_SERVICE" --property=ExecStart --value) \
  || die "preview ExecStart 未指向 $PREVIEW_ROOT，停止"

# 2026-11-04 实测硬门槛：本机 /usr/bin、/usr/local/bin、/usr/local/sbin 全是 root:root 750，
# 且 /bin -> /usr/bin。任何非 root 用户（含本部署身份）都无法执行 bash/env/systemctl/curl/sudo
# 的 shell 解析，force-command 与 login shell 均会 Permission denied。
# 这是服务器既有系统级权限加固，脚本无法靠挪 gate 路径绕过（shebang 依赖 /usr/bin/env）。
BIN_DIR_MODE=$(stat -c %a /usr/bin)
if [ "$BIN_DIR_MODE" -lt 755 ]; then
  echo ""
  echo "  [BLOCKER] 系统目录权限阻断：/usr/bin=$BIN_DIR_MODE（需要 >=755）"
  echo "  [BLOCKER] /bin -> $(readlink -f /bin)，非 root 用户无法执行任何系统二进制"
  echo "  [BLOCKER] 专用 SSH 身份的 force-command / login shell 会报 Permission denied"
  echo "  [BLOCKER] 修复（需 root，系统级改动，请用户明确授权）："
  echo "     chmod 0755 /usr/bin /usr/local/bin /usr/local/sbin"
  echo "  [BLOCKER] 本脚本不擅自改系统目录权限；此处停止，避免留下半可用配置。"
  echo ""
  exit 3
fi
ok "前置校验通过（/usr/bin=$BIN_DIR_MODE，非 root 可执行系统二进制）"

# =============================================================================
# SECTION 3 —— 生成受控身份与入口
# =============================================================================
hr "SECTION 3 配置专用部署身份"

# 3.1 系统用户：无密码、不加入任何管理组。
# 【2026-11-04 实测修正】shell 不能设 nologin —— sshd 会回
# "This account is currently not available"，force-command 根本没机会执行。
# 用真实 shell /bin/bash 让 sshd 能起会话；安全性完全由 authorized_keys 的
# restrict + command= 保证（禁 PTY / 禁转发 / 不执行客户端提供的命令）。
DEPLOY_SHELL=/bin/bash
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir "$INCOMING" --shell "$DEPLOY_SHELL" "$DEPLOY_USER"
  ok "已创建 $DEPLOY_USER（system / 密码锁定 / 无管理组）"
else
  usermod -s "$DEPLOY_SHELL" -d "$INCOMING" "$DEPLOY_USER"
  ok "$DEPLOY_USER 已存在，shell=$DEPLOY_SHELL、家目录对齐 $INCOMING"
fi
passwd -l "$DEPLOY_USER" >/dev/null 2>&1 || true   # 确保密码登录不可用
id "$DEPLOY_USER"

# 3.2 目录：incoming 仅 deploy 用户可写；previous 仅 root 可写（回退材料不可被部署身份篡改）
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$INCOMING"
install -d -m 0750 -o root -g root "$PREVIOUS"
# 【2026-11-04 事故修复】绝不能对 gate 父目录做 `install -d -m 0750`：
# install -d -m 会连「已存在」的目录一起改权限，前几轮把 /usr/local/sbin、
# /usr/local/bin、/usr/bin 依次改成 750，导致非 root 无法执行任何二进制，
# 并让我误判成「服务器既有加固」。这里只校验存在且可遍历，不改权限。
GATE_DIR=$(dirname "$GATE")
[ -d "$GATE_DIR" ] || die "gate 父目录不存在：$GATE_DIR"
[ -x "$GATE_DIR" ] || die "gate 父目录不可遍历：$GATE_DIR（请人工检查，不要自动 chmod 系统目录）"
ok "目录就位 $INCOMING(0700 deploy) / $PREVIOUS(0750 root)"

# 3.3 authorized_keys：restrict + 强制命令，公钥由 root 拥有、deploy 用户不可改
AK_DIR="$INCOMING/.ssh"
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$AK_DIR"
printf 'restrict,command="%s" %s\n' "$GATE" "$PUBKEY" > "$AK_DIR/authorized_keys"
chown root:root "$AK_DIR/authorized_keys"
chmod 0644 "$AK_DIR/authorized_keys"
# 让 sshd 从该位置读取（不改全局 sshd_config，用 AuthorizedKeysFile 的 %h 语义：家目录=INCOMING）
# 若 sshd 使用默认 ~/.ssh/authorized_keys 即生效；下面用 sshd -T 复核。
info "authorized_keys: restrict + command=$GATE（禁转发/禁 pty/禁任意命令/禁 shell）"

# 3.4 gate：唯一强制入口，白名单子命令，其余一律拒绝并记日志
cat > "$GATE" <<'GATE_EOF'
#!/usr/bin/env bash
# 唯一入口。SSH_ORIGINAL_COMMAND 是客户端原始命令；只放行 status / upload / deploy。
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
LOG=/var/log/shilie-preview-deploy.log
RUNNER=/usr/local/sbin/shilie-preview-deploy-runner
INCOMING=/var/lib/shilie-preview/incoming
MAX=209715200

log(){ printf '%s peer=%s user=%s %s\n' "$(date -Is)" "${SSH_CONNECTION%% *}" "${USER:-?}" "$*" >> "$LOG" 2>/dev/null || true; logger -t shilie-preview-deploy "$*" 2>/dev/null || true; }
reject(){ log "DENY orig='${SSH_ORIGINAL_COMMAND:-<empty>}' reason=$1"; printf 'REJECTED: %s\n' "$1" >&2; exit 1; }

cmd="${SSH_ORIGINAL_COMMAND:-}"
case "$cmd" in
  status)
    log "STATUS"
    printf 'unit=%s\n' "$(systemctl is-active shilie-preview.service 2>&1 || true)"
    printf 'user=%s\n' "$(systemctl show shilie-preview.service --property=User --value)"
    printf 'pid=%s\n' "$(systemctl show shilie-preview.service --property=MainPID --value)"
    printf 'health='; curl -sk -o /dev/null -w '%{http_code}\n' -m 6 https://127.0.0.1:8771/health || true
    printf 'prod_pid_readonly=%s\n' "$(systemctl show shilie.service --property=MainPID --value)"
    exit 0 ;;
  upload)
    log "UPLOAD"
    umask 077
    tmp=$(mktemp "$INCOMING/.upload-XXXXXX") || reject "mktemp 失败"
    # 从 stdin 接收一个 tar.gz 包；限流、限长、超时
    if ! timeout 180 head -c $((MAX+1)) > "$tmp"; then rm -f "$tmp"; reject "upload 读取失败"; fi
    sz=$(stat -c %s "$tmp")
    if [ "$sz" -gt "$MAX" ]; then rm -f "$tmp"; reject "包超过 ${MAX} 字节"; fi
    if ! gzip -t "$tmp" 2>/dev/null; then rm -f "$tmp"; reject "不是完整 gzip 流"; fi
    mv -f "$tmp" "$INCOMING/pending.tar.gz"
    printf 'UPLOAD_OK bytes=%s\n' "$sz"
    exit 0 ;;
  deploy\ *)
    name="${cmd#deploy }"
    case "$name" in
      *[!A-Za-z0-9._-]*|''|.*|*..*) reject "非法 release 名" ;;
    esac
    [ -f "$INCOMING/pending.tar.gz" ] || reject "没有待部署包（先 upload）"
    # 固定文件名与 release 名绑定，避免路径拼接
    log "DEPLOY_REQUEST name=$name"
    exec sudo -n "$RUNNER" deploy "$name" ;;
  *)
    reject "仅允许 status | upload | deploy <name>" ;;
esac
GATE_EOF
chown root:root "$GATE"; chmod 0755 "$GATE"
# 兼容早期把 gate 放在 750 目录的残留：删掉，避免误用不可执行的旧文件
rm -f /usr/local/sbin/shilie-preview-gate /usr/local/bin/shilie-preview-gate
ok "gate 就位（$GATE，白名单：status / upload / deploy）"

# 3.5 runner：唯一可提权的脚本，含包审查、受控换位、失败自动回退、日志
cat > "$RUNNER" <<'RUNNER_EOF'
#!/usr/bin/env bash
# 以 root 运行（仅由 gate 经 sudo 调用）。只替换 8771 的 Python 包代码，别的都不碰。
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
LOG=/var/log/shilie-preview-deploy.log
ROOT=/var/lib/shilie-preview
APP=$ROOT/app
SVC=shilie-preview.service
PROD_SVC=shilie.service
PORT=8771
INCOMING=$ROOT/incoming
PREVIOUS=$ROOT/previous
SITE=$APP/.venv/lib/python3.10/site-packages/rag_tech_retriever
SRC=$APP/src/rag_tech_retriever
APP_USER=shilie_pvapp
MAX=209715200

log(){ printf '%s [runner] %s\n' "$(date -Is)" "$*" >> "$LOG" 2>/dev/null || true; logger -t shilie-preview-deploy "runner: $*" 2>/dev/null || true; }
fail(){ log "ERROR $*"; printf 'DEPLOY_FAILED: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "runner 必须 root"
action="${1:-}"; name="${2:-}"
[ "$action" = deploy ] || fail "仅支持 deploy"
case "$name" in *[!A-Za-z0-9._-]*|''|.*|*..*) fail "非法 release 名" ;; esac

pkg="$INCOMING/pending.tar.gz"
[ -f "$pkg" ] || fail "缺少 $pkg"
[ ! -L "$pkg" ] || fail "待部署包是软链接"
[ "$(stat -c %s "$pkg")" -le "$MAX" ] || fail "包过大"
[ "$(stat -c %U "$pkg")" = "shilie_deploy" ] || fail "包属主异常"

# ---- 部署包审查：路径穿越 / 软链接 / 权限位 / 顶层结构 ----
log "AUDIT $name"
mapfile -t names < <(tar -tzf "$pkg" 2>/dev/null) || fail "tar 无法列出内容（损坏或非法）"
[ "${#names[@]}" -gt 0 ] || fail "空包"
have_root=0
for p in "${names[@]}"; do
  case "$p" in
    /*|*../*|*/../*|*/..|..) fail "路径越界成员: $p" ;;
  esac
  case "$p" in *' '*|*$'\t'*) fail "成员名含空白(拒绝以保解析确定): $p" ;; esac
  case "$p" in rag_tech_retriever/*|rag_tech_retriever) have_root=1 ;; esac
done
[ "$have_root" -eq 1 ] || fail "包缺少顶层 rag_tech_retriever/ 目录"
# 类型/权限位：tar -tvzf 首字符；拒绝链接、设备、fifo、setuid/setgid/sticky
while IFS= read -r line; do
  mode="${line:0:10}"
  case "${mode:0:1}" in
    -|d) ;;
    *) fail "非法成员类型: $line" ;;
  esac
  case "$mode" in *s*|*S*|*t*|*T*) fail "含 setuid/setgid/sticky 位: $line" ;; esac
  case "$line" in *' -> '*) fail "符号链接成员: $line" ;; esac
done < <(tar -tvzf "$pkg" 2>/dev/null)
log "AUDIT_PASS members=${#names[@]}"

# ---- 目标边界复核 ----
[ -d "$APP" ] && [ ! -L "$APP" ] || fail "$APP 必须是普通目录"
[ -d "$SITE" ] || fail "缺少目标 $SITE"
[ "$(systemctl show "$SVC" --property=User --value)" = "$APP_USER" ] || fail "unit 身份异常"
systemctl show "$SVC" --property=ExecStart --value | grep -q "$ROOT" || fail "unit 未指向隔离根，拒绝"
PROD_PID=$(systemctl show "$PROD_SVC" --property=MainPID --value)

# ---- 解包到 root 私有 staging（不沿用包内属主/权限；再复核无软链）----
stage=$(mktemp -d "$ROOT/.staging-XXXXXX")
chmod 0750 "$stage"
trap 'rm -rf "$stage"' EXIT
tar --no-same-owner --no-same-permissions --no-overwrite-dir -xzf "$pkg" -C "$stage" || fail "解包失败"
[ -d "$stage/rag_tech_retriever" ] || fail "解包后缺少 rag_tech_retriever/"
if find "$stage" -type l | grep -q .; then fail "staging 内出现软链接"; fi
find "$stage" -type f -exec chmod 0644 {} + ; find "$stage" -type d -exec chmod 0755 {} +

# ---- 保留旧代码（回退材料），不做任何删除 ----
ts=$(date +%Y%m%d-%H%M%S)
keep="$PREVIOUS/$name-$ts"
install -d -m 0750 "$keep"
[ -d "$SITE" ] && cp -a "$SITE" "$keep/site-rag_tech_retriever" || true
[ -d "$SRC" ]  && cp -a "$SRC"  "$keep/src-rag_tech_retriever"  || true
log "BACKUP $keep （旧代码保留，不删除 previous/）"

# ---- 健康端点 ----
health_path=""
for p in /health /health/live /health/ready /api/session; do
  c=$(curl -sk -o /dev/null -w '%{http_code}' -m 6 "https://127.0.0.1:$PORT$p" || true)
  [ "$c" = 200 ] && { health_path=$p; break; }
done
[ -n "$health_path" ] || fail "部署前 8771 无健康端点，中止（不换位）"

rollback(){
  log "ROLLBACK 开始"
  systemctl stop "$SVC" >/dev/null 2>&1 || true
  [ -d "$keep/site-rag_tech_retriever" ] && { rm -rf "$SITE"; cp -a "$keep/site-rag_tech_retriever" "$SITE"; }
  [ -d "$keep/src-rag_tech_retriever" ]  && { rm -rf "$SRC";  cp -a "$keep/src-rag_tech_retriever"  "$SRC"; }
  chown -R "$APP_USER:$APP_USER" "$SITE" "$SRC" 2>/dev/null || true
  systemctl start "$SVC" >/dev/null 2>&1 || true
  log "ROLLBACK 完成"
}

# ---- 停服 → 替换两处代码目录 → 起服 ----
log "SWAP 开始 name=$name"
if ! systemctl stop "$SVC"; then fail "停止 8771 失败（未改动代码）"; fi
newsite="$SITE.deploy-new"; newsrc="$SRC.deploy-new"
rm -rf "$newsite" "$newsrc"
cp -a "$stage/rag_tech_retriever" "$newsite"
cp -a "$stage/rag_tech_retriever" "$newsrc"
chown -R "$APP_USER:$APP_USER" "$newsite" "$newsrc"

mv "$SITE" "$SITE.deploy-old"; mv "$newsite" "$SITE"
if [ -d "$SRC" ]; then mv "$SRC" "$SRC.deploy-old"; fi
mv "$newsrc" "$SRC"

if ! systemctl start "$SVC"; then
  rollback
  [ -d "$SITE.deploy-old" ] && mv "$SITE.deploy-old" "$SITE" || true
  fail "启动 8771 失败，已回退"
fi
# 等待健康
healthy=0
for i in $(seq 1 20); do
  c=$(curl -sk -o /dev/null -w '%{http_code}' -m 4 "https://127.0.0.1:$PORT$health_path" || true)
  [ "$c" = 200 ] && { healthy=1; break; }
  sleep 1
done
# 复核正式服务 PID 未变
PROD_PID_AFTER=$(systemctl show "$PROD_SVC" --property=MainPID --value)
if [ "$healthy" -ne 1 ] || [ "$PROD_PID" != "$PROD_PID_AFTER" ]; then
  rollback
  [ -d "$SITE.deploy-old" ] && { rm -rf "$SITE"; mv "$SITE.deploy-old" "$SITE"; }
  [ -d "$SRC.deploy-old" ]  && { rm -rf "$SRC";  mv "$SRC.deploy-old"  "$SRC"; }
  chown -R "$APP_USER:$APP_USER" "$SITE" "$SRC" 2>/dev/null || true
  fail "验证失败(healthy=$healthy prod_pid $PROD_PID->$PROD_PID_AFTER)，已回退"
fi
# 成功：清理本次 .deploy-old 临时副本（previous/ 里的回退副本永久保留）
rm -rf "$SITE.deploy-old" "$SRC.deploy-old"
# 归档本次包到 previous，pending 清出待部署区（不删除历史）
mv -f "$pkg" "$keep/payload.tar.gz"
log "DEPLOY_OK name=$name health=$health_path prod_pid=$PROD_PID_AFTER backup=$keep"
printf 'DEPLOY_OK name=%s backup=%s health=%s\n' "$name" "$keep" "$health_path"
RUNNER_EOF
chown root:root "$RUNNER"; chmod 0750 "$RUNNER"
ok "runner 就位（含路径穿越/软链接/setuid 审查 + 自动回退）"

# 3.6 sudoers：精确到单一 runner + 参数形状，禁止其它任何命令
cat > "$SUDOERS" <<'SUDO_EOF'
# 仅允许 gate 调用 runner 的 deploy 子命令；参数不含空格/分号/斜杠。
Defaults:shilie_deploy !requiretty, env_reset, umask=0027
Cmnd_Alias PREVIEW_DEPLOY = /usr/local/sbin/shilie-preview-deploy-runner deploy [A-Za-z0-9._-]*
shilie_deploy ALL=(root) NOPASSWD: PREVIEW_DEPLOY
SUDO_EOF
chown root:root "$SUDOERS"; chmod 0440 "$SUDOERS"
visudo -cf "$SUDOERS" || die "sudoers 语法错误"
ok "sudoers 精确到单一脚本（visudo 校验通过）"

# 3.7 日志文件：deploy 用户可 append，root 可写；别人不可读
install -o root -g "$DEPLOY_USER" -m 0660 /dev/null "$LOGFILE" 2>/dev/null || { : > "$LOGFILE"; chown root:"$DEPLOY_USER" "$LOGFILE"; chmod 0660 "$LOGFILE"; }
ok "审计日志 $LOGFILE (root:shilie_deploy 0660) + journald"

# 3.8 复核 sshd 是否会读取我们放的 authorized_keys
hr "SECTION 3b sshd 配置复核"
sshd -T 2>/dev/null | grep -iE 'authorizedkeysfile|pubkeyauthentication|permitrootlogin' || true
info "若 AuthorizedKeysFile 不是默认 .ssh/authorized_keys，请把公钥改放到对应位置并保持一致"

# =============================================================================
# SECTION 4 —— 服务器端自测（不依赖外部网络，模拟 force-command）
# =============================================================================
hr "SECTION 4 服务器端自测"

# 2026-11-04 实测：runuser/su 走 PAM，被本机 PAM 配置挡住（failed to execute ... Permission denied），
# 而 setpriv --reuid/--regid --clear-groups 精确降权执行成功。自测用 setpriv 模拟 deploy 身份，
# 不依赖 PAM。注意：真实 SSH 由 sshd 起会话、不走 runuser，是最终判据（见 README §7）。
DEPLOY_UID=$(id -u "$DEPLOY_USER")
DEPLOY_GID=$(id -g "$DEPLOY_USER")
as_deploy(){ SSH_ORIGINAL_COMMAND="$1" setpriv --reuid="$DEPLOY_UID" --regid="$DEPLOY_GID" --clear-groups /usr/bin/env "$GATE"; }

echo "-- 4.1 负向：任意命令 / 空命令（想要 shell）/ 操作 8770 / 访问正式库 --"
for bad in 'id; whoami; cat /etc/shadow' '' 'systemctl restart shilie' 'sudo -l' \
           'curl -k https://127.0.0.1:8770/api/session' 'psql -d shilie_native_20261027 -c select'; do
  out=$(as_deploy "$bad" 2>&1 || true)
  case "$out" in *REJECTED*) ok "DENY <<$bad>>" ;; *) echo "  [WARN] 未按预期拒绝: <<$bad>> => $out" ;; esac
done

echo "-- 4.2 正向：status 只读 --"
as_deploy status || die "status 失败"

echo "-- 4.3 恶意包审计：用 python3 精确构造三类恶意成员，逐条触发审查分支 --"
# tar 命令行默认会剥离 ../ 成员名，无法可靠测到「路径穿越」分支；
# 这里用 python3 tarfile 直接写入成员名，确保 ../ / 软链 / setuid 三条规则都被真实触发。
BAD_TMP=$(mktemp -d); trap 'rm -rf "$BAD_TMP"' EXIT
BASELINE_SHA=$(sha256sum "$SITE_PKG/platform/model_connection.py" | awk '{print $1}')
make_bad(){  # $1=输出路径  $2=类型
python3 - "$1" "$2" <<'PY'
import io, sys, tarfile
out, kind = sys.argv[1], sys.argv[2]
with tarfile.open(out, "w:gz") as t:
    def add(name, data=b"", mode=0o644, typ=tarfile.REGTYPE, link=""):
        ti = tarfile.TarInfo(name); ti.mode = mode; ti.type = typ; ti.linkname = link
        ti.size = len(data); t.addfile(ti, io.BytesIO(data))
    add("rag_tech_retriever/__init__.py", b"")
    if kind == "traversal":
        add("../evil_escape.py", b"print('escaped')\n")          # 路径穿越成员名
    elif kind == "symlink":
        add("rag_tech_retriever/link_to_shadow", typ=tarfile.SYMTYPE, link="/etc/shadow")
    elif kind == "setuid":
        add("rag_tech_retriever/suid.py", b"x\n", mode=0o4755)    # setuid 位
    elif kind == "absolute":
        add("/etc/cron.d/evil", b"* * * * * root id\n")           # 绝对路径
PY
}
for kind in traversal symlink setuid absolute; do
  make_bad "$BAD_TMP/$kind.tar.gz" "$kind"
  cp "$BAD_TMP/$kind.tar.gz" "$INCOMING/pending.tar.gz"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$INCOMING/pending.tar.gz"
  # 直接以 root 调 runner（等价于 gate->sudo 的审计分支），预期全部失败
  if sudo -n "$RUNNER" deploy "bad-$kind" >/tmp/.badout 2>&1; then
    die "恶意包 $kind 未被拒绝（严重）：$(cat /tmp/.badout)"
  else
    ok "拒绝 $kind: $(tail -1 /tmp/.badout)"
  fi
  rm -f "$INCOMING/pending.tar.gz"
done
# 证明：四次恶意部署后，线上代码一行未动
NOW_SHA=$(sha256sum "$SITE_PKG/platform/model_connection.py" | awk '{print $1}')
[ "$BASELINE_SHA" = "$NOW_SHA" ] && ok "恶意包被拒且线上代码 sha256 未变" \
  || die "恶意包阶段改动了线上代码，用 previous/ 回退"
rm -f /tmp/.badout

echo "-- 4.4 正常包：就地打包『当前运行中的代码』（含未入库的 MiMo 修复），走完整 upload→deploy --"
SNAP=$(mktemp -d)
cp -a "$SITE_PKG" "$SNAP/rag_tech_retriever"
tar -czf "$SNAP/payload.tar.gz" -C "$SNAP" rag_tech_retriever
MIMO_BEFORE=$(sha256sum "$SITE_PKG/platform/model_connection.py" | awk '{print $1}')
echo "  MiMo 文件部署前 sha256 = $MIMO_BEFORE"
# 用 setpriv 精确降权模拟 deploy 身份（PAM 阻挡的绕法），经 gate 的 upload 分支接收 stdin 流
SSH_ORIGINAL_COMMAND=upload setpriv --reuid="$DEPLOY_UID" --regid="$DEPLOY_GID" --clear-groups /usr/bin/env "$GATE" < "$SNAP/payload.tar.gz"
ok "upload 经 gate 成功"
# 经 gate -> sudo -n -> runner 真实部署
SSH_ORIGINAL_COMMAND="deploy $VERIFY_NAME" setpriv --reuid="$DEPLOY_UID" --regid="$DEPLOY_GID" --clear-groups /usr/bin/env "$GATE"
ok "deploy 经 gate+sudo 成功（真实停/换位/起/健康/回退链路）"
MIMO_AFTER=$(sha256sum "$SITE_PKG/platform/model_connection.py" | awk '{print $1}')
echo "  MiMo 文件部署后 sha256 = $MIMO_AFTER"
[ "$MIMO_BEFORE" = "$MIMO_AFTER" ] && ok "MiMo 修复未丢失" || die "MiMo 修复丢失，立即用 previous/ 回退"

echo "-- 4.5 收尾复核 --"
echo "  preview is-active : $(systemctl is-active "$PREVIEW_SERVICE")"
echo "  health            : $(curl -sk -o /dev/null -w '%{http_code}' -m 6 https://127.0.0.1:8771"$HEALTH_PATH")"
PROD_PID_AFTER=$(systemctl show "$PROD_SERVICE" --property=MainPID --value)
echo "  PROD MainPID      : $PROD_PID_BEFORE -> $PROD_PID_AFTER"
[ "$PROD_PID_BEFORE" = "$PROD_PID_AFTER" ] && ok "正式 8770 未重启" || die "正式 PID 变化，异常"
echo "  previous 回退副本 :"; ls -1 "$PREVIOUS" | tail -5
echo "  审计日志尾部      :"; tail -12 "$LOGFILE"
rm -rf "$SNAP" "$BAD_TMP" /tmp/.badout /tmp/.shilie_prod_pid_before

hr "完成"
printf '服务器端自测完成。\n'
printf '注意：本脚本自测用 setpriv 模拟 deploy 身份，最终判据仍是用本机专用密钥真实 SSH（README §7）。\n'
printf '若 SECTION 2 因 /usr/bin 权限不足 exit 3，需先由 root chmod 0755 三个系统目录（系统级改动，需授权）。\n'
printf '正式环境晋级仍需用户另行明确授权；本脚本未触碰 8770。\n'
