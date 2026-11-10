"""8771 隔离测试环境部署：暂存构建 -> 整目录换位 -> 验证 ->（失败则）换回。

为什么需要独立脚本
- `deploy_release.py` 的 preview 目标仍在写 `/opt/shilie/preview`，且以共享身份
  覆盖代码；2026-11-04 起 8771 已切到 `shilie_pvapp` + `/var/lib/shilie-preview/app`，
  旧流程会在预检阶段被拒绝。本脚本是隔离运行时的唯一部署路径。
- 隔离 unit 的可写目录是稳定路径 `/var/lib/shilie-preview/app/data/local` 与
  `/var/lib/shilie-preview/app/output`，因此这里不切软链，而是整目录换位：
  旧 app 移到 `previous/`，新 app 从 `staging/` 原子改名到 `app`，失败即换回。
- `.venv312`（Python 3.12）用硬链接克隆（同一文件系统），避免每次复制 1.7G；
  该 venv 为 editable 安装，`.pth` 指向 `/var/lib/shilie-preview/app/src`，
  整目录换位后即加载新代码，无需复制包到 site-packages。

安全边界
- 只操作 `/var/lib/shilie-preview`、`shilie-preview.service` 与隔离库；
  绝不触碰 `/opt/shilie`、`/etc/shilie`、`/var/lib/shilie`、`shilie.service`、8770。
- 预检要求 unit 身份为 `shilie_pvapp` 且 `ExecStart` 指向隔离根，否则立即中止。
- 默认 `--dry-run`；`--apply --confirm HEAD|<release>` 才执行。
- 部署后复核正式服务 PID 未变；正式库/正式私密文件不做任何读写。

用法（项目根目录，Windows PowerShell 或 bash）：
    python scripts/deploy_preview_isolated.py --dry-run
    python scripts/deploy_preview_isolated.py --apply --confirm HEAD
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_release as base  # 复用 SSH/打包/日志等已验证实现

PREVIEW_USER = "shilie_pvapp"
PREVIEW_SERVICE = "shilie-preview"
PREVIEW_PORT = 8771
PREVIEW_ROOT = "/var/lib/shilie-preview"
PREVIEW_APP = f"{PREVIEW_ROOT}/app"
PREVIEW_DB = "shilie_preview_20261104"
PREVIEW_PG_SOCK = f"{PREVIEW_ROOT}/pgsock"
PREVIEW_PG_PORT = 55433
PROD_SERVICE = "shilie"
PREVIEW_VENV = ".venv312"


def isolated_runtime(user: str, exec_start: str) -> bool:
    """unit 是否运行在隔离身份与隔离根内。"""
    return user == PREVIEW_USER and PREVIEW_APP in exec_start


def layout_is_plain_dir(kind: str) -> bool:
    """`app` 必须是普通目录（本脚本做整目录换位，不处理软链布局）。"""
    return kind.strip() == "directory"


def run_remote(script: str, *, timeout: int = 600) -> tuple[int, str]:
    """复用 deploy_release 的远端执行（二进制 stdin，避免 Windows CRLF 破坏 sh）。"""
    return base.run_remote(script, timeout=timeout)


def preflight() -> dict:
    """只读预检：隔离身份、数据基线、正式服务 PID、磁盘与登录形态。"""
    base.step("预检")
    if not base.KEY.is_file():
        raise base.DeployError(f"SSH 密钥不存在：{base.KEY}")

    local_ver = base.local_version()
    base.ok(f"本地版本 v{local_ver}")

    script = f"""
set -u
echo "APP_KIND=$(stat -c %F {PREVIEW_APP} 2>/dev/null || echo missing)"
echo "UNIT_USER=$(systemctl show {PREVIEW_SERVICE} --property=User --value)"
echo "UNIT_EXEC=$(systemctl show {PREVIEW_SERVICE} --property=ExecStart --value | head -c 260)"
echo "UNIT_ACTIVE=$(systemctl is-active {PREVIEW_SERVICE} || true)"
echo "PROD_PID=$(systemctl show {PROD_SERVICE} --property=MainPID --value)"
echo "DISK_FREE_KB=$(df -P / | awk 'NR==2 {{print $4}}')"
echo "RECORDS=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from workspace_records')"
echo "VERSIONS=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from workspace_versions')"
echo "VECTORS=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from rag_chunks')"
curl -sk -m 8 https://127.0.0.1:{PREVIEW_PORT}/api/session | sed 's/^/SESSION=/'
echo
echo "PREFLIGHT_END"
"""
    code, out = run_remote(script, timeout=120)
    if code != 0 or "PREFLIGHT_END" not in out:
        raise base.DeployError(f"预检失败：\n{out[-800:]}")

    info: dict = {"local_version": local_ver, "raw": out}
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key.lower()] = value.strip()

    if not layout_is_plain_dir(info.get("app_kind", "")):
        raise base.DeployError(
            f"{PREVIEW_APP} 不是普通目录（{info.get('app_kind')}），"
            "布局已变化；本脚本只支持当前的整目录布局。"
        )
    if not isolated_runtime(info.get("unit_user", ""), info.get("unit_exec", "")):
        raise base.DeployError(
            "8771 未处于隔离运行时："
            f"User={info.get('unit_user') or '?'}，ExecStart={info.get('unit_exec') or '?'}；"
            "请先确认 `zzzz-preview-isolation.conf` 生效，再部署。"
        )
    if info.get("unit_active") != "active":
        raise base.DeployError("8771 当前不是 active，先在测试环境排障，不能用部署覆盖未知状态。")

    try:
        info["records"] = int(info.get("records", ""))
        info["versions"] = int(info.get("versions", ""))
        info["vectors"] = int(info.get("vectors", ""))
        free_gb = int(info.get("disk_free_kb", "0")) / 1024 / 1024
    except ValueError as exc:
        raise base.DeployError(f"预检数值解析失败：{exc}") from exc
    if min(info["records"], info["versions"], info["vectors"]) < 0:
        raise base.DeployError("预检未取到数据基线，中止部署")

    info["disk_free_gb"] = round(free_gb, 1)
    info["prod_pid"] = info.get("prod_pid", "")
    if free_gb < 2:
        raise base.DeployError(f"磁盘剩余 {free_gb:.1f}G，不足 2G，中止部署")

    base.ok(f"隔离身份 {PREVIEW_USER}，app 为普通目录")
    base.ok(f"数据基线 {info['records']} 记录 / {info['versions']} 历史 / {info['vectors']} 向量")
    base.ok(f"正式 8770 PID {info['prod_pid'] or '?'}（部署期间必须不变）")
    base.ok(f"磁盘剩余 {info['disk_free_gb']}G")

    running = remote_version()
    info["running_version"] = running
    base.ok(f"线上版本 v{running} -> 目标 v{local_ver}")
    if info.get("session"):
        base.ok("登录形态：" + info["session"][:160])
    return info


def remote_version() -> str | None:
    """目标环境当前对外提供的静态版本号。"""
    code, out = run_remote(
        f"curl -sk -m 10 https://127.0.0.1:{PREVIEW_PORT}/ | grep -o '?v=[0-9]*' | head -1",
        timeout=40,
    )
    found = re.findall(r"v=(\d+)", out)
    return found[0] if (code == 0 and found) else None


def deploy(pkg: Path, release: str) -> str:
    """上传并在 staging 构建完整新 app，返回 staging 绝对路径。"""
    base.step("上传")
    remote_pkg = f"{PREVIEW_ROOT}/staging/{pkg.name}"
    run_remote(f"mkdir -p {PREVIEW_ROOT}/staging && chmod 711 {PREVIEW_ROOT}/staging", timeout=30)
    done = subprocess.run(
        ["scp", "-F", "none", "-P", "22", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
         "-o", "StrictHostKeyChecking=yes",
         *(["-o", f"UserKnownHostsFile={base.KNOWN_HOSTS}"] if base.KNOWN_HOSTS.is_file() else []),
         "-i", str(base.KEY), str(pkg), f"{base.USER}@{base.HOST}:{remote_pkg}"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900,
    )
    if done.returncode != 0:
        raise base.DeployError(f"上传失败：{done.stderr[-500:]}")
    base.ok(f"已上传 {pkg.name}")

    base.step("暂存构建")
    stage = f"{PREVIEW_ROOT}/staging/{release}"
    script = f"""
set -eu
APP={PREVIEW_APP}
STAGE={stage}
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar -xzf {remote_pkg} -C "$STAGE"

# venv 硬链接克隆：同文件系统，不复制 1.7G；新包只替换应用自身。
cp -al "$APP/{PREVIEW_VENV}" "$STAGE/{PREVIEW_VENV}"

# 用户数据与凭据只从隔离根继承，绝不读 /var/lib/shilie。
rm -rf "$STAGE/data/local" "$STAGE/data/public" "$STAGE/credentials" "$STAGE/output"
cp -a "$APP/data/local" "$STAGE/data/local"
if [ -d "$APP/data/public" ]; then cp -a "$APP/data/public" "$STAGE/data/public"; fi
cp -a "$APP/credentials" "$STAGE/credentials"
cp -a "$APP/output" "$STAGE/output"

# 共享配置优先、发布包补新键；共享独有文件也复制过来。
PYTHONPATH="$STAGE/src" "$STAGE/{PREVIEW_VENV}/bin/python" "$STAGE/scripts/merge_deploy_config.py" \
  --package "$STAGE/config" --persistent "$APP/config" --dest "$STAGE/config"
for f in "$APP/config"/*; do
  b=$(basename "$f")
  [ -e "$STAGE/config/$b" ] || cp -a "$f" "$STAGE/config/$b"
done

# editable 安装无需复制包：.pth 指向 app/src，换位后即为新代码。

chown -R root:{PREVIEW_USER} "$STAGE"
chmod 750 "$STAGE"
chmod -R g+rX,o-rwx "$STAGE"
chown -R {PREVIEW_USER}:{PREVIEW_USER} "$STAGE/data/local" "$STAGE/output"
chmod -R u+rwX,g+rwX "$STAGE/data/local" "$STAGE/output"
chmod 700 "$STAGE/data/local"
chmod 600 "$STAGE/data/local/encryption.key" "$STAGE/data/local/private-vault.json" 2>/dev/null || true
chmod 640 "$STAGE/credentials/server.key" 2>/dev/null || true

# 构建期自检：以服务身份导入包，并核对静态版本号。
runuser -u {PREVIEW_USER} -- env HOME="$STAGE" RAG_PROJECT_ROOT="$STAGE" PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$STAGE/src" \
  PATH="$STAGE/{PREVIEW_VENV}/bin:/usr/bin:/bin" \
  "$STAGE/{PREVIEW_VENV}/bin/python" -c "import rag_tech_retriever; print('IMPORT_OK')"
grep -q "?v={base.local_version()}" "$STAGE/src/rag_tech_retriever/api/static/shilie/index.html"

echo "STAGE={stage}"
echo "STAGE_SIZE=$(du -sh "$STAGE" | cut -f1)"
"""
    code, out = run_remote(script, timeout=900)
    if code != 0 or "STAGE=" not in out:
        raise base.DeployError(f"暂存构建失败：\n{out[-1200:]}")
    size = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("STAGE_SIZE=")), "?")
    base.ok(f"暂存完成（{size}）：{stage}")
    return stage


def swap(stage: str, release: str) -> str:
    """停服，把旧 app 移到 previous，再把 staging 改名到 app；返回旧路径。"""
    base.step("换位")
    script = f"""
set -eu
APP={PREVIEW_APP}
OLD={PREVIEW_ROOT}/previous/app-{release}
mkdir -p {PREVIEW_ROOT}/previous
if [ -e "$OLD" ]; then OLD="$OLD-$(date +%H%M%S)"; fi
systemctl stop {PREVIEW_SERVICE}
mv "$APP" "$OLD"
mv {stage} "$APP"
echo "OLD=$OLD"
"""
    code, out = run_remote(script, timeout=120)
    old = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("OLD=")), "")
    if code != 0 or not old:
        raise base.DeployError(f"换位失败：\n{out[-800:]}")
    base.ok(f"旧目录：{old}")
    return old


def start_service() -> None:
    """轮询启动到 active；失败时带出最近日志。"""
    base.step("启动")
    code, out = base.run_remote(f"""
systemctl start {PREVIEW_SERVICE}
i=0
while [ $i -lt 40 ]; do
  STATE=$(systemctl is-active {PREVIEW_SERVICE})
  if [ "$STATE" = "active" ]; then echo "SERVICE=active"; exit 0; fi
  if [ "$STATE" = "failed" ]; then echo "SERVICE=failed"; exit 1; fi
  i=$((i+1)); sleep 2
done
echo "SERVICE=timeout"
exit 1
""", timeout=300)
    if code != 0 or "SERVICE=active" not in out:
        jcode, jout = run_remote(
            f"journalctl -u {PREVIEW_SERVICE} -n 20 --no-pager 2>/dev/null | tail -20", timeout=40)
        detail = jout.strip() if jcode == 0 else ""
        raise base.DeployError(f"启动失败：\n{out[-600:]}\n{detail[-800:]}")
    base.ok("服务已 active")


def verify(info: dict) -> None:
    """健康、版本、数据、登录、静态资源与正式服务 PID 复核。"""
    base.step("验证")
    deadline = time.time() + 180
    health = ""
    journal = ""
    while time.time() < deadline:
        code, out = run_remote(
            f"curl -sk -m 8 https://127.0.0.1:{PREVIEW_PORT}/health", timeout=40)
        if code == 0 and '"status":"ok"' in out:
            health = out.strip()
            break
        jcode, jout = run_remote(
            f"journalctl -u {PREVIEW_SERVICE} -n 25 --no-pager 2>/dev/null | "
            "grep -iE 'error|exception|traceback|OSError|failed' | tail -8",
            timeout=40)
        if jcode == 0 and jout.strip():
            journal = jout.strip()
        time.sleep(5)
    if not health:
        hint = f"\n最近错误日志：\n{journal}" if journal else ""
        raise base.DeployError(f"健康检查 180 秒内未通过{hint}")
    base.ok(f"健康：{health[:120]}")

    ver = remote_version()
    if ver != info["local_version"]:
        raise base.DeployError(f"版本不符：期望 v{info['local_version']}，实际 v{ver}")
    base.ok(f"线上版本 v{ver}")

    script = f"""
echo "USER=$(systemctl show {PREVIEW_SERVICE} --property=User --value)"
echo "PROD_PID=$(systemctl show {PROD_SERVICE} --property=MainPID --value)"
echo "R=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from workspace_records')"
echo "V=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from workspace_versions')"
echo "C=$(runuser -u shilie_pvdb -- psql -h {PREVIEW_PG_SOCK} -p {PREVIEW_PG_PORT} -d {PREVIEW_DB} -tAc 'select count(*) from rag_chunks')"
curl -sk -m 8 -o /dev/null -w "STATIC=%{{http_code}}\\n" https://127.0.0.1:{PREVIEW_PORT}/static/shilie/app.js
curl -sk -m 8 -o /dev/null -w "AUTH=%{{http_code}}\\n" https://127.0.0.1:{PREVIEW_PORT}/api/knowledge
curl -sk -m 8 https://127.0.0.1:{PREVIEW_PORT}/api/session | sed 's/^/SESSION=/'
echo
"""
    code, out = run_remote(script, timeout=90)
    values: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip()

    if values.get("USER") != PREVIEW_USER:
        raise base.DeployError(f"隔离身份被改动：User={values.get('USER')}")
    base.ok(f"隔离身份仍为 {PREVIEW_USER}")

    if values.get("PROD_PID") != info["prod_pid"]:
        raise base.DeployError(
            f"正式 8770 PID 变化：部署前 {info['prod_pid']}，现在 {values.get('PROD_PID')}"
        )
    base.ok(f"正式 8770 未重启（PID {info['prod_pid']}）")

    try:
        actual = {key: int(values.get(key, "")) for key in ("R", "V", "C")}
    except ValueError as exc:
        raise base.DeployError(f"验证数值解析失败：{exc}") from exc
    for label, key, expected in (
        ("记录", "R", info["records"]),
        ("历史", "V", info["versions"]),
        ("向量", "C", info["vectors"]),
    ):
        if actual[key] != expected:
            raise base.DeployError(f"{label}数变化：部署前 {expected}，现在 {actual[key]}")
    base.ok(f"数据未变：{info['records']} 记录 / {info['versions']} 历史 / {info['vectors']} 向量")

    if values.get("STATIC") != "200":
        raise base.DeployError(f"静态资源 app.js 返回 {values.get('STATIC')}")
    base.ok("静态资源 200")
    if values.get("AUTH") not in {"401", "403"}:
        raise base.DeployError(
            f"未鉴权的 /api/knowledge 返回 {values.get('AUTH')}，鉴权可能失效"
        )
    base.ok(f"未鉴权访问被拒（{values.get('AUTH')}）")
    if '"account_login":true' not in values.get("SESSION", ""):
        raise base.DeployError("账号登录未生效：" + values.get("SESSION", "")[:200])
    base.ok("账号登录形态正常")


def rollback(old: str, release: str) -> None:
    """把旧 app 换回并重启；不自动处理数据库。"""
    base.step("自动回滚")
    if not old:
        base.fail("没有可回滚的旧目录，需人工介入")
        return
    bad = f"{PREVIEW_ROOT}/failed/app-{release}"
    script = f"""
set -eu
APP={PREVIEW_APP}
mkdir -p {PREVIEW_ROOT}/failed
systemctl stop {PREVIEW_SERVICE} || true
if [ -e "$APP" ]; then mv "$APP" {bad}; fi
mv {old} "$APP"
systemctl start {PREVIEW_SERVICE}
i=0
while [ $i -lt 40 ]; do
  STATE=$(systemctl is-active {PREVIEW_SERVICE})
  if [ "$STATE" = "active" ]; then echo "SERVICE=active"; exit 0; fi
  if [ "$STATE" = "failed" ]; then echo "SERVICE=failed"; exit 1; fi
  i=$((i+1)); sleep 2
done
echo "SERVICE=timeout"
exit 1
"""
    code, out = run_remote(script, timeout=300)
    if code != 0 or "SERVICE=active" not in out:
        base.fail(f"回滚失败，需人工介入：\n{out[-800:]}")
        return
    ver = remote_version()
    base.ok(f"已换回 {old}（线上 v{ver}）")


def prune(keep: int) -> None:
    """保留最近 N 个旧 app；失败只告警，不影响已成功的新版本。"""
    try:
        code, out = run_remote(f"""
set -eu
cd {PREVIEW_ROOT}/previous
COUNT=0
for name in $(ls -1dt app-* 2>/dev/null); do
  COUNT=$((COUNT+1))
  if [ $COUNT -gt {keep} ]; then rm -rf -- "$name"; echo "PRUNED $name"; fi
done
cd {PREVIEW_ROOT}/failed 2>/dev/null || exit 0
COUNT=0
for name in $(ls -1dt app-* 2>/dev/null); do
  COUNT=$((COUNT+1))
  if [ $COUNT -gt 1 ]; then rm -rf -- "$name"; echo "PRUNED_FAILED $name"; fi
done
# staging 只在部署过程中使用；成功后清空，避免失败残留长期占盘。
cd {PREVIEW_ROOT}/staging
find . -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} +
echo "STAGING_CLEARED"
""", timeout=180)
    except Exception as exc:  # noqa: BLE001 - 清理是收尾动作
        base.warn(f"旧目录清理异常：{type(exc).__name__}: {exc}")
        return
    if code != 0:
        base.warn("旧目录清理失败：" + out.strip()[-200:])
        return
    pruned = [line for line in out.splitlines() if line.startswith("PRUNED")]
    print(f"  已清理 {len(pruned)} 个旧目录" if pruned else "  无需清理旧目录")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只预检并打印计划（默认行为）")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只做 dry-run）")
    parser.add_argument("--confirm", metavar="RELEASE", help="release 名，或 HEAD 表示当前提交")
    parser.add_argument("--keep-previous", type=int, default=2, metavar="N",
                        help="成功后保留的旧 app 个数（默认 2）")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run 与 --apply 不能同时使用")

    print("=" * 60)
    print("8771 隔离测试环境部署" + ("" if args.apply else "（DRY-RUN，不做任何修改）"))
    print("=" * 60)

    try:
        info = preflight()
    except base.DeployError as exc:
        base.fail(str(exc))
        return 1

    if not args.apply:
        base.step("计划")
        print(f"  目标版本：v{info['local_version']}")
        print(f"  当前环境：v{info['running_version']}（测试环境 :{PREVIEW_PORT}）")
        print(f"  数据基线：{info['records']} 记录 / {info['versions']} 历史 / {info['vectors']} 向量")
        print(f"  将要部署：{base.head_commit()}")
        print("  将执行：打包 -> staging 构建 -> 停服换位 -> 启动 -> 验证 -> 清理旧目录")
        print("  失败时自动换回旧 app（数据库不在本脚本内变更）")
        print("\n确认无误后执行：")
        print("  python scripts/deploy_preview_isolated.py --apply --confirm HEAD")
        return 0

    pkg, release = base.make_package()
    expected = release if args.confirm == "HEAD" else args.confirm
    if expected != release:
        base.fail(f"--confirm 必须是 HEAD 或完整 release 名：{release}")
        return 1

    old = ""
    try:
        stage = deploy(pkg, release)
        old = swap(stage, release)
        start_service()
        verify(info)
    except base.DeployError as exc:
        base.fail(str(exc))
        rollback(old, release)
        return 1
    except Exception as exc:  # noqa: BLE001 - 任何异常都必须触发回滚
        base.fail(f"{type(exc).__name__}: {exc}")
        rollback(old, release)
        return 1

    prune(args.keep_previous)

    base.step("完成")
    base.ok(f"测试环境已是 v{info['local_version']}（{release}）")
    print(f"  地址：https://{base.HOST}:{PREVIEW_PORT}/")
    print("  回滚：把 /var/lib/shilie-preview/previous/app-<release> 换回 app 并重启")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
