"""MAWS hive agents must fire; fused picks must not drift."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from maws.bootstrap import UNIFIED_ROOT  # noqa: E402
from maws.catalog import EXPECTED, STORIES  # noqa: E402
from maws.supervisor import AGENTS, iter_maws  # noqa: E402

from framework.audit import AuditChain  # noqa: E402


class SupervisorHive(unittest.TestCase):
    def test_agents_declared(self) -> None:
        self.assertIn("Supervisor", AGENTS)
        self.assertIn("CrcAgent", AGENTS)

    def test_pass_allow_via_maws(self) -> None:
        checkov, telemetry, service, _ = STORIES["pass"]
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        events = list(iter_maws(checkov, telemetry, AuditChain(Path(tmp.name)), service=service))
        gate = next(e for e in events if e["stage"] == "gate")
        self.assertEqual(gate["agent"], "DsaAgent")
        self.assertEqual((gate["detail"]["dsa"], gate["detail"]["action"]), EXPECTED["pass"])
        self.assertEqual(events[-1]["detail"]["governance"]["orchestrator"], "maws")

    def test_fail_compensates_blue(self) -> None:
        checkov, telemetry, service, _ = STORIES["fail"]
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        events = list(iter_maws(checkov, telemetry, AuditChain(Path(tmp.name)), service=service))
        comp = next(e for e in events if e["stage"] == "compensate")
        self.assertTrue(comp["detail"]["blue_stays_live"])


class AutomateStories(unittest.TestCase):
    def test_all_stories_match_expected(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "maws.automate"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["passed"])
        self.assertEqual(len(payload["stories"]), 7)


def _post_automate(handler_cls, payload: dict) -> tuple[int, dict]:
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/scan",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return int(resp.status), json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"raw": raw}
            return int(exc.code), body
    finally:
        httpd.shutdown()
        httpd.server_close()


class AutomateHttpPost(unittest.TestCase):
    def test_demo_handler_implements_do_post(self) -> None:
        from maws.demo import DemoHandler  # noqa: E402

        self.assertTrue(callable(getattr(DemoHandler, "do_POST", None)))

    def test_post_scan_uncloneable_is_json_never_501(self) -> None:
        from maws.demo import DemoHandler  # noqa: E402

        status, body = _post_automate(
            DemoHandler, {"git_url": "/no/such/git/repo", "ref": "main", "path": "."}
        )
        self.assertNotEqual(status, 501, body)
        self.assertIn(status, (200, 400, 500), body)
        self.assertIsInstance(body, dict)
        self.assertIn("error", body)
