"""Pure comparison fixtures plus PostgreSQL-backed immutable publication rules."""
from copy import deepcopy
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from contracts.plugins import executable_manifest, validate_manifest
from contracts.v1 import ContractError, manifest
from workloads.can_payload_compare import MAX_DETAILS, MAX_INPUT_BYTES, compare, human_report, json_report
from workloads.registry import run, verify_wheel
from .models import AuditEvent, Job, TestApproval, TestVersion
from .submissions import Actor, Rejected, approval, publish, submit, version_grant
from .test_m2a import Fixture


def matching_fixture_wheel(path):
    """Test-only ZIP fixture; real distributable/clean install checked separately."""
    root = Path(__file__).resolve().parents[2]
    with zipfile.ZipFile(path, "w") as archive:
        for package in ("contracts", "agent", "workloads"):
            for source in sorted((root / package).glob("*.py")):
                archive.writestr(source.relative_to(root).as_posix(), source.read_bytes())
        archive.writestr("hardware_validation_lab_contracts-0.6.0.dist-info/METADATA",
                         "Metadata-Version: 2.4\r\nName: hardware-validation-lab-contracts\r\nVersion: 0.6.0\r\n")


class CANComparisonTests(unittest.TestCase):
    def result(self, expected=b"00 01 AA FF\n", actual=b"00 01 AA FF\n", header=0):
        return compare(expected, actual, header_bytes=header)

    def test_match_is_deterministic_with_recoverable_raw_and_normalized_evidence(self):
        report = self.result()
        self.assertEqual(report["outcome"], "PASS")
        self.assertEqual(report["evaluation_status"], "EVALUATED")
        evidence = report["inputs"]["expected"]
        self.assertEqual(bytes.fromhex(evidence["raw_content_hex"]), b"00 01 AA FF\n")
        self.assertEqual(evidence["raw_sha256"], hashlib.sha256(b"00 01 AA FF\n").hexdigest())
        self.assertEqual(evidence["normalized_payload_hex"], "0001aaff")
        self.assertEqual(evidence["normalized_sha256"], hashlib.sha256(bytes.fromhex("0001aaff")).hexdigest())
        self.assertEqual(json_report(report), json_report(self.result()))
        self.assertEqual(json.loads(json_report(report)), report)
        self.assertIn("no physical capture", human_report(report))

    def test_substitution_payload_offset_after_expected_header(self):
        report = self.result(b"DE AD 00 01 AA FF", b"00 01 AB FF", header=2)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertEqual(report["details"], [{"kind": "substitution", "offset": 2, "expected": 170, "actual": 171}])
        self.assertEqual(report["inputs"]["actual"]["removed_header_bytes"], 0)
        self.assertIn("offset 2: substitution expected=AA actual=AB", human_report(report))

    def test_missing_and_extra_counts_include_length_and_overlap(self):
        missing = self.result(b"01 02 03", b"01 FF")
        self.assertEqual(missing["summary"]["overlap_mismatches"], 1)
        self.assertEqual(missing["summary"]["missing_bytes"], 1)
        self.assertEqual(missing["summary"]["extra_bytes"], 0)
        self.assertEqual(missing["details"][-1], {"kind": "missing", "offset": 2, "expected": 3, "actual": None})
        extra = self.result(b"01 02", b"01 FF 03")
        self.assertEqual(extra["summary"]["overlap_mismatches"], 1)
        self.assertEqual(extra["summary"]["extra_bytes"], 1)
        self.assertEqual(extra["details"][-1], {"kind": "extra", "offset": 2, "expected": None, "actual": 3})

    def test_leading_insertion_is_positional_not_edit_distance(self):
        report = self.result(b"01 02 03", b"00 01 02 03")
        self.assertEqual(report["summary"]["overlap_mismatches"], 3)
        self.assertEqual(report["summary"]["extra_bytes"], 1)
        self.assertEqual(report["summary"]["total_differing_positions"], 4)

    def test_strict_grammar_rejects_incomplete_pairs_prefixes_comments_unicode(self):
        for data in (b"A", b"A A", b"0xAA", b"AA:BB", b"AA #comment", b"AA\x00", b"AA\vBB", b"\xef\xbb\xbfAA", b"\xff"):
            with self.subTest(data=data):
                report = self.result(actual=data)
                self.assertEqual(report["outcome"], "ERROR")
                self.assertEqual(report["evaluation_status"], "NOT_EVALUATED")
                self.assertEqual(report["errors"][0]["code"], "INVALID_HEX")
                self.assertIsNone(report["summary"])
                self.assertEqual(bytes.fromhex(report["inputs"]["actual"]["raw_content_hex"]), data)

    def test_case_whitespace_and_contiguous_complete_pairs(self):
        self.assertEqual(self.result(b" 00\t01\r\naaFF\n", b"0001AAff")["outcome"], "PASS")

    def test_empty_or_header_consumed_reference_is_never_pass(self):
        for expected, actual, header in ((b"", b"", 0), (b" \r\n", b"00", 0), (b"AA", b"AA", 1), (b"AA", b"AA", 2), (b"AA", b"", 0)):
            self.assertEqual(self.result(expected, actual, header)["outcome"], "ERROR")

    def test_bounds_and_type_failures(self):
        report = self.result(actual=b"AA" * (MAX_INPUT_BYTES // 2 + 1))
        self.assertEqual(report["errors"][0]["code"], "INPUT_TOO_LARGE")
        self.assertNotIn("actual", report["inputs"])
        self.assertEqual(self.result(actual="AA")["errors"][0]["code"], "INPUT_TYPE")
        for invalid in (True, -1, 4097, "2", None):
            with self.assertRaises(ContractError):
                self.result(header=invalid)
        self.assertEqual(self.result(b"00" * 4096 + b"AA", b"AA", 4096)["outcome"], "PASS")

    def test_detail_bound_does_not_truncate_counts(self):
        report = self.result(b"00" * 200, b"FF" * 250)
        self.assertEqual(len(report["details"]), MAX_DETAILS)
        self.assertEqual(report["summary"]["overlap_mismatches"], 200)
        self.assertEqual(report["summary"]["extra_bytes"], 50)
        self.assertTrue(report["summary"]["details_truncated"])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.wheel = Path(self.directory.name) / "fixture.whl"
        matching_fixture_wheel(self.wheel)
        self.digest = verify_wheel(self.wheel)
        self.manifest = executable_manifest(1, self.digest)

    def run_plugin(self, content=None, params=None, inputs=None):
        return run(self.manifest if content is None else content,
                   {"expected": b"FF AA", "actual": b"AA"} if inputs is None else inputs,
                   {"header_bytes": 1} if params is None else params, wheel_path=self.wheel)

    def test_verified_package_and_versioned_report(self):
        self.assertEqual(self.digest, hashlib.sha256(self.wheel.read_bytes()).hexdigest())
        report = self.run_plugin()
        self.assertEqual(report["outcome"], "PASS")
        self.assertEqual(report["plugin_package_sha256"], self.digest)
        self.assertEqual(report["plugin_version"], "0.3.0")

    def test_unknown_plugin_metadata_only_or_invalid_manifest_rejected(self):
        for change in ({"plugin": "os.system"}, {"schema_version": 2}, {"schema_version": True}, {"source": "physical"}, {"arbitrary_command": "anything"}):
            content = {**self.manifest, **change}
            with self.assertRaises(ContractError):
                self.run_plugin(content)
        with self.assertRaises(ContractError):
            self.run_plugin(manifest(1))

    def test_header_override_and_missing_or_extra_roles_rejected(self):
        for params in ({"header_bytes": 0}, {"header_bytes": 1, "command": "anything"}, {"header_bytes": True}):
            with self.assertRaises(ContractError):
                self.run_plugin(params=params)
        for inputs in ({"actual": b"AA"}, {"expected": b"FF AA", "actual": b"AA", "other": b"00"}):
            with self.assertRaises(ContractError):
                self.run_plugin(inputs=inputs)

    def test_digest_mismatch_and_changed_source_cannot_run(self):
        with self.assertRaises(ContractError):
            self.run_plugin({**self.manifest, "plugin_package_sha256": "0" * 64})
        with zipfile.ZipFile(self.wheel, "a") as archive:
            archive.writestr("workloads/extra.py", "# not installed\n")
        with self.assertRaises(ContractError):
            verify_wheel(self.wheel)

    def test_old_contract_remains_metadata_only(self):
        old = manifest(2)
        self.assertIsNone(old["plugin_package_sha256"])
        self.assertFalse(old["execution_available"])
        self.assertEqual(validate_manifest(old)[1], 2)

    def test_changed_module_rejected(self):
        with zipfile.ZipFile(self.wheel) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["workloads/can_payload_compare.py"] += b"\n# changed implementation\n"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        with self.assertRaises(ContractError):
            verify_wheel(self.wheel)

    def test_valid_grammar_boundary_and_full_mismatch_totals(self):
        # Full accepted input limit, not only a size-guard test.
        result = compare(b"00" * (MAX_INPUT_BYTES // 2), b"FF" * (MAX_INPUT_BYTES // 2), header_bytes=0)
        self.assertEqual(result["summary"]["overlap_mismatches"], MAX_INPUT_BYTES // 2)
        self.assertEqual(len(result["details"]), MAX_DETAILS)


class WorkloadPublicationTests(Fixture, TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = tempfile.TemporaryDirectory()
        cls.config = override_settings(ARTIFACT_ROOT=Path(cls.storage.name) / "inputs")
        cls.config.enable()
        super().setUpClass()
        cls.prepare()
        cls.wheel = Path(cls.storage.name) / "fixture.whl"
        matching_fixture_wheel(cls.wheel)
        if os.environ.get("LAB_B2_REVIEW_WHEEL"):
            # Optional real-build integration mode, exercised for the local gate.
            cls.wheel = Path(os.environ["LAB_B2_REVIEW_WHEEL"])

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.config.disable()
        cls.storage.cleanup()

    def test_new_version_requires_new_approval_grant_and_preserves_old_queued_context(self):
        old_batch, _ = submit(Actor(self.operator.pk), "old-queued", self.payload)
        old_job = Job.objects.get(batch=old_batch)
        snapshot = deepcopy(old_job.snapshot)
        published = publish(Actor(self.admin.pk), self.project.pk, self.definition.pk, workload_wheel=self.wheel)
        self.assertEqual(published.number, 2)
        self.assertTrue(published.manifest["execution_available"])
        self.assertFalse(TestApproval.objects.filter(version=published).exists())
        self.version.refresh_from_db()
        self.assertEqual(self.version.manifest, manifest(0))
        data = deepcopy(self.payload)
        data["items"][0]["version_id"] = str(published.pk)
        with self.assertRaises(Rejected):
            submit(Actor(self.operator.pk), "new-queued", data)
        approval(Actor(self.admin.pk), self.project.pk, published.pk, True)
        with self.assertRaises(Rejected):
            submit(Actor(self.operator.pk), "new-queued", data)
        version_grant(Actor(self.admin.pk), self.project.pk, self.member.pk, published.pk, True)
        batch, _ = submit(Actor(self.operator.pk), "new-queued", data)
        new_job = Job.objects.get(batch=batch)
        self.assertEqual(new_job.state, "queued")
        old_job.refresh_from_db()
        self.assertEqual(old_job.snapshot, snapshot)
        self.assertTrue(AuditEvent.objects.filter(action="version.published", target=str(published.pk)).exists())

    def test_command_publishes_new_version_with_actual_fixture_digest(self):
        output = StringIO()
        call_command("publish_can_workload", str(self.project.pk), str(self.definition.pk), self.admin.email,
                     wheel=str(self.wheel), stdout=output)
        version = TestVersion.objects.filter(definition=self.definition).latest("number")
        self.assertEqual(version.manifest["plugin_package_sha256"], verify_wheel(self.wheel))
        self.assertIn("dispatch remains disabled", output.getvalue())

    def test_no_unauthorized_publish_or_failed_verification_version(self):
        for user in (self.viewer, self.operator, self.engineer):
            with self.assertRaises(Rejected):
                publish(Actor(user.pk), self.project.pk, self.definition.pk, workload_wheel=self.wheel)
        count = self.definition.versions.count()
        with self.assertRaises((OSError, ContractError)):
            publish(Actor(self.admin.pk), self.project.pk, self.definition.pk, workload_wheel=self.wheel.parent / "missing.whl")
        self.assertEqual(self.definition.versions.count(), count)
