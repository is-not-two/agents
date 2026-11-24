"""Local clamd INSTREAM adapter: only an exact clean verdict permits release."""
import socket
import struct
import time
from typing import Literal

Verdict = Literal["clean", "rejected", "pending"]


def scan_payload(blob: bytes, socket_path: str, timeout: float = 5.0) -> Verdict:
    """Leave unavailable, malformed, or indeterminate scans quarantined."""
    if not 0 < len(blob) <= 1048576 or not socket_path or timeout <= 0:
        return "pending"
    deadline = time.monotonic() + timeout
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            def remaining() -> None:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    raise TimeoutError()
                sock.settimeout(budget)
            remaining()
            sock.connect(socket_path)
            sock.sendall(b"zINSTREAM\0")
            for start in range(0, len(blob), 65536):
                chunk = blob[start:start + 65536]
                remaining()
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            remaining()
            sock.sendall(bytes(4))
            reply = bytearray()
            while len(reply) < 1024 and 0 not in reply:
                remaining()
                part = sock.recv(1024 - len(reply))
                if not part:
                    return "pending"
                reply.extend(part)
            if reply == b"stream: OK\0":
                return "clean"
            if reply.startswith(b"stream: ") and reply.endswith(b" FOUND\0") and reply.count(0) == 1:
                return "rejected"
    except (OSError, AttributeError):
        pass
    return "pending"


def scan_one(transaction, socket_path: str, timeout: float = 5.0) -> str:
    """Process at most one immutable blob. Caller supplies scanner-role transactions.

    Locked jobs are skipped. On an indeterminate result stop the batch and retry
    after backoff rather than treating service downtime as a clean verdict.
    """
    with transaction() as cursor:
        cursor.execute("""SELECT a.id,c.payload FROM community.attachments a
            JOIN community.attachment_content c ON c.attachment_id=a.id
            WHERE a.scan_state='pending' ORDER BY a.id
            FOR UPDATE OF a SKIP LOCKED LIMIT 1""")
        row = cursor.fetchone()
        if row is None:
            return "idle"
        verdict = scan_payload(bytes(row["payload"]), socket_path, timeout)
        if verdict in {"clean", "rejected"}:
            cursor.execute("""UPDATE community.attachments SET scan_state=%s
                WHERE id=%s AND scan_state='pending'""", (verdict, row["id"]))
            if cursor.rowcount != 1:
                raise RuntimeError("扫描结果与待处理附件未匹配")
        return verdict
