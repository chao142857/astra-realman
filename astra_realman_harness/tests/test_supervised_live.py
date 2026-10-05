"""Fake-only tests of the live dispatch boundary. Never loads the SDK."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from io_utils import ROOT
import supervised_live as live

class LiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-live-boundary-", dir=ROOT/"logs")
        self.run = Path(self.temp.name)
        self.calls = []
        self.handle = object()
        def fake_step(*args):
            self.calls.append(args)
            return 0
        self.session = SimpleNamespace(
            connected={"left": SimpleNamespace(handle=self.handle)},
            connection_info={"left": {"ip": "192.168.1.19"}},
            sdk=SimpleNamespace(rm_set_pos_step=fake_step))
        self.port = live.SupervisedPort(self.session, self.run, execute=True)
        self.port.evidence = {"prechecks": [{"arms": {"left": {"marker": "fresh synthetic state"}}}]}
        self.good = dict(axis=2, step_m=.01, speed_percent=1, block=1)
        self.guard = patch.object(live, "validate_step", return_value={"outcome": "PASS_EXECUTABLE", "errors": []})
        self.logs = patch.object(live, "write_json")
        self.claim = patch.object(live, "durable_claim")
        self.guard.start(); self.logs.start(); self.claim.start()

    def tearDown(self):
        self.claim.stop(); self.logs.stop(); self.guard.stop(); self.temp.cleanup()

    def test_exact_command_only_and_at_most_once(self):
        self.assertEqual(self.port.position_step(**self.good), 0)
        self.assertEqual(self.calls, [(self.handle, 2, .01, 1, 1)])
        self.assertEqual(self.port.hardware_calls_attempted, 1)
        with self.assertRaises(RuntimeError):
            self.port.position_step(**self.good)
        self.assertEqual(len(self.calls), 1)

    def test_default_readonly_and_every_argument_override_denied(self):
        self.port.execute_enabled = False
        with self.assertRaises(RuntimeError):
            self.port.position_step(**self.good)
        self.port.execute_enabled = True
        for change in ({"axis": 1}, {"axis": True}, {"step_m": .001}, {"step_m": -.01},
                       {"step_m": float("nan")}, {"speed_percent": 2},
                       {"speed_percent": True}, {"block": 0}, {"block": True}):
            with self.subTest(change=change):
                with self.assertRaises(RuntimeError):
                    self.port.position_step(**dict(self.good, **change))
        self.assertEqual(self.calls, [])

    def test_rejection_claim_conflict_or_wrong_ip_never_dispatches(self):
        with patch.object(live, "validate_step", return_value={"outcome": "REJECT", "errors": ["STALE"]}):
            with self.assertRaises(RuntimeError):
                self.port.position_step(**self.good)
        with patch.object(live, "durable_claim", side_effect=FileExistsError("consumed")):
            with self.assertRaises(FileExistsError):
                self.port.position_step(**self.good)
        self.session.connection_info["left"]["ip"] = "192.168.1.18"
        with self.assertRaises(RuntimeError):
            self.port.position_step(**self.good)
        self.assertEqual(self.calls, [])

    def test_sdk_exception_consumes_attempt_before_return(self):
        def fake_raise(*args):
            self.calls.append(args)
            raise TimeoutError("may have been accepted")
        self.session.sdk.rm_set_pos_step = fake_raise
        with self.assertRaises(TimeoutError):
            self.port.position_step(**self.good)
        self.assertEqual(self.port.hardware_calls_attempted, 1)
        with self.assertRaises(RuntimeError):
            self.port.position_step(**self.good)
        self.assertEqual(len(self.calls), 1)

    def test_state_expiring_during_claim_or_logging_never_reaches_sdk(self):
        results = [{"outcome": "PASS_EXECUTABLE", "errors": []},
                   {"outcome": "REJECT", "errors": ["STALE_STATE"]}]
        with patch.object(live, "validate_step", side_effect=results):
            with self.assertRaisesRegex(RuntimeError, "STATE_EXPIRED_AFTER_DURABLE_CLAIM"):
                self.port.position_step(**self.good)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.port.hardware_calls_attempted, 0)

    def test_durable_claim_is_exclusive_and_wrong_path_denied(self):
        self.claim.stop()
        path = self.run/"fixed.claim.json"
        with patch.object(live, "CLAIM", path):
            live.durable_claim(path, {"scope": "synthetic test"})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                live.durable_claim(path, {"scope": "second synthetic test"})
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                live.durable_claim(self.run/"other.json", {})
        self.claim.start()

if __name__ == "__main__":
    unittest.main()
