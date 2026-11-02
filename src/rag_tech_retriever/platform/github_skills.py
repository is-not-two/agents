"""Quarantined public GitHub clone -> pinned Markdown preview -> explicit skill import.

No checkout, hooks, submodules, package installation or repository code execution.
Only SKILL.md is activated; supporting scripts/resources remain unsupported here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from uuid import uuid4

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict
from rag_tech_retriever.platform.skill_registry import SkillRegistry


class GitHubSkills:
    """All subprocess arguments are separate argv entries, never shell strings."""

    def __init__(self, directory: Path, registry: SkillRegistry, limits: dict) -> None:
        self.directory, self.registry, self.limits = directory.resolve(), registry, limits

    @staticmethod
    def _size(directory: Path | None) -> int:
        total = 0
        if directory and directory.exists():
            for path in directory.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except FileNotFoundError:
                    pass  # git renames/removes temporary pack/lock files while cloning.
        return total

    @staticmethod
    def normalize_url(url: str) -> str:
        """Only public HTTPS GitHub repository URLs; no tokens, paths, local or SSH URLs."""
        match = re.fullmatch(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url)
        if not match or match[2] in {".", ".."}:
            raise DomainError("仅支持https://github.com/OWNER/REPO形式的公开仓库地址")
        return f"https://github.com/{match[1]}/{match[2]}.git"

    def _run(self, arguments: list[str], repo: Path | None = None, clone_target: Path | None = None,
             maximum: int = 1048576) -> bytes:
        git = shutil.which("git")
        if not git:
            raise DomainError("服务器未安装Git，请由管理员安装后重试")
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
                   GIT_ASKPASS="", GIT_NO_LAZY_FETCH="1", GIT_LFS_SKIP_SMUDGE="1")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        args = [git, "-c", "core.hooksPath=" + str(self.directory / "no-hooks"),
                "-c", "credential.helper=", "-c", "http.followRedirects=false",
                "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", *arguments]
        with tempfile.TemporaryFile() as output:
            try:
                proc = subprocess.Popen(args, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.DEVNULL, **options)
                started = time.monotonic()
                while proc.poll() is None:
                    size = output.seek(0, 2)
                    disk_size = self._size(clone_target)
                    if (time.monotonic() - started > self.limits.get("timeout_seconds", 60)
                            or size > maximum or disk_size > self.limits.get("max_bytes", 52428800)):
                        raise DomainError("Git克隆/读取超时或超过大小限制，已中止")
                    time.sleep(0.2)
                if proc.returncode != 0:
                    raise DomainError("GitHub克隆或读取失败；请检查公开仓库地址、分支与网络")
                if self._size(clone_target) > self.limits.get("max_bytes", 52428800):
                    raise DomainError("克隆仓库超过大小限制")
                output.seek(0)
                raw = output.read(maximum + 1)
                if len(raw) > maximum:
                    raise DomainError("仓库文件列表或技能内容超过限制")
                return raw
            finally:
                if "proc" in locals() and proc.poll() is None:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)

    def _clone(self, url: str, destination: Path, ref: str | None) -> None:
        args = ["clone", "--depth=1", "--single-branch", "--no-tags", "--no-checkout", "--template="]
        if ref:
            args.extend(["--branch", ref])
        self._run([*args, "--", url, str(destination)], clone_target=destination)

    def preview(self, repo_url: str, ref: str | None = None) -> dict:
        """Clone in a verified temporary directory and keep only a bounded text manifest."""
        url = self.normalize_url(repo_url)
        if ref and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,100}", ref) or ".." in ref):
            raise DomainError("分支或标签格式不正确")
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="clone-", dir=self.directory) as folder:
            temporary = Path(folder).resolve()
            assert temporary.is_relative_to(self.directory) and temporary != self.directory
            destination = temporary / "repo"
            self._clone(url, destination, ref)
            commit = self._run(["rev-parse", "HEAD"], destination, maximum=128).decode().strip()
            if not re.fullmatch(r"[a-f0-9]{40,64}", commit):
                raise DomainError("无法固定仓库提交版本")
            tree = self._run(["ls-tree", "-r", "-l", "-z", commit], destination)
            entries = tree.split(b"\0")
            if len(entries) > 5001:
                raise DomainError("仓库文件过多，请使用专门的技能仓库")
            skills, warnings = {}, []
            for item in entries:
                if not item:
                    continue
                info, raw_path = item.split(b"\t", 1)
                path = raw_path.decode("utf-8")
                if PurePosixPath(path).name != "SKILL.md":
                    continue
                mode, _, _, size = info.split()
                if mode != b"100644" or len(PurePosixPath(path).parts) > 8 or int(size) > self.registry.maximum:
                    warnings.append("跳过非普通文件、过深或过大的SKILL.md")
                    continue
                name = PurePosixPath(path).parent.name
                if path == "SKILL.md":
                    name = url.rsplit("/", 1)[-1].removesuffix(".git")
                try:
                    raw = self._run(["show", commit + ":" + path], destination, maximum=self.registry.maximum)
                    self.registry._path(name)
                    skill = self.registry._parse(name, raw)
                except DomainError:
                    warnings.append("跳过名称或内容不符合Agent Skills格式的技能")
                    continue
                if name in skills:
                    raise DomainError("仓库存在同名技能，请先拆分仓库")
                skills[name] = {**skill, "repository_path": path}
                if len(skills) > 32:
                    raise DomainError("一次最多预览32个技能")
        if not skills:
            raise DomainError("仓库中没有可导入的SKILL.md")
        import_id = uuid4().hex
        manifest = {"import_id": import_id, "repo_url": url, "commit": commit, "skills": skills,
                    "warnings": warnings + ["只导入SKILL.md；未执行或安装脚本、依赖、子模块与其他资源。"]}
        with (self.directory / (import_id + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False)
        return manifest

    def apply(self, import_id: str, selected: list[str]) -> dict:
        """Create-only, retryable import; never overwrite an existing different skill."""
        if not re.fullmatch(r"[a-f0-9]{32}", import_id):
            raise DomainError("导入编号格式不正确")
        path = self.directory / (import_id + ".json")
        if not path.is_file():
            raise RecordMissing("导入预览不存在")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not selected or len(selected) != len(set(selected)) or set(selected) - manifest["skills"].keys():
            raise DomainError("请选择预览中有效且不重复的技能")
        # Preflight all conflicts before publishing any new skill.
        for name in selected:
            try:
                existing = self.registry.get(name)
            except RecordMissing:
                continue
            if existing["revision"] != manifest["skills"][name]["revision"]:
                raise VersionConflict("存在不同内容的同名技能，未覆盖，请先处理冲突")
        imported = []
        for name in selected:
            skill = manifest["skills"][name]
            try:
                self.registry.save(name, skill["content"], None)
            except VersionConflict:
                if self.registry.get(name)["revision"] != skill["revision"]:
                    raise
            imported.append({"name": name, "revision": skill["revision"]})
        return {"status": "imported", "import_id": import_id, "commit": manifest["commit"],
                "skills": imported, "scripts_executed": False, "warnings": manifest["warnings"]}
