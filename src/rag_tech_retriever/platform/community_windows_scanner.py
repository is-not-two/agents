"""Opt-in Windows scan adapter. Nonzero results stay quarantined.

Does not change Defender cloud/sample-submission policy. Deployment must approve
that policy before scanning user content. This module never starts a daemon.
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

MAX_BYTES = 1048576


def scan_windows_payload(blob: bytes, timeout: float = 30.0) -> str:
    """Only a successful no-remediation scan of unchanged bytes is clean."""
    if os.name != "nt" or not 0 < len(blob) <= MAX_BYTES or timeout <= 0:
        return "pending"
    deadline = time.monotonic()+timeout
    try:
        platform = Path(os.environ.get("ProgramData", "C:/ProgramData"))/"Microsoft/Windows Defender/Platform"
        candidates = sorted(platform.glob("*/MpCmdRun.exe"), reverse=True)
        if not candidates:
            return "pending"
        executable = candidates[0]
        env = {k:v for k,v in os.environ.items() if k.upper() != "PSMODULEPATH"}
        env["COMMUNITY_SCANNER_BINARY"] = str(executable)
        ps = (
            "$ErrorActionPreference='Stop';"
            "$s=Get-MpComputerStatus;"
            "$a=Get-AuthenticodeSignature -LiteralPath $env:COMMUNITY_SCANNER_BINARY;"
            "if(!$s.AntivirusEnabled -or !$s.RealTimeProtectionEnabled -or "
            "$a.Status -ne 'Valid' -or "
            "((Get-Date)-$s.AntivirusSignatureLastUpdated).TotalHours -gt 48){exit 1}"
        )
        flags = subprocess.CREATE_NO_WINDOW
        powershell = Path(os.environ["SystemRoot"])/"System32/WindowsPowerShell/v1.0/powershell.exe"
        check = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", ps],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=max(.1,deadline-time.monotonic()), creationflags=flags,
                               check=False)
        if check.returncode or time.monotonic() >= deadline:
            return "pending"
        with tempfile.TemporaryDirectory(prefix="shilie-scan-") as folder:
            target = Path(folder)/"quarantined-upload.bin"
            target.write_bytes(blob)
            result = subprocess.run([str(executable), "-Scan", "-ScanType", "3",
                                     "-File", str(target), "-DisableRemediation"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=max(.1,deadline-time.monotonic()), creationflags=flags,
                                    check=False)
            # Defender's code 2 conflates a detection with a scan error: never
            # assert "malware" from that code, and never release those bytes.
            if result.returncode == 0 and target.read_bytes() == blob:
                return "clean"
    except (OSError, subprocess.SubprocessError):
        pass
    return "pending"
