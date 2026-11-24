"""Diagnostic arithmetic and query-only Windows process handles; no remote traffic."""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from community_burst_diagnostics import (
    run_parallel_with_cpu,
    run_with_cpu,
    server_delta,
    split_native_configs,
    stage_summary,
)


class BurstDiagnosticContract(unittest.TestCase):
    def test_shards_preserve_all_requests_once_and_parallel_capacity(self):
        command = ["curl.exe", "--parallel-max", "300", "--config", "-"]
        configs = ["url = https://example.invalid/" + str(n) for n in range(300)]
        tasks = split_native_configs(command, "\nnext\n".join(configs), 3)
        self.assertEqual(len(tasks), 3)
        self.assertEqual([row for _, data in tasks for row in data.split("\nnext\n")], configs)
        self.assertEqual([task[0][2] for task in tasks], ["100", "100", "100"])
        with self.assertRaises(ValueError):
            split_native_configs(command, "\nnext\n".join(configs[:100]), 3)

    @unittest.skipUnless(os.name == "nt", "Win32 query handles")
    def test_synchronized_processes_finish_with_combined_output(self):
        tasks = [([sys.executable, "-c", "print(123)"], "") for _ in range(3)]
        result, metrics = run_parallel_with_cpu(tasks, 5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("123"), 3)
        self.assertEqual(metrics["load_processes"], 3)
        self.assertLess(metrics["dispatch_skew_ms"], 100)
        self.assertGreaterEqual(metrics["curl_average_cpus"], 0)

    def test_stage_percentiles_are_differences_per_request(self):
        rows = [
            {"status": 200, "exit": 0, "tcp": 0, "tls": 9, "first": 10, "total": 11},
            {"status": 200, "exit": 0, "tcp": 8, "tls": 8, "first": 8, "total": 8},
        ]
        result = stage_summary(rows)
        self.assertEqual(result["successful_samples"], 2)
        self.assertEqual(result["p95_ms"]["tls_only"], 9000)
        self.assertEqual(result["p95_ms"]["request_after_tls"], 1000)
        self.assertEqual(result["p95_ms"]["body_after_first"], 1000)

    def test_failed_samples_explicitly_excluded_only_from_stage_attribution(self):
        self.assertEqual(stage_summary([{"status": 0, "exit": 7}]), {"successful_samples": 0})

    def test_host_delta_and_boot_identity(self):
        before = {
            "boot_id": "a",
            "network": {"Tcp.RetransSegs": 10},
            "cpu_total": 400,
            "cpu_idle": 200,
            "monotonic": 0,
        }
        after = {
            "boot_id": "a",
            "network": {"Tcp.RetransSegs": 12},
            "cpu_total": 600,
            "cpu_idle": 300,
            "monotonic": 2,
        }
        result = server_delta(before, after)
        self.assertEqual(result["cpu_busy_pct"], 50)
        self.assertEqual(result["network_counter_deltas"]["Tcp.RetransSegs"], 2)
        self.assertIn("not per-port", result["scope"])
        with self.assertRaises(ValueError):
            server_delta(before, {**after, "boot_id": "b"})

    @unittest.skipUnless(os.name == "nt", "Win32 query handles")
    def test_completed_child_timing_and_output(self):
        result, metrics = run_with_cpu([sys.executable, "-c", "print(123)"], "", 5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "123")
        self.assertGreaterEqual(metrics["curl_user_seconds"], 0)
        self.assertGreaterEqual(metrics["client_host_busy_pct"], 0)
        self.assertLessEqual(metrics["client_host_busy_pct"], 100)

    @unittest.skipUnless(os.name == "nt", "Win32 query handles")
    def test_timed_out_child_is_terminated(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_with_cpu([sys.executable, "-c", "import time;time.sleep(30)"], "", 0.1)
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
