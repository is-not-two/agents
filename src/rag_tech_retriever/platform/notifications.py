"""持久通知 outbox：先领取后外发，模糊结果不盲重试，凭据不入记录。"""
from __future__ import annotations

import hashlib
import smtplib
import ssl
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.headerregistry import Address
from email.message import EmailMessage

from rag_tech_retriever.common.config_loader import ConfigLoader
from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.record_store import RecordMissing, RecordStore, VersionConflict


def _address(value: str) -> str:
    if not value or any(c in value for c in "\r\n"):
        raise DomainError("SMTP 地址缺失或包含非法字符")
    try:
        parsed = Address(addr_spec=value)
        if not parsed.username or not parsed.domain:
            raise ValueError
    except ValueError as exc:
        raise DomainError("SMTP 地址格式不正确") from exc
    return value


class NotificationService:
    """同一自然日最多一个摘要意图，SMTP 接受不等于手机/收件箱已送达。"""

    def __init__(self, store: RecordStore, env=None, clock=None) -> None:
        self.store = store
        self.env = env or store.config.env
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        config = ConfigLoader(store.config.settings_path.parent / "notifications.yaml")
        self.policy = config.get("notifications", {})
        bounds = {"timezone_offset_minutes": (-720, 840), "max_attempts": (1, 10),
                  "retry_base_seconds": (1, 86400), "claim_stale_seconds": (120, 86400),
                  "smtp_timeout_seconds": (1, 30), "batch_limit": (1, 50), "preview_item_limit": (1, 100)}
        for key, (low, high) in bounds.items():
            value = self.policy.get(key)
            if type(value) is not int or not low <= value <= high:
                raise DomainError("通知配置无效：" + key)
        enabled = str(self.env("NOTIFY_ENABLED", str(self.policy.get("enabled", False)))).lower()
        if enabled not in {"true", "false"}:
            raise DomainError("NOTIFY_ENABLED 仅支持 true/false")
        self.enabled = enabled == "true"

    def public(self) -> dict:
        """只返回配置是否齐备，不返回地址、账号、主机、密码或异常原文。"""
        return {"enabled": self.enabled, "channel": "smtp", "configured": all(self.env(k, "") for k in ("SMTP_HOST", "SMTP_FROM", "SMTP_TO")),
                "timezone_offset_minutes": self.policy["timezone_offset_minutes"],
                "delivery_semantics": "sent 表示 SMTP 已接受；不证明收件箱或手机已收到"}

    def _smtp(self) -> dict:
        if not self.enabled:
            raise DomainError("通知发送尚未启用；队列内容未发送")
        host = str(self.env("SMTP_HOST", "")).strip()
        if not host or len(host) > 253 or any(c.isspace() for c in host):
            raise DomainError("请设置有效 SMTP_HOST")
        mode = str(self.env("SMTP_SECURITY", "starttls"))
        if mode not in {"starttls", "tls", "local-test"}:
            raise DomainError("SMTP_SECURITY 仅支持 starttls/tls；隔离测试可用 local-test")
        if mode == "local-test" and host != "127.0.0.1":
            raise DomainError("明文 SMTP 仅允许显式 local-test 的 127.0.0.1")
        try:
            port = int(self.env("SMTP_PORT", "465" if mode == "tls" else "587"))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError as exc:
            raise DomainError("SMTP_PORT 无效") from exc
        user, password = self.env("SMTP_USER", ""), self.env("SMTP_PASSWORD", "")
        if bool(user) != bool(password):
            raise DomainError("SMTP 账号和密码必须成对配置")
        return {"host": host, "port": port, "mode": mode, "user": user, "password": password,
                "sender": _address(self.env("SMTP_FROM", "")), "recipient": _address(self.env("SMTP_TO", ""))}

    def preview(self) -> dict:
        """只读取到期卡片和跟进任务，摘要不包含答案、私密日记或模型内容。"""
        now = self.clock().astimezone(timezone.utc)
        with self.store.transaction() as cur:
            cur.execute(f"SELECT id,kind,data FROM {self.store.records} WHERE deleted=FALSE AND kind=ANY(%s) ORDER BY id", (["learning_card", "application"],))
            rows = cur.fetchall()
        cards = [row for row in rows if row["kind"] == "learning_card" and not row["data"]["paused"] and row["data"]["due_at"] <= now.isoformat()]
        jobs = [row for row in rows if row["kind"] == "application" and row["data"]["status"] not in {"offered", "rejected"} and row["data"]["follow_up_at"] and row["data"]["follow_up_at"] <= now.isoformat()]
        local = now.astimezone(timezone(timedelta(minutes=self.policy["timezone_offset_minutes"])))
        day = local.date().isoformat()
        limit = self.policy["preview_item_limit"]
        first = jobs[0] if jobs else cards[0] if cards else None
        lines = [f"时列今日摘要 {day}", f"待跟进 {len(jobs)} 条，待复习 {len(cards)} 张。"]
        if first:
            lines += ["今天先处理：" + first["data"]["title"] + "（按已到期任务排序，非 AI 推测）"]
        lines += ["", "待跟进：", *["- " + row["data"]["title"] for row in jobs[:limit]], "", "待复习：", *["- " + row["data"]["title"] for row in cards[:limit]]]
        if len(jobs) > limit or len(cards) > limit:
            lines += [f"每类最多展示 {limit} 项，完整清单请回工作区查看。"]
        return {"date": day, "title": "时列今日摘要 " + day, "body": "\n".join(lines)[:16000],
                "counts": {"followups": len(jobs), "reviews": len(cards)}, "as_of": now.isoformat()}

    def enqueue_daily(self) -> dict:
        """稳定操作 ID 不带 attempt；多次 cron 或重复确认复用原消息。"""
        preview = self.preview()
        operation = "daily:" + preview["date"]
        return self._enqueue(preview, operation)

    def enqueue_weekly(self, report: dict) -> dict:
        """内部已生成的纯统计周报入队，不接受外部任意收件人与消息。"""
        return self._enqueue({"title": "时列周报 " + report["week_start"], "body": report["markdown"][:16000]}, "weekly:" + report["week_start"])

    def _enqueue(self, preview: dict, operation: str) -> dict:
        """每日/每周各自冻结消息和操作身份，不因重试或模型换用而重发。"""
        record_id = "notify-" + hashlib.sha256(operation.encode()).hexdigest()
        with self.store.transaction() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.store.prefix + ":notifications",))
            cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (record_id,))
            old = cur.fetchone()
            if old:
                if old["kind"] != "notification_outbox":
                    raise VersionConflict("通知操作 ID 冲突")
                return {"notification": self.store._serialize(old), "reused": True}
            data = {"title": preview["title"], "body": preview["body"], "operation_id": operation,
                    "channel": "smtp", "status": "pending", "attempts": 0, "attempt_limit": self.policy["max_attempts"],
                    "next_attempt_at": self.clock().isoformat(), "claimed_at": "", "last_error": "", "retryable": False,
                    "resolution": "", "smtp_accepted": False}
            return {"notification": self.store._save(cur, "notification_outbox", data, record_id, None), "reused": False}

    def listing(self) -> dict:
        """外发状态与配置提示可见；消息记录不含 SMTP 凭据。"""
        return {"notifications": self.store.list("notification_outbox", limit=100), "settings": self.public()}

    def _claim(self) -> dict | None:
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.store.records} WHERE kind='notification_outbox' AND deleted=FALSE "
                        "AND (data->>'status'='pending' OR (data->>'status'='failed' AND data->>'retryable'='true')) "
                        "AND (data->>'attempts')::int < (data->>'attempt_limit')::int "
                        "AND data->>'next_attempt_at' <= %s ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1", (self.clock().isoformat(),))
            row = cur.fetchone()
            if row is None:
                return None
            data = {**row["data"], "status": "sending", "claimed_at": self.clock().isoformat(), "attempts": row["data"]["attempts"] + 1}
            return self.store._save(cur, "notification_outbox", data, row["id"], row["version"])

    def recover_stale(self) -> int:
        """崩溃或未记账发送只转 unknown，禁止当成失败自动重发。"""
        cutoff = (self.clock() - timedelta(seconds=self.policy["claim_stale_seconds"])).isoformat()
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.store.records} WHERE kind='notification_outbox' AND deleted=FALSE AND data->>'status'='sending' AND data->>'claimed_at'<=%s FOR UPDATE SKIP LOCKED", (cutoff,))
            rows = cur.fetchall()
            for row in rows:
                self.store._save(cur, "notification_outbox", {**row["data"], "status": "unknown", "last_error": "发送进程中断，结果未知；核对收件结果前不会自动重试", "retryable": False}, row["id"], row["version"])
        return len(rows)

    def _send(self, row: dict, config: dict) -> tuple[str, str, bool]:
        message = EmailMessage()
        message["Subject"] = row["data"]["title"]
        message["From"], message["To"] = config["sender"], config["recipient"]
        message["Message-ID"] = "<" + row["id"] + "@shilie.local>"
        message.set_content(row["data"]["body"])
        smtp = None
        sending = False
        try:
            factory = smtplib.SMTP_SSL if config["mode"] == "tls" else smtplib.SMTP
            kwargs = {"timeout": self.policy["smtp_timeout_seconds"]}
            if config["mode"] == "tls":
                kwargs["context"] = ssl.create_default_context()
            smtp = factory(config["host"], config["port"], **kwargs)
            if config["mode"] == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if config["user"]:
                smtp.login(config["user"], config["password"])
            sending = True
            refused = smtp.send_message(message)
            if refused:
                return "failed", "SMTP 拒绝收件地址", False
            return "sent", "", False
        except smtplib.SMTPAuthenticationError:
            return "failed", "SMTP 鉴权失败，请检查配置后显式重试", False
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
            return "failed", "SMTP 拒绝发件人或收件人", False
        except smtplib.SMTPDataError as exc:
            return "failed", "SMTP 明确拒绝消息内容", 400 <= exc.smtp_code < 500
        except (OSError, smtplib.SMTPException):
            return ("unknown", "SMTP 外发连接中断，结果未知；不会自动重试", False) if sending else ("failed", "SMTP 连接或握手失败，未发消息正文", True)
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except OSError:
                    pass  # Closing cannot turn a known result into an unrecorded send.

    def dispatch(self, limit: int | None = None) -> dict:
        """有限批次执行；配置失败不领取，领取成功后持久化每次结果。"""
        config = self._smtp()
        limit = self.policy["batch_limit"] if limit is None else limit
        if type(limit) is not int or not 1 <= limit <= 50:
            raise DomainError("发送批次必须为 1–50")
        recovered = self.recover_stale()
        results = []
        for _ in range(limit):
            row = self._claim()
            if row is None:
                break
            status, error, retryable = self._send(row, config)
            data = deepcopy(row["data"])
            data.update(status=status, last_error=error, retryable=retryable, smtp_accepted=status == "sent",
                        next_attempt_at=(self.clock() + timedelta(seconds=self.policy["retry_base_seconds"] * 2 ** min(data["attempts"] - 1, 10))).isoformat())
            results.append(self.store.save("notification_outbox", data, row["id"], row["version"]))
        return {"processed": results, "recovered_unknown": recovered}

    def resolve(self, record_id: str, version: int, action: str, confirmation: str) -> dict:
        """未知结果只有人工核对后才可处理；sent/sending 不支持盲目重放。"""
        if confirmation != "已核对通知结果":
            raise DomainError("请先核对发送结果并明确确认")
        with self.store.transaction() as cur:
            cur.execute(f"SELECT * FROM {self.store.records} WHERE id=%s FOR UPDATE", (record_id,))
            row = cur.fetchone()
            if row is None or row["kind"] != "notification_outbox" or row["deleted"]:
                raise RecordMissing("通知记录不存在")
            if row["version"] != version:
                raise VersionConflict("通知状态已变化，请重新读取")
            data = deepcopy(row["data"])
            if action == "retry" and data["status"] in {"failed", "unknown"}:
                data.update(status="pending", next_attempt_at=self.clock().isoformat(), attempt_limit=data["attempts"] + self.policy["max_attempts"],
                            resolution="用户核对未发送后显式允许重试", retryable=False, last_error="")
            elif action == "received" and data["status"] == "unknown":
                data.update(status="sent", resolution="用户人工核对已收到；不是 SMTP 回执证明")
            elif action == "cancel" and data["status"] in {"pending", "failed"}:
                data.update(status="cancelled", resolution="用户取消了未确认发送的通知", retryable=False)
            else:
                raise VersionConflict("当前通知状态不允许此操作；发送中或已提交 SMTP 的消息不能盲重发")
            return self.store._save(cur, "notification_outbox", data, record_id, version, "notification:" + action)
