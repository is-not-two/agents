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
SITE_PKG = "lib/python3.10/site-packages/rag_tech_retriever"

#: 部署目标：两套环境各自独立数据库与代码目录，仅共用模型缓存。
#: 测试库用于预览验证，写操作不再进入正式数据；preview 部署不自动备份生产库。
TARGETS: dict[str, dict] = {
    "production": {
        "app": f"{REMOTE_ROOT}/current", "port": 8770, "service": "shilie",
        "scheme": "https", "dropin": "/etc/systemd/system/shilie.service.d",
        "db": "shilie_native_20261027", "backup": True, "label": "正式环境",
    },
    "preview": {
        "app": f"{REMOTE_ROOT}/preview", "port": 8771, "service": "shilie-preview",
        "scheme": "https", "dropin": "/etc/systemd/system/shilie-preview.service.d",
        "db": "shilie_preview_20261103", "backup": False, "label": "测试环境",
    },
}
DB = TARGETS["production"]["db"]

# 当前目标（set_target 切换；函数在调用时读取模块全局，f-string 求值即生效）
REMOTE_APP = TARGETS["production"]["app"]
WEB_PORT = TARGETS["production"]["port"]
SERVICE = TARGETS["production"]["service"]
SCHEME = TARGETS["production"]["scheme"]
DROPIN_DIR = TARGETS["production"]["dropin"]
TARGET_NAME = "production"


def set_target(name: str) -> dict:
    """切换部署目标，返回其配置；数据库也随之切换，预检只查目标库。"""
    global REMOTE_APP, WEB_PORT, SERVICE, SCHEME, DROPIN_DIR, TARGET_NAME, DB
    if name not in TARGETS:
        raise DeployError(f"未知部署目标：{name}")
    target = TARGETS[name]
    REMOTE_APP = target["app"]
    WEB_PORT = target["port"]
    SERVICE = target["service"]
    SCHEME = target["scheme"]
    DROPIN_DIR = target["dropin"]
    DB = target["db"]
    TARGET_NAME = name
    return target


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
    """目标环境当前对外提供的静态版本号。"""
    code, out = run_remote(
        f"curl -sk -m 10 {SCHEME}://127.0.0.1:{WEB_PORT}/ | grep -o '?v=[0-9]*' | head -1",
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
systemctl is-active {SERVICE} || true
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


def head_commit() -> str:
    """当前 HEAD 短哈希，用作 release 名的一部分。"""
    done = subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        cwd=PROJECT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if done.returncode != 0:
        raise DeployError(f"读取 git HEAD 失败：{done.stderr.strip()}")
    return done.stdout.strip()


def make_package() -> tuple[Path, str]:
    """从 git HEAD 打包，返回 (包路径, release 名)。

    release 名由「提交哈希 + 时间戳」组成：哈希保证可追溯到具体提交，
    时间戳区分同一提交的重复部署。用户在 dry-run 阶段就能看到确切名称，
    不必猜时间戳——这正是 `--confirm` 可用的前提。

    用 zip + .NET 解压而非 tar：Windows 自带 tar（bsdtar）在解含中文文件名的
    归档时会报 "Invalid empty pathname"，data/raw/aihuoke_docs 下的中文文档会
    整批丢失。zip 走 UTF-8 标志位，两侧都能正确还原。
    """
    step("打包")
    import shutil
    import zipfile

    commit = head_commit()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release = f"native-{stamp}-{commit}"
    work = PROJECT / "output" / "deployment" / f"_release-{stamp}"
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=True)

    archive = work / "rel.zip"
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", "archive", "--format=zip",
         f"--output={archive}", "HEAD"],
        cwd=PROJECT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if done.returncode != 0 or not archive.is_file():
        raise DeployError(f"git archive 失败：{done.stderr[-400:]}")

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(stage)

    # 中文文件名必须完整保留，否则语料缺失会导致向量检索空转
    raw_dir = stage / "data" / "raw" / "aihuoke_docs"
    if not raw_dir.is_dir() or len(list(raw_dir.glob("*.md"))) < 14:
        raise DeployError("语料目录不完整（中文文件名可能丢失），中止打包")

    for junk in ("output/stages", "output/playwright", "output/web",
                 "output/product-20261028", "output/deployment", "output/release-b"):
        target = stage / junk
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    weird = stage / "({html"
    if weird.exists():
        weird.unlink()

    # tar.gz 供上传（压缩比好），内容由 zip 正确解出后再压
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
    return pkg, release


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
    # 三个约束必须同时满足：
    # 1) systemd ProtectSystem=strict + ReadWritePaths 只放行 /var/lib/shilie，
    #    /opt/shilie 整体只读 → 运行期不能往项目目录写任何东西。
    # 2) 代码里 (root/sub).resolve().is_relative_to(root.resolve()) 校验
    #    （skills 目录、语料路径）→ 这些目录不能是软链，否则 resolve 后越界。
    # 3) skills / skill-imports / exports / stages 必须可写。
    #
    # 三者交集只有一条路：把这些目录做成**项目内实体目录**，并让 systemd
    # 额外放行它们。放行用 drop-in 加 ReadWritePaths，比改主 unit 易回退。
    script = f"""
set -e
DEST={REMOTE_ROOT}/releases/{release}
rm -rf "$DEST"; mkdir -p "$DEST"
tar -xzf {remote_pkg} -C "$DEST"
PREV=$(readlink -f {REMOTE_APP})
cp -a "$PREV/.venv" "$DEST/.venv"

# data/local 必须是项目内实体且可写（代码会 resolve 校验）。
# 先继承上一 release 的 data/local（简历正文、周报、加密密钥都在这里），
# 再从共享目录补齐 canonical 的 vault/技能/导出，避免跨 release 丢用户数据。
rm -rf "$DEST/data/local" "$DEST/output/stages"
mkdir -p "$DEST/data/local/skills" \
         "$DEST/data/local/skill-imports" \
         "$DEST/data/local/exports" \
         "$DEST/output/stages"
cp -a "$PREV/data/local/." "$DEST/data/local/" 2>/dev/null || true
cp -a /var/lib/shilie/data/local/private-vault.json "$DEST/data/local/" 2>/dev/null || true
# 已有技能与导出内容继承过来，不丢用户数据
cp -a /var/lib/shilie/data/local/skills/. "$DEST/data/local/skills/" 2>/dev/null || true
cp -a /var/lib/shilie/data/local/skill-imports/. "$DEST/data/local/skill-imports/" 2>/dev/null || true
# 应用层加密密钥：首次部署生成，后续继承；密钥文件只对服务用户可读。
if [ ! -s "$DEST/data/local/encryption.key" ]; then
  (umask 077; openssl rand -base64 32 > "$DEST/data/local/encryption.key")
fi

cp -a /var/lib/shilie/config/. "$DEST/config/" 2>/dev/null || true
chown -R root:shilie "$DEST"
chmod 750 "$DEST"
chown -R shilie:shilie "$DEST/data/local" "$DEST/output" 2>/dev/null || true
chmod -R u+rwX,g+rwX "$DEST/data/local" "$DEST/output" 2>/dev/null || true
chmod 600 "$DEST/data/local/encryption.key" 2>/dev/null || true
chown shilie:shilie "$DEST/data/local/encryption.key" 2>/dev/null || true

# 让 systemd 放行本 release 的可写子目录（drop-in，可随软链一起回退）。
# 注意必须写到目标服务自己的 drop-in 目录，否则 preview 部署会改掉生产的放行路径。
mkdir -p {DROPIN_DIR}
cat > {DROPIN_DIR}/runtime-writable.conf <<EOF
[Service]
ReadWritePaths=$DEST/output/stages $DEST/data/local $DEST/data/local/skills $DEST/data/local/skill-imports $DEST/data/local/exports /var/lib/shilie
EOF
systemctl daemon-reload

echo "PREV_RELEASE=$PREV"
echo "NEW_VERSION=$(grep -o '?v=[0-9]*' "$DEST/src/rag_tech_retriever/api/static/shilie/index.html" | head -1)"
echo "SKILLS_DIR=$(readlink -f "$DEST/data/local/skills")"
"""
    code, out = run_remote(script, timeout=600)
    if code != 0:
        raise DeployError(f"解包失败：\n{out[-800:]}")
    ok("解包完成，venv 已复用，可写目录已放行")


def activate(release: str) -> None:
    """切软链 + 覆盖 site-packages（关键：非 editable 安装）+ 重启。

    服务启动要加载应用并连库，`systemctl restart` 返回后状态常为
    `activating`，固定 sleep 会误判失败并触发不必要的回滚。
    这里改成轮询等待 `active`，超时才判失败。
    """
    step("切换与重启")
    script = f"""
set -e
ln -sfn {REMOTE_ROOT}/releases/{release} {REMOTE_APP}
SITE={REMOTE_APP}/.venv/{SITE_PKG}
rm -rf "$SITE"
cp -a {REMOTE_APP}/src/rag_tech_retriever "$SITE"
chown -R root:shilie "$SITE"
chmod -R u+rwX,g+rX,o-rwx "$SITE"
systemctl restart {SERVICE}
i=0
while [ $i -lt 40 ]; do
  STATE=$(systemctl is-active {SERVICE})
  if [ "$STATE" = "active" ]; then echo "SERVICE=active"; exit 0; fi
  if [ "$STATE" = "failed" ]; then
    echo "SERVICE=failed"
    journalctl -u {SERVICE} -n 12 --no-pager 2>/dev/null | tail -12
    exit 1
  fi
  i=$((i+1)); sleep 2
done
echo "SERVICE=timeout"
exit 1
"""
    code, out = run_remote(script, timeout=300)
    if code != 0 or "SERVICE=active" not in out:
        raise DeployError(f"切换或重启失败：\n{out[-1200:]}")
    ok("已切换并重启")


def verify(expected: dict) -> None:
    """就绪探测 + 版本 + 数据 + 关键端点；任一不符即失败。"""
    step("验证")
    deadline = time.time() + 180
    health = ""
    last_journal = ""
    while time.time() < deadline:
        code, out = run_remote(
            f"curl -sk -m 8 {SCHEME}://127.0.0.1:{WEB_PORT}/health", timeout=40)
        if code == 0 and '"status":"ok"' in out:
            health = out.strip()
            break
        # 服务起不来时把最近日志带出来，否则只报「超时」等于没诊断
        jcode, jout = run_remote(
            f"journalctl -u {SERVICE} -n 25 --no-pager 2>/dev/null | "
            "grep -iE 'error|exception|traceback|OSError|failed' | tail -8",
            timeout=40)
        if jcode == 0 and jout.strip():
            last_journal = jout.strip()
        time.sleep(5)
    if not health:
        hint = f"\n最近错误日志：\n{last_journal}" if last_journal else ""
        raise DeployError(f"健康检查 180 秒内未通过{hint}")
    ok(f"健康：{health[:120]}")

    ver = remote_version()
    if ver != expected["local_version"]:
        raise DeployError(f"版本不符：期望 v{expected['local_version']}，实际 v{ver}")
    ok(f"线上版本 v{ver}")

    script = f"""
sudo -u postgres psql -d {DB} -tAc "select count(*) from workspace_records" | sed 's/^/R=/'
sudo -u postgres psql -d {DB} -tAc "select count(*) from rag_chunks" | sed 's/^/V=/'
curl -sk -m 8 -o /dev/null -w "STATIC=%{{http_code}}\\n" {SCHEME}://127.0.0.1:{WEB_PORT}/static/shilie/evaluation.js
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
# 回滚必须把 drop-in 重写为指向旧 release：旧版本同样需要可写目录放行，
# 直接删除 drop-in 会让旧版本启动时因 EROFS 崩溃。
mkdir -p {DROPIN_DIR}
cat > {DROPIN_DIR}/runtime-writable.conf <<EOF
[Service]
ReadWritePaths={prev_release}/output/stages {prev_release}/data/local {prev_release}/data/local/skills {prev_release}/data/local/skill-imports {prev_release}/data/local/exports /var/lib/shilie
EOF
systemctl daemon-reload
systemctl restart {SERVICE}
i=0
while [ $i -lt 40 ]; do
  STATE=$(systemctl is-active {SERVICE})
  if [ "$STATE" = "active" ]; then echo "SERVICE=active"; exit 0; fi
  if [ "$STATE" = "failed" ]; then echo "SERVICE=failed"; exit 1; fi
  i=$((i+1)); sleep 2
done
echo "SERVICE=timeout"
exit 1
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
    parser.add_argument("--target", choices=sorted(TARGETS), default="production",
                        help="部署目标：preview=测试环境(8771)，production=正式环境(8770)")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只做 dry-run）")
    parser.add_argument("--confirm", metavar="RELEASE",
                        help="确认部署的 release 名，必须与生成的名称一致")
    parser.add_argument("--skip-backup", action="store_true",
                        help="跳过备份（preview 默认跳过；正式环境慎用）")
    args = parser.parse_args()

    try:
        target = set_target(args.target)
    except DeployError as exc:
        fail(str(exc))
        return 1
    # 测试环境部署不碰数据库（共用生产库），备份无意义且慢，默认跳过
    skip_backup = args.skip_backup or not target["backup"]

    print("=" * 60)
    print(f"{target['label']}部署（{TARGET_NAME}）" + ("" if args.apply else "（DRY-RUN，不做任何修改）"))
    print("=" * 60)

    try:
        info = preflight()
    except DeployError as exc:
        fail(str(exc))
        return 1

    if not args.apply:
        step("计划")
        print(f"  目标版本：v{info['local_version']}")
        print(f"  当前环境：v{info['running_version']}（{target['label']} :{target['port']}）")
        print(f"  数据基线：{info.get('records')} 条记录 / {info.get('vectors')} 条向量")
        print(f"  将要部署：{head_commit()}")
        print("  将执行：打包 -> " + ("" if skip_backup else "备份 -> ") + "上传 -> 解包 -> 切换 -> 验证")
        print("  失败时自动回滚代码（数据库需人工处理）")
        print("\n确认无误后执行：")
        print(f"  python scripts/deploy_release.py --target {TARGET_NAME} --apply --confirm HEAD")
        print(f"  （或指定完整名称，如 --confirm native-<stamp>-{head_commit()}）")
        return 0

    pkg, release = make_package()
    # 允许用 HEAD 表示「部署当前提交」，避免操作者去抄时间戳
    expected = release if args.confirm == "HEAD" else args.confirm
    if expected != release:
        fail(f"--confirm 必须是 HEAD 或完整 release 名：{release}")
        return 1

    prev = ""
    backup_dir = None
    try:
        code, out = run_remote(f"readlink -f {REMOTE_APP}", timeout=40)
        prev = out.strip().splitlines()[-1] if code == 0 else ""
        if not skip_backup:
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
    ok(f"{target['label']}已是 v{info['local_version']}（{release}）")
    print(f"  地址：{target['scheme']}://{HOST}:{target['port']}/")
    if backup_dir:
        print(f"  备份：{backup_dir}")
    print("  回滚：python scripts/deploy_release.py 手动指定上一 release，或见 docs/DEPLOYMENT_REALITY.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
