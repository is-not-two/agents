"""把 OpenCode 接成执行器：走它的 HTTP 服务，不走会卡住的 CLI。

为什么不用 `opencode run`：在本机实测它初始化后一直停在 epoll，60 秒超时也没有输出；
而 `opencode serve` + `/session/{id}/message` 3 秒就返回。所以固定用服务模式：
一条常驻进程 + 每个任务一个 session。

分工不变：它负责改，我们的循环负责门禁、绿点、回退、预算、绕过校验扫描。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from rag_tech_retriever.platform.coding_loop import GIT_SAFE


class OpenCodeError(RuntimeError):
    """调用 opencode 服务失败。"""


class OpenCodeAttempt:
    """一轮 = 建一个 session，发一条带失败反馈的消息，等它返回。"""

    def __init__(self, config: dict, root: Path, task: str, *,
                 binary: str = "opencode", host: str = "127.0.0.1", port: int = 4096,
                 base_url: str = "", home: str = "", readonly: Sequence[str] = (),
                 timeout: int = 300, opener: Callable[[str, str, dict | None], dict] | None = None,
                 launcher: Callable[..., subprocess.Popen] | None = None,
                 log_path: str = "/tmp/shilie-opencode.log",
                 supervisor: str = "", supervisor_script: str = "") -> None:
        self.config = dict(config)
        self.root = Path(root).resolve()
        self.task = task
        self.binary = binary
        self.host, self.port = host, port
        self.base_url = base_url.rstrip("/")
        self.home = home
        self.readonly = tuple(item.strip("/\\") for item in readonly if item.strip())
        self.timeout = timeout
        self.opener = opener or self._http
        self.launcher = launcher
        self.supervisor = supervisor
        self.supervisor_script = supervisor_script
        self.unit = ""
        self.poll_interval = 2.0
        self.log_path = log_path
        self._log_handle = None
        self.pid = 0
        self.server: subprocess.Popen | None = None
        self.last_reply = ""

    # ---------- 服务 ----------

    def _http(self, url: str, method: str = "GET", payload: dict | None = None,
              timeout: float | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            # 健康探测用短超时；业务请求才用长超时。
            effective = timeout or (3 if url.endswith("/doc") else self.timeout)
            with urllib.request.urlopen(request, timeout=effective) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise OpenCodeError(f"opencode 返回 {exc.code}：{exc.read()[:300]!r}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise OpenCodeError(f"连不上 opencode 服务：{exc}") from exc
        return json.loads(body) if body.strip() else {}

    def _probe(self) -> None:
        """健康探测走注入的客户端；真实实现内部对 /doc 用短超时。

        服务器还没起来时，长超时会把整个预算一次耗光（这次最坑的一个 bug）。
        """
        self.opener(self.base_url + "/doc")

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def ensure_server(self) -> str:
        if not self.base_url:
            # 端口必须独占：复用到别的实例会把改动写到它的工作目录里去（实测踩过）。
            if not self.port:
                self.port = self._free_port()
            self.base_url = f"http://{self.host}:{self.port}"
        try:
            self._probe()
            return self.base_url
        except OpenCodeError:
            pass
        if self.supervisor == "systemd" and self.supervisor_script:
            self._start_via_supervisor()
        else:
            self._start_inline()

        deadline = time.monotonic() + 90
        last = ""
        while time.monotonic() < deadline:
            try:
                self._probe()
                if not self._serves_our_directory():
                    raise OpenCodeError(f"端口 {self.port} 被别的目录占用")
                return self.base_url
            except OpenCodeError as exc:
                last = str(exc)
                time.sleep(0.5)
        raise OpenCodeError(f"opencode serve 90 秒内没有就绪（{last}）")

    def _start_via_supervisor(self) -> None:
        """交给 systemd-run 起，循环只记单元名。"""
        result = subprocess.run(
            [self.supervisor_script, "start", str(self.root), str(self.port),
             self.home or str(Path.home()), self.binary],
            capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise OpenCodeError(f"systemd-run 启动失败：{result.stderr.strip()[:200]}")
        self.unit = (result.stdout or "").strip().splitlines()[-1] if result.stdout else ""
        shown = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", self.unit],
                               capture_output=True, text=True, timeout=20, check=False)
        try:
            self.pid = int((shown.stdout or "0").strip() or 0)
        except ValueError:
            self.pid = 0

    def _start_inline(self) -> None:
        """退路：自己脱离式起进程（实测不总能成，所以默认不用）。"""
        env = dict(os.environ)
        if self.home:
            env["HOME"] = self.home
        if self.log_path:
            self._log_handle = open(self.log_path, "ab")  # noqa: SIM115 - 子进程存活期间保持打开
            sink = self._log_handle
        else:
            sink = subprocess.DEVNULL
        try:
            self.server = subprocess.Popen(
                [self.binary, "serve", "--hostname", self.host, "--port", str(self.port)],
                cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
                stdout=sink, stderr=sink, start_new_session=True)
            self.pid = self.server.pid
        except OSError as exc:
            raise OpenCodeError(f"启动 opencode 失败：{exc}") from exc

    def _serves_our_directory(self) -> bool:
        """用 /proc 核对进程工作目录，防止连到别的项目留下的服务。"""
        if not self.pid or not Path("/proc").is_dir():
            return True
        try:
            cwd = Path(f"/proc/{self.pid}/cwd").resolve()
        except OSError:
            return True     # 进程已退出：交给 /doc 探测去判断
        return cwd == self.root

    def close(self) -> None:
        if self.unit and self.supervisor_script:
            subprocess.run([self.supervisor_script, "stop", str(self.root)],
                           capture_output=True, timeout=30, check=False)
            self.unit = ""
        self.poll_interval = 2.0
        if self.pid:
            subprocess.run(["kill", "-TERM", str(self.pid)], capture_output=True, check=False)
            self.pid = 0
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - 兜底
                self.server.kill()
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

    # ---------- 一次尝试 ----------

    def prompt(self, feedback: str) -> str:
        message = self.task
        if feedback:
            message += "\n\n上一轮校验没有通过，错误输出如下，请针对性修掉：\n" + feedback[-1500:]
        if self.readonly:
            message += "\n\n不要修改这些路径（测试、门禁、依赖）：" + "、".join(self.readonly)
        return message

    def attempt(self, context) -> None:
        base = self.ensure_server()
        session = self.opener(base + "/session", "POST", {"title": f"auto round {context.round_no}"})
        session_id = session.get("id")
        if not session_id:
            raise OpenCodeError("没有拿到 session id")
        payload = {
            "model": {"providerID": "openai", "modelID": self.config["model"]},
            "parts": [{"type": "text", "text": self.prompt(context.feedback)}],
        }
        # 异步提交后不要看「是否 busy」：刚提交时状态可能还是空闲，会被误判成已结束。
        # 正确的判据是「出现了一条已完成的助手消息」。
        self.opener(f"{base}/session/{session_id}/prompt_async", "POST", payload)
        deadline = time.monotonic() + self.timeout
        reply: dict = {}
        while time.monotonic() < deadline:
            messages = self.opener(f"{base}/session/{session_id}/message")
            reply = self._last_assistant(messages)
            if reply.get("info", {}).get("time", {}).get("completed"):
                break
            reply = {}
            time.sleep(self.poll_interval)
        if not reply:
            raise OpenCodeError(f"等待模型超过 {self.timeout} 秒仍未结束")
        cwd = str(reply.get("info", {}).get("path", {}).get("cwd") or "")
        if cwd and Path(cwd).resolve() != self.root:
            # 服务跑在别的目录 → 改动会落在错误的地方，宁可整轮失败。
            raise OpenCodeError(f"服务工作目录是 {cwd}，不是副本 {self.root}")
        self.last_reply = self._text_of(reply)
        blocked = self._touched_readonly()
        if blocked:
            raise OpenCodeError("修改了只读路径：" + "、".join(blocked[:4]))
        context.tried.append(self.last_reply[:160] or f"round {context.round_no}")

    @staticmethod
    def _last_assistant(messages: list) -> dict:
        for message in reversed(messages or []):
            if str(message.get("info", {}).get("role") or "") == "assistant":
                return message
        return {}

    @staticmethod
    def _text_of(reply: dict) -> str:
        chunks = [part.get("text", "") for part in reply.get("parts", [])
                  if part.get("type") == "text"]
        return "\n".join(chunk for chunk in chunks if chunk).strip()

    def _touched_readonly(self) -> list[str]:
        result = subprocess.run([*GIT_SAFE, "status", "--porcelain"], cwd=self.root,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=60, check=False)
        names = []
        for line in (result.stdout or "").splitlines():
            name = line[3:].strip()
            if " -> " in name:
                name = name.split(" -> ")[-1]
            if name and any(name == item or name.startswith(item + "/")
                            for item in self.readonly):
                names.append(name)
        return names
