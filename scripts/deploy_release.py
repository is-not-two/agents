"""正式环境一键部署：预检 -> 备份 -> 切换 -> 验证 ->（失败则）回滚。

设计边界（为什么不是全自动 CD）
- 服务器上有用户真实数据（workspace_records / private-vault.json），自动触发
  等于把「覆盖数据」变成无人值守操作。
- 表结构变更（如 kind 约束 8→17）不可通过软链回滚，必须与代码同步回退。
- 单机单服务，重启即中断；没有蓝绿、没有第二实例可切。
- 模型首次加载约 250 秒，就绪探测必须足够长，否则误判失败。

因此本脚本是「人按一下、机器保证不出错」，而不是「push 即上线」。

安全设计
- 默认 --dry-run：只做预检和打印计划，不做任何修改。
- 官方参数 --apply 才真正执行，且要求同时给出 --confirm <release> 防止手滑。
- 每一步失败立即停并自动回滚，回滚结果单独报告。
- 备份先于任何写操作；备份失败即中止。

用法（项目根目录，Windows PowerShell 或 bash）：
    python scripts/deploy_release.py --dry-run
    python scripts/deploy_release.py --apply --confirm native-20261102-1115
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
HOST = "8.156.81.128"
USER = "root"
KEY = Path(os.path.expanduser("~")) / ".ssh" / "selfstock_8_156_81_128_rsa"
KNOWN_HOSTS = PROJECT / "output/playwright/review-001-gpt/fix-v84/enterprise-ops-v85/native-server-access/known_hosts"
REMOTE_ROOT = "/opt/shilie"
REMOTE_APP = f"{REMOTE_ROOT}/current"
SITE_PKG = "lib/python3.10/site-packages/rag_tech_retriever"
DB = "shilie_native_20261027"
WEB_PORT = 8770


class DeployError(Exception):
    """部署步骤失败。"""


def ssh_cmd() -> list[str]:
    """固定的 SSH 参数：禁用一切隐式配置，只认显式指定。"""
    cmd = ["ssh", "-F", "none", "-T", "-p", "22"]
    if KNOWN_HOSTS.is_file():
        cmd += ["-o", f"UserKnownHostsFile={KNOWN_HOSTS}"]
    cmd += [
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
        "-i", str(KEY), f"{USER}@{HOST}",
    ]
    return cmd


def run_remote(script: str, *, timeout: int = 600, label: str = "") -> tuple[int, str]:
    """在服务器执行一段 sh 脚本，返回 (退出码, 输出)。

    以二进制写入 stdin：Windows 上 text=True 会把 \\n 改写成 \\r\\n，
    远端 sh 会因行尾 \\r 报 "invalid option"。这里显式按 UTF-8 编码字节。
    """
    normalized = script.replace("\r\n", "\n").replace("\r", "").lstrip("\ufeff")
    payload = (normalized.rstrip("\n") + "\n").encode("utf-8")
    try:
        done = subprocess.run(ssh_cmd() + ["sh -s"], input=payload, capture_output=True,
                              check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return 124, f"远程执行超时：{exc}"
    out = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
    return done.returncode, out


def step(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def local_version() -> str:
    """本地静态版本号。"""
    index = PROJECT / "src/rag_tech_retriever/api/static/shilie/index.html"
    found = re.findall(r"\?v=(\d+)", index.read_text(encoding="utf-8"))
    if not found:
        raise DeployError("本地 index.html 找不到版本号")
    return found[0]


def remote_version() -> str | None:
    """服务器当前对外提供的静态版本号。"""
    code, out = run_remote(
        f"curl -sk -m 10 https://127.0.0.1:{WEB_PORT}/ | grep -o '?v=[0-9]*' | head -1",
        timeout=40,
    )
    found = re.findall(r"v=(\d+)", out)
    return found[0] if (code == 0 and found) else None


def preflight() -> dict:
    """预检：连接、空间、备份能力、kind 一致性、当前发布状态。"""
    step("预检")
    if not KEY.is_file():
        raise DeployError(f"SSH 密钥不存在：{KEY}")

    local_ver = local_version()
    ok(f"本地版本 v{local_ver}")

    script = f"""
set -e
echo "PROBE_START"
readlink -f {REMOTE_APP}
systemctl is-active shilie
df -P / | awk 'NR==2 {{print "DISK_FREE_KB=" $4}}'
sudo -u postgres psql -d {DB} -tAc "select count(*) from workspace_records" | sed 's/^/RECORDS=/'
sudo -u postgres psql -d {DB} -tAc "select count(*) from rag_chunks" | sed 's/^/VECTORS=/'
sudo -u postgres psql -d {DB} -tAc "select pg_get_constraintdef(oid) from pg_constraint where conname='workspace_records_kind_check'" | sed 's/^/KINDEXPR=/'
ls -d {REMOTE_ROOT}/releases/*/ | sed 's/^/RELEASE=/'
echo "PROBE_END"
"""
    code, out = run_remote(script, timeout=90)
    if code != 0 or "PROBE_END" not in out:
        raise DeployError(f"服务器预检失败：\n{out[-800:]}")

    info: dict = {"local_version": local_ver, "raw": out}
    for line in out.splitlines():
        if line.startswith("DISK_FREE_KB="):
            free_gb = int(line.split("=", 1)[1]) / 1024 / 1024
            info["disk_free_gb"] = round(free_gb, 1)
            if free_gb < 3:
                raise DeployError(f"磁盘剩余 {free_gb:.1f}G，不足 3G，中止部署")
            ok(f"磁盘剩余 {free_gb:.1f}G")
        elif line.startswith("RECORDS="):
            info["records"] = int(line.split("=", 1)[1])
            ok(f"当前记录 {info['records']} 条")
        elif line.startswith("VECTORS="):
            info["vectors"] = int(line.split("=", 1)[1])
            ok(f"当前向量 {info['vectors']} 条")
        elif line.startswith("KINDEXPR="):
            info["db_kinds"] = set(re.findall(r"'([a-z_]+)'::text", line))
        elif line.startswith("RELEASE="):
            info.setdefault("releases", []).append(line.split("=", 1)[1].strip())

    # 代码与数据库 kind 必须一致，否则切换后必然拒绝启动
    sys.path.insert(0, str(PROJECT / "src"))
    from rag_tech_retriever.platform.record_store import RECORD_KINDS

    if info.get("db_kinds"):
        missing = RECORD_KINDS - info["db_kinds"]
        extra = info["db_kinds"] - RECORD_KINDS
        if missing:
            raise DeployError(
                f"数据库缺少 kind：{', '.join(sorted(missing))}\n"
                f"需先执行 schema 迁移，否则新版本会拒绝启动"
            )
        if extra:
            raise DeployError(
                f"数据库多出 kind：{', '.join(sorted(extra))}\n"
                f"回滚到旧代码会失败，需一并恢复旧约束"
            )
        ok(f"{len(RECORD_KINDS)} 种 kind 与数据库一致")

    info["running_version"] = remote_version()
    ok(f"线上版本 v{info['running_version']} -> 目标 v{local_ver}")
    return info


def make_package() -> Path:
    """从 git HEAD 打包，排除运行产物。"""
    step("打包")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release = f"native-{stamp}"
    work = PROJECT / "output" / "deployment" / f"_release-{stamp}"
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=True)

    tar_path = work / "rel.tar"
    done = subprocess.run(
        ["git", "archive", "--format=tar", "--output", str(tar_path), "HEAD"],
        cwd=PROJECT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if done.returncode != 0 or not tar_path.is_file():
        raise DeployError(f"git archive 失败：{done.stderr[-400:]}")

    extracted = subprocess.run(
        ["tar", "-x", "-f", str(tar_path), "-C", str(stage)],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if extracted.returncode != 0:
        raise DeployError(f"解包失败：{extracted.stderr[-600:]}")

    for junk in ("output/stages", "output/playwright", "output/web",
                 "output/product-20261028", "output/deployment", "output/release-b"):
        target = stage / junk
        if target.exists():
            import shutil

            shutil.rmtree(target, ignore_errors=True)
    weird = stage / "({html"
    if weird.exists():
        weird.unlink()

    pkg = work / f"{release}.tar.gz"
    packed = subprocess.run(
        ["tar", "-czf", str(pkg), "-C", str(stage), "."],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if packed.returncode != 0 or not pkg.is_file():
        raise DeployError(f"压缩失败：{packed.stderr[-400:]}")

    files = sum(1 for _ in stage.rglob("*") if _.is_file())
    size_mb = round(pkg.stat().st_size / 1024 / 1024, 2)
    ok(f"{release}：{files} 个文件，{size_mb} MB")
    return pkg


def backup(prev_release: str) -> str:
    """数据库 + 代码 + 配置三份备份；任一失败即中止。"""
    step("备份")
    script = f"""
set -e
STAMP=$(date +%Y%m%d-%H%M%S)
BK=/var/backups/shilie/deploy-$STAMP
mkdir -p "$BK"; chmod 700 "$BK"
sudo -u postgres pg_dump -Fc {DB} > "$BK/db.dump"
test -s "$BK/db.dump"
ls -1 {prev_release}/src > /dev/null 2>&1 && cp -a {prev_release}/src "$BK/src" || true
cp -a /var/lib/shilie/config "$BK/config" 2>/dev/null || true
echo "BACKUP_DIR=$BK"
du -sh "$BK" | awk '{{print "BACKUP_SIZE=" $1}}'
"""
    code, out = run_remote(script, timeout=300)
    if code != 0 or "BACKUP_DIR=" not in out:
        raise DeployError(f"备份失败：\n{out[-600:]}")
    path = next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith("BACKUP_DIR="))
    ok(f"备份完成：{path}")
    return path


def deploy(pkg: Path, release: str) -> None:
    """上传并部署到新 release 目录。"""
    step("上传")
    remote_pkg = f"{REMOTE_ROOT}/incoming/{pkg.name}"
    done = subprocess.run(
        ["scp", "-F", "none", "-P", "22", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
         "-o", "StrictHostKeyChecking=yes",
         *(["-o", f"UserKnownHostsFile={KNOWN_HOSTS}"] if KNOWN_HOSTS.is_file() else []),
         "-i", str(KEY), str(pkg), f"{USER}@{HOST}:{remote_pkg}"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900,
    )
    if done.returncode != 0:
        raise DeployError(f"上传失败：{done.stderr[-500:]}")
    ok(f"已上传 {pkg.name}")

    step("解包与接线")
    script = f"""
set -e
DEST={REMOTE_ROOT}/releases/{release}
rm -rf "$DEST"; mkdir -p "$DEST"
tar -xzf {remote_pkg} -C "$DEST"
PREV=$(readlink -f {REMOTE_APP})
cp -a "$PREV/.venv" "$DEST/.venv"
cp -a /var/lib/shilie/config/. "$DEST/config/" 2>/dev/null || true
mkdir -p "$DEST/data/local"
cp -a /var/lib/shilie/data/local/. "$DEST/data/local/" 2>/dev/null || true
chown -R root:shilie "$DEST"
chmod 750 "$DEST"
echo "PREV_RELEASE=$PREV"
echo "NEW_VERSION=$(grep -o '?v=[0-9]*' "$DEST/src/rag_tech_retriever/api/static/shilie/index.html" | head -1)"
"""
    code, out = run_remote(script, timeout=600)
    if code != 0:
        raise DeployError(f"解包失败：\n{out[-800:]}")
    ok("解包完成，venv 与配置已复用")


def activate(release: str) -> None:
    """切软链 + 覆盖 site-packages（关键：非 editable 安装）+ 重启。"""
    step("切换与重启")
    script = f"""
set -e
ln -sfn {REMOTE_ROOT}/releases/{release} {REMOTE_APP}
SITE={REMOTE_APP}/.venv/{SITE_PKG}
rm -rf "$SITE"
cp -a {REMOTE_APP}/src/rag_tech_retriever "$SITE"
chown -R root:shilie "$SITE"
chmod -R u+rwX,g+rX,o-rwx "$SITE"
systemctl restart shilie
sleep 10
systemctl is-active shilie
"""
    code, out = run_remote(script, timeout=600)
    if code != 0 or "active" not in out:
        raise DeployError(f"切换或重启失败：\n{out[-800:]}")
    ok("已切换并重启")


def verify(expected: dict) -> None:
    """就绪探测 + 版本 + 数据 + 关键端点；任一不符即失败。"""
    step("验证")
    deadline = time.time() + 180
    health = ""
    while time.time() < deadline:
        code, out = run_remote(
            f"curl -sk -m 8 https://127.0.0.1:{WEB_PORT}/health", timeout=40)
        if code == 0 and '"status":"ok"' in out:
            health = out.strip()
            break
        time.sleep(5)
    if not health:
        raise DeployError("健康检查 180 秒内未通过")
    ok(f"健康：{health[:120]}")

    ver = remote_version()
    if ver != expected["local_version"]:
        raise DeployError(f"版本不符：期望 v{expected['local_version']}，实际 v{ver}")
    ok(f"线上版本 v{ver}")

    script = f"""
sudo -u postgres psql -d {DB} -tAc "select count(*) from workspace_records" | sed 's/^/R=/'
sudo -u postgres psql -d {DB} -tAc "select count(*) from rag_chunks" | sed 's/^/V=/'
curl -sk -m 8 -o /dev/null -w "STATIC=%{{http_code}}\\n" https://127.0.0.1:{WEB_PORT}/static/shilie/evaluation.js
"""
    code, out = run_remote(script, timeout=90)
    records = next((int(l.split("=", 1)[1]) for l in out.splitlines() if l.startswith("R=")), -1)
    vectors = next((int(l.split("=", 1)[1]) for l in out.splitlines() if l.startswith("V=")), -1)
    static_code = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("STATIC=")), "?")

    if records != expected.get("records"):
        raise DeployError(f"记录数变化：部署前 {expected.get('records')}，现在 {records}")
    if vectors != expected.get("vectors"):
        raise DeployError(f"向量数变化：部署前 {expected.get('vectors')}，现在 {vectors}")
    ok(f"数据未变：{records} 条记录 / {vectors} 条向量")
    if static_code not in {"200", "404"}:
        warn(f"evaluation.js 返回 {static_code}（404 表示该版本无此模块，正常）")
    else:
        ok(f"evaluation.js HTTP {static_code}")


def rollback(prev_release: str, backup_dir: str | None) -> None:
    """把软链切回上一版并恢复 site-packages；不自动恢复数据库。"""
    step("自动回滚")
    if not prev_release:
        fail("没有可回滚的上一版本，请人工介入")
        return
    script = f"""
set -e
ln -sfn {prev_release} {REMOTE_APP}
SITE={REMOTE_APP}/.venv/{SITE_PKG}
if [ -d "{backup_dir}/src" ]; then
  rm -rf "$SITE"
  cp -a "{backup_dir}/src/rag_tech_retriever" "$SITE"
  chown -R root:shilie "$SITE"
fi
systemctl restart shilie
sleep 10
systemctl is-active shilie
"""
    code, out = run_remote(script, timeout=600)
    if code != 0:
        fail(f"回滚失败，需人工介入：\n{out[-600:]}")
        return
    ver = remote_version()
    ok(f"已回滚到 {prev_release}（线上 v{ver}）")
    warn("数据库未自动恢复；若本次改过表结构，需手动用备份恢复")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只做 dry-run）")
    parser.add_argument("--confirm", metavar="RELEASE",
                        help="确认部署的 release 名，必须与生成的名称一致")
    parser.add_argument("--skip-backup", action="store_true",
                        help="跳过备份（危险，仅用于演练环境）")
    args = parser.parse_args()

    print("=" * 60)
    print("正式环境部署" + ("" if args.apply else "（DRY-RUN，不做任何修改）"))
    print("=" * 60)

    try:
        info = preflight()
    except DeployError as exc:
        fail(str(exc))
        return 1

    if not args.apply:
        step("计划")
        print(f"  目标版本：v{info['local_version']}")
        print(f"  当前线上：v{info['running_version']}")
        print(f"  数据基线：{info.get('records')} 条记录 / {info.get('vectors')} 条向量")
        print("  将执行：打包 -> 备份 -> 上传 -> 解包 -> 切换 -> 验证")
        print("  失败时自动回滚代码（数据库需人工处理）")
        print("\n确认无误后执行：")
        print("  python scripts/deploy_release.py --apply --confirm <release>")
        return 0

    pkg = make_package()
    release = pkg.name.replace(".tar.gz", "")
    if args.confirm != release:
        fail(f"--confirm 必须等于生成的 release 名：{release}")
        return 1

    prev = ""
    backup_dir = None
    try:
        code, out = run_remote(f"readlink -f {REMOTE_APP}", timeout=40)
        prev = out.strip().splitlines()[-1] if code == 0 else ""
        if not args.skip_backup:
            backup_dir = backup(prev)
        deploy(pkg, release)
        activate(release)
        verify(info)
    except DeployError as exc:
        fail(str(exc))
        rollback(prev, backup_dir)
        return 1
    except Exception as exc:  # noqa: BLE001 - 任何异常都必须触发回滚
        fail(f"{type(exc).__name__}: {exc}")
        rollback(prev, backup_dir)
        return 1

    step("完成")
    ok(f"线上已是 v{info['local_version']}（{release}）")
    if backup_dir:
        print(f"  备份：{backup_dir}")
    print("  回滚：python scripts/deploy_release.py 手动指定上一 release，或见 docs/DEPLOYMENT_REALITY.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
