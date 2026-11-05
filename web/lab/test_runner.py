"""Real local Windows child-process tests; no database/device execution claims."""
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from contracts.plugins import executable_manifest
from contracts.runner_v1 import Limits, strict_json
from contracts.v1 import ContractError
from agent.process_tree import TreeError, WindowsTree
from agent.runner import run_can, run_probe, validate_output
from workloads.registry import verify_wheel
from .test_can_plugin import matching_fixture_wheel


class RunnerContractTests(unittest.TestCase):
    def test_invalid_limits_and_duplicate_json_rejected(self):
        for changes in ({"wall_seconds": float("nan")}, {"wall_seconds": True}, {"memory_mb": 1},
                        {"stdout_bytes": 20_000_000}, {"processes": 0}, {"cpu_percent": 101}, {"grace_seconds": -1}):
            with self.assertRaises(ContractError):
                replace(Limits(), **changes).validate()
        for raw in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', '{'):
            with self.assertRaises(ContractError):
                strict_json(raw)

    def test_unsupported_platform_fails_closed(self):
        with patch("agent.process_tree.os.name", "posix"), self.assertRaises(TreeError):
            WindowsTree(Limits())

    def test_unknown_probe_and_malformed_report_rejected(self):
        with self.assertRaises(ContractError):
            run_probe("powershell.exe", "unused")
        for raw in (b'{"schema_version":true}', b'{"schema_version":1,"outcome":"PASS"}'):
            with self.assertRaises(ContractError):
                validate_output(raw, probe=None, staged={}, digest="0" * 64)

    def test_changed_policy_and_invalid_error_details_rejected(self):
        from workloads.can_payload_compare import compare
        from copy import deepcopy
        base = compare(b"AA", b"AA", header_bytes=0)
        base['source'] = 'runner_probe'
        for change in ({'parameters':{'header_bytes':1}}, {'summary':None}, {'errors':[{'message':'bad'}]}):
            value = {**deepcopy(base), **change}
            with self.assertRaises((ContractError, TypeError)):
                validate_output(json.dumps(value).encode(), probe='pass', staged={'expected':b'AA','actual':b'AA'}, digest=None)


@unittest.skipUnless(os.name == "nt", "Windows Job Object integration requires Windows; Linux runner is unavailable.")
class WindowsRunnerTests(unittest.TestCase):
    def setUp(self):
        # Native gate is intentionally unavailable rather than silently weakened
        # on other OSes. Linux integration is explicitly not claimed.
        self.assertEqual(os.name, "nt", "Native runner gate requires Windows; run pure contract tests elsewhere.")
        self.root = Path(__file__).resolve().parents[2]
        self.storage = tempfile.TemporaryDirectory(prefix="b3-test-", dir=self.root / ".local")
        self.base = Path(self.storage.name).resolve()
        self.assertTrue(self.base.is_relative_to((self.root / ".local").resolve()))
        self.addCleanup(self.cleanup_owned_test_directory)
        self.counter = 0

    def cleanup_owned_test_directory(self):
        # Only the exact owned diagnostic file can be made writable for test
        # teardown; no host ACL or unrelated file is changed.
        for path in self.base.glob("*/work/fixture.tmp"):
            if path.is_file() and not path.is_symlink():
                path.chmod(stat.S_IWRITE | stat.S_IREAD)
        self.storage.cleanup()

    def output(self):
        self.counter += 1
        return self.base / f"run-{self.counter}"

    def probe(self, scenario, **options):
        output = self.output()
        result = run_probe(scenario, output, **options)
        self.assertEqual(json.loads((output / "run.json").read_text()), result)
        return result, output

    def assert_stopped(self, result):
        self.assertTrue(result["termination_confirmed"])
        if result["process_id"]:
            self.assertEqual(result["accounting"]["active_processes"], 0)

    def test_timeout_cooperative_stop_and_forced_escalation(self):
        for scenario, forced in (("cooperative", False), ("ignore_cancel", True)):
            result, output = self.probe(scenario, limits=Limits(wall_seconds=.5, grace_seconds=1))
            self.assertEqual(result["outcome"], "TIMEOUT")
            self.assertEqual(result["forced_termination"], forced)
            self.assertEqual(result["cleanup_status"], "COMPLETE")
            self.assert_stopped(result)
            if not forced:
                self.assertIn(b'CANCELLED', (output / "stdout.bin").read_bytes())

    def test_explicit_cancel_preserves_distinction_from_timeout(self):
        event = threading.Event()
        timer = threading.Timer(.5, event.set)
        timer.start()
        try:
            result, _ = self.probe("cooperative", cancel=event, limits=Limits(wall_seconds=5, grace_seconds=1))
        finally:
            timer.cancel()
            timer.join()
        self.assertEqual(result["outcome"], "CANCELLED")
        self.assertEqual(result["reason"], "CANCEL_REQUESTED")
        self.assertFalse(result["forced_termination"])
        self.assert_stopped(result)

    def test_prelaunch_cancel_does_not_spawn(self):
        event = threading.Event()
        event.set()
        result, _ = self.probe("cooperative", cancel=event)
        self.assertEqual(result["outcome"], "CANCELLED")
        self.assertIsNone(result["process_id"])
        self.assertEqual(result["cleanup_status"], "COMPLETE")

    def test_crash_and_malformed_output_are_infrastructure_errors(self):
        for scenario, reason in (("crash", "CHILD_EXIT"), ("malformed", "MALFORMED_OUTPUT")):
            result, _ = self.probe(scenario)
            self.assertEqual((result["outcome"], result["reason"]), ("ERROR", reason))
            self.assertEqual(result["evaluation_status"], "NOT_EVALUATED")
            self.assert_stopped(result)

    def test_stdout_and_stderr_overflow_are_bounded(self):
        for scenario, file in (("overflow", "stdout.bin"), ("stderr_overflow", "stderr.bin")):
            result, output = self.probe(scenario, limits=Limits(stdout_bytes=512, stderr_bytes=512, grace_seconds=.1))
            self.assertEqual((result["outcome"], result["reason"]), ("ERROR", "OUTPUT_LIMIT"))
            self.assertLessEqual((output / file).stat().st_size, 512)
            self.assert_stopped(result)

    def test_descendant_is_counted_and_terminated_with_root(self):
        result, _ = self.probe("descendant", limits=Limits(wall_seconds=.7, grace_seconds=.1))
        self.assertEqual(result["outcome"], "TIMEOUT")
        self.assertTrue(result["forced_termination"])
        self.assertGreaterEqual(result["accounting"]["total_processes"], 2)
        self.assert_stopped(result)

    def test_memory_and_cpu_limits_fail_without_product_fail(self):
        for scenario in ("memory", "cpu"):
            result, _ = self.probe(scenario, limits=Limits(memory_mb=64, cpu_seconds=.2, wall_seconds=8))
            self.assertEqual(result["outcome"], "ERROR")
            self.assertEqual(result["reason"], "CHILD_EXIT")
            self.assert_stopped(result)

    def test_working_disk_limit_and_partial_prepare_cleanup(self):
        result, _ = self.probe("disk", limits=Limits(disk_bytes=32768, grace_seconds=.1))
        self.assertEqual((result["outcome"], result["reason"]), ("ERROR", "DISK_LIMIT"))
        self.assertEqual(result["cleanup_status"], "COMPLETE")
        self.assert_stopped(result)
        sentinel = self.base / "unrelated.txt"
        sentinel.write_text("preserve me")
        result, output = self.probe("prepare_error")
        self.assertIsNone(result["process_id"])
        self.assertEqual(result["outcome"], "ERROR")
        self.assertEqual(result["cleanup_status"], "COMPLETE")
        self.assertFalse((output / "work").exists())
        self.assertEqual(sentinel.read_text(), "preserve me")

    def test_cleanup_failure_preserves_pass_and_evidence(self):
        result, output = self.probe("cleanup_error")
        self.assertEqual(result["outcome"], "PASS")
        self.assertEqual(result["evaluation_status"], "EVALUATED")
        self.assertEqual(result["cleanup_status"], "ERROR")
        self.assertTrue(result["quarantine_required"])
        self.assertTrue((output / "report.json").exists())
        self.assertTrue((output / "work/fixture.tmp").exists())
        self.assert_stopped(result)

    def test_collection_io_failure_retains_primary_outcome(self):
        original = Path.write_text

        def fail_human(path, *args, **kwargs):
            if path.name == 'report.txt':
                raise OSError('controlled artifact write failure')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'write_text', fail_human):
            result, output = self.probe('pass')
        self.assertEqual(result['outcome'], 'PASS')
        self.assertEqual(result['evidence_status'], 'INCOMPLETE')
        self.assertTrue(result['report_collected'])
        self.assertTrue(result['quarantine_required'])
        self.assertTrue((output/'report.json').exists())
        self.assert_stopped(result)

    def test_unconfirmed_termination_defers_cleanup(self):
        with patch.object(WindowsTree, "wait_empty", return_value=False):
            result, output = self.probe("ignore_cancel", limits=Limits(wall_seconds=.3, grace_seconds=.1))
        # Simulated inability to confirm: not evidence of actual running hardware.
        self.assertFalse(result["termination_confirmed"])
        self.assertEqual(result["cleanup_status"], "DEFERRED_UNCONFIRMED_TERMINATION")
        self.assertTrue(result["quarantine_required"])
        self.assertTrue((output / "work").exists())

    def test_job_setup_failure_never_opens_launch_gate(self):
        with patch.object(WindowsTree, "attach", side_effect=TreeError("controlled denied containment")):
            result, _ = self.probe("ignore_cancel")
        self.assertEqual(result["reason"], "SETUP_ERROR")
        self.assertFalse(result["launch_gate_open"])
        self.assertTrue(result["termination_confirmed"])

    def test_can_pass_fail_error_and_source_inputs_preserved(self):
        wheel = self.base / "fixture.whl"
        matching_fixture_wheel(wheel)
        manifest = executable_manifest(2, verify_wheel(wheel))
        expected = self.base / "expected.hex"
        expected.write_bytes(b"DE AD 00 01 AA FF\n")
        actual = self.base / "actual.hex"
        for data, outcome in ((b"00 01 AA FF", "PASS"), (b"00 01 AB FF", "FAIL"), (b"AG", "ERROR")):
            actual.write_bytes(data)
            output = self.output()
            result = run_can(manifest, expected, actual, wheel, output, parameters={"header_bytes": 2})
            self.assertEqual(result["outcome"], outcome)
            self.assertEqual(result["cleanup_status"], "COMPLETE")
            self.assertTrue(result["report_collected"])
            self.assert_stopped(result)
            self.assertEqual(actual.read_bytes(), data)
        denied = run_can(manifest, expected, actual, wheel, self.output(), parameters={"header_bytes": 0})
        self.assertIsNone(denied["process_id"])
        self.assertEqual(denied["reason"], "SETUP_ERROR")

    def test_existing_output_and_arbitrary_manifest_commands_rejected(self):
        output = self.output()
        output.mkdir()
        marker = output / "preserve.txt"
        marker.write_text("existing")
        with self.assertRaises(FileExistsError):
            run_probe("crash", output)
        self.assertEqual(marker.read_text(), "existing")
        result = run_can({"plugin": "powershell.exe", "command": "anything"}, "x", "y", "z", self.output(), parameters={})
        self.assertEqual(result["outcome"], "ERROR")
        self.assertIsNone(result["process_id"])
