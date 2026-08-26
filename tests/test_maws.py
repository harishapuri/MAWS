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
