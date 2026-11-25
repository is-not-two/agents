"""Read-only host/process diagnostics, separate from the unchanged burst gate."""

import ctypes
import json
import math
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from threading import Barrier

SNAPSHOT = r"""
from pathlib import Path
import json,time
def counters(path,names):
 lines=Path(path).read_text().splitlines();result={}
 for i in range(0,len(lines),2):
  keys=lines[i].split();values=lines[i+1].split()
  for key,value in zip(keys[1:],values[1:]):
   if key in names:result[keys[0].rstrip(':')+'.'+key]=int(value)
 return result
net=counters('/proc/net/netstat',{'ListenOverflows','ListenDrops','TCPReqQFullDoCookies','TCPReqQFullDrop','TCPSynRetrans','TCPTimeouts'})
net.update(counters('/proc/net/snmp',{'RetransSegs','PassiveOpens','ActiveOpens','AttemptFails','EstabResets'}))
cpu=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
print(json.dumps({'network':net,'cpu_total':sum(cpu),'cpu_idle':cpu[3]+cpu[4],
 'monotonic':time.monotonic(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}))
"""


def server_snapshot(remote):
    return json.loads(remote("python3 -", SNAPSHOT))


def server_delta(before, after):
    if before["boot_id"] != after["boot_id"]:
        raise ValueError("server restarted during diagnostic window")
    total = after["cpu_total"] - before["cpu_total"]
    idle = after["cpu_idle"] - before["cpu_idle"]
    return {
        "scope": "whole server, includes SSH and other services; not per-port attribution",
        "window_seconds": round(after["monotonic"] - before["monotonic"], 3),
        "cpu_busy_pct": round(100 * (total - idle) / total, 2) if total else None,
        "network_counter_deltas": {
            key: value - before["network"][key] for key, value in after["network"].items()
        },
    }


def stage_summary(rows):
    valid = [row for row in rows if row["status"] == 200 and row["exit"] == 0]
    if not valid:
        return {"successful_samples": 0}
    samples = {key: [] for key in ("tcp", "tls_only", "request_after_tls", "body_after_first")}
    for row in valid:
        assert 0 <= row["tcp"] <= row["tls"] <= row["first"] <= row["total"]
        samples["tcp"].append(row["tcp"])
        samples["tls_only"].append(row["tls"] - row["tcp"])
        samples["request_after_tls"].append(row["first"] - row["tls"])
        samples["body_after_first"].append(row["total"] - row["first"])
    return {
        "successful_samples": len(valid),
        "p95_ms": {
            key: round(sorted(values)[math.ceil(0.95 * len(values)) - 1] * 1000, 1)
            for key, values in samples.items()
        },
    }


def application_summary(remote, prefix):
    if not re.fullmatch(r"curl-cap-[a-f0-9]{32}-(100|200|300)-[0-9]+(?:-write-(?:posts|reviews|withdraw))?", prefix):
        raise ValueError("invalid diagnostic request prefix")
    script = (
        "prefix="
        + repr(prefix + "-")
        + r"""
import subprocess,json,math
lines=subprocess.check_output(['journalctl','-u','shilie-preview','--since','5 min ago','--no-pager','-o','cat'],text=True).splitlines()
rows=[]
for line in lines:
 try:value=json.loads(line)
 except ValueError:continue
 if str(value.get('request_id','')).startswith(prefix):rows.append(value)
times=sorted(row['elapsed_ms'] for row in rows)
print(json.dumps({'matched':len(rows),'p95_ms':times[math.ceil(.95*len(times))-1] if times else None,
 'max_ms':max(times) if times else None,'status_counts':{str(code):sum(row['status']==code for row in rows) for code in {row['status'] for row in rows}}}))
"""
    )
    return json.loads(remote("python3 -", script))


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    def ticks(self):
        return self.low + (self.high << 32)


class _WindowsTimes:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(_FileTime)] * 4
        self.api.GetProcessTimes.restype = wintypes.BOOL
        self.api.GetSystemTimes.argtypes = [ctypes.POINTER(_FileTime)] * 3
        self.api.GetSystemTimes.restype = wintypes.BOOL

    def system(self):
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        if not self.api.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return idle.ticks(), kernel.ticks() + user.ticks()

    def process(self, handle):
        created, exited, kernel, user = _FileTime(), _FileTime(), _FileTime(), _FileTime()
        if not self.api.GetProcessTimes(
            handle, *(ctypes.byref(x) for x in (created, exited, kernel, user))
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return kernel.ticks() / 10000000, user.ticks() / 10000000


def run_with_cpu(command, data, timeout, *, barrier=None):
    """Keep only a query-information handle; config/cookies stay in the stdin pipe."""
    if os.name != "nt":
        raise RuntimeError("native Windows diagnostic requires Windows")
    api = _WindowsTimes()
    before_idle, before_total = api.system()
    started = time.perf_counter()
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    handle = None
    try:
        handle = api.api.OpenProcess(0x1000, False, process.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if barrier is not None:
            barrier.wait(timeout=5)
        dispatched = time.perf_counter()
        out, err = process.communicate(data, timeout=timeout)
        elapsed = time.perf_counter() - started
        kernel, user = api.process(handle)
        after_idle, after_total = api.system()
        total = after_total - before_total
        metrics = {
            "curl_kernel_seconds": round(kernel, 4),
            "curl_user_seconds": round(user, 4),
            "curl_average_cpus": round((kernel + user) / elapsed, 3),
            "client_host_busy_pct": round(100 * (total - (after_idle - before_idle)) / total, 2)
            if total
            else None,
        }
        if barrier is not None:
            metrics["_dispatch"] = dispatched
        return subprocess.CompletedProcess(command, process.returncode, out, err), metrics
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.communicate()
        raise
    finally:
        if handle:
            api.api.CloseHandle(handle)


def split_native_configs(command, data, shards):
    """Partition all requests once; each process starts only after the common gate."""
    configs = data.split("\nnext\n")
    if shards not in (1, 3) or len(configs) % shards:
        raise ValueError("diagnostic shard count must divide the exact request count")
    width = len(configs) // shards
    tasks = []
    for index in range(shards):
        child_command = list(command)
        child_command[child_command.index("--parallel-max") + 1] = str(width)
        tasks.append((child_command, "\nnext\n".join(configs[index * width : (index + 1) * width])))
    return tasks


def run_parallel_with_cpu(tasks, timeout):
    """Independent load generators, not a change to server or rate limits."""
    if not 1 <= len(tasks) <= 3:
        raise ValueError("at most three diagnostic load processes")
    api = _WindowsTimes()
    before_idle, before_total = api.system()
    started = time.perf_counter()
    barrier = Barrier(len(tasks))
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [
            pool.submit(run_with_cpu, command, data, timeout, barrier=barrier)
            for command, data in tasks
        ]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started
    after_idle, after_total = api.system()
    total = after_total - before_total
    dispatches = [metrics.pop("_dispatch") for _, metrics in results]
    kernel = sum(metrics["curl_kernel_seconds"] for _, metrics in results)
    user = sum(metrics["curl_user_seconds"] for _, metrics in results)
    status = next((result.returncode for result, _ in results if result.returncode), 0)
    combined = subprocess.CompletedProcess(
        [command for command, _ in tasks],
        status,
        "".join(result.stdout for result, _ in results),
        "".join(result.stderr for result, _ in results),
    )
    return combined, {
        "load_processes": len(tasks),
        "dispatch_skew_ms": round((max(dispatches) - min(dispatches)) * 1000, 3),
        "curl_kernel_seconds": round(kernel, 4),
        "curl_user_seconds": round(user, 4),
        "curl_average_cpus": round((kernel + user) / elapsed, 3),
        "client_host_busy_pct": round(100 * (total - (after_idle - before_idle)) / total, 2)
        if total
        else None,
        "processes": [metrics for _, metrics in results],
    }
