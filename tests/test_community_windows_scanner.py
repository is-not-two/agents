"""Fail-closed Windows attachment scanning contract; no malware samples."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import rag_tech_retriever.platform.community_windows_scanner as scanner


class WindowsScannerContract(unittest.TestCase):
    def test_empty_oversize_and_expired_do_not_launch(self):
        with patch.object(scanner.subprocess,"run") as run:
            for blob,timeout in [(b"",30),(b"x"*1048577,30),(b"x",0)]:
                self.assertEqual(scanner.scan_windows_payload(blob,timeout),"pending")
            run.assert_not_called()

    def test_missing_engine_does_not_release(self):
        with patch.object(Path,"glob",return_value=iter(())),patch.object(scanner.subprocess,"run") as run:
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"pending")
            run.assert_not_called()

    def test_unhealthy_or_untrusted_engine_does_not_scan(self):
        with patch.object(scanner.subprocess,"run",return_value=subprocess.CompletedProcess([],1)) as run:
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"pending")
            self.assertEqual(run.call_count,1)

    def test_nonzero_result_is_not_a_clean_or_malware_assertion(self):
        with patch.object(scanner.subprocess,"run",side_effect=[
            subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],2)]) as run:
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"pending")
            self.assertIn("-DisableRemediation",run.call_args.args[0])

    def test_timeout_remains_quarantined(self):
        with patch.object(scanner.subprocess,"run",side_effect=subprocess.TimeoutExpired("scan",1)):
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"pending")

    def test_changed_bytes_cannot_be_released_even_with_exit_zero(self):
        def run(args,**kw):
            if "-File" in args:
                Path(args[args.index("-File")+1]).write_bytes(b"changed")
            return subprocess.CompletedProcess(args,0)
        with patch.object(scanner.subprocess,"run",side_effect=run):
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"pending")

    def test_unchanged_success_is_clean(self):
        with patch.object(scanner.subprocess,"run",return_value=subprocess.CompletedProcess([],0)):
            self.assertEqual(scanner.scan_windows_payload(b"controlled test"),"clean")

if __name__=="__main__":unittest.main()
