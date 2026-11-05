"""Standalone bounded Windows runner. No assignments, journal or hardware lease."""
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time

from contracts.plugins import validate_manifest, validate_parameters
from contracts.runner_v1 import Limits, PROBES, strict_json
from contracts.v1 import ContractError
from workloads.can_payload_compare import MAX_INPUT_BYTES, human_report, json_report
from workloads.registry import MAX_WHEEL_BYTES, verify_wheel
from .process_tree import create_tree

BOOTSTRAP = "import sys; gate=sys.stdin.buffer.raw.readline(16); " \
            "gate==b'GO\\n' or sys.exit(2); sys.path.insert(0,sys.argv[1]); from agent.worker import main; main()"


class CancelledBeforeLaunch(Exception):
    pass


def safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
                raise ContractError("Local paths must not traverse links/reparse points.")
    return path


def bounded_read(path, maximum):
    path = safe_path(path)
    if not path.is_file():
        raise ContractError("Expected a regular local input file.")
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ContractError("Input exceeds the local size bound.")
    return value


class Capture:
    def __init__(self, stream, maximum, overflow):
        self.data = bytearray()
        self.maximum, self.overflow, self.stream = maximum, overflow, stream
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while chunk := os.read(self.stream.fileno(), 4096):
                remaining = self.maximum - len(self.data)
                self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.overflow.set()
        except (OSError, ValueError):
            self.overflow.set()
        finally:
            self.done.set()


def disk_usage(work):
    total, count = 0, 0
    for path in work.iterdir():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ContractError("Unexpected worker filesystem entry.")
        total += info.st_size
        count += 1
    if count > 8:
        raise ContractError("Worker file count exceeded.")
    return total


def validate_output(raw, *, probe, staged, digest, parameters=None):
    report = strict_json(raw)
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ContractError("Unsupported worker report schema.")
    if probe == "cooperative" and report == {"schema_version": 1, "outcome": "CANCELLED", "evaluation_status": "NOT_EVALUATED"}:
        return report
    required = {"schema_version", "plugin", "source", "comparison", "offset_basis", "parameters", "outcome",
                "evaluation_status", "errors", "inputs", "summary", "details", "details_limit"}
    if probe is None:
        required |= {"plugin_package_sha256", "plugin_version"}
    if set(report) != required or report["plugin"] != "can_payload_compare" or report["source"] != ("runner_probe" if probe else "simulated"):
        raise ContractError("Invalid worker report fields/source.")
    if report["comparison"] != "positional" or report["offset_basis"] != "normalized_payload_zero_based":
        raise ContractError("Invalid report offset convention.")
    if report["outcome"] not in {"PASS", "FAIL", "ERROR"} or not isinstance(report["errors"], list):
        raise ContractError("Invalid worker outcome.")
    evaluated = report["outcome"] != "ERROR"
    if report["evaluation_status"] != ("EVALUATED" if evaluated else "NOT_EVALUATED") or bool(report["errors"]) == evaluated:
        raise ContractError("Inconsistent worker evaluation.")
    if not isinstance(report["inputs"], dict) or set(report["inputs"]) != {"expected", "actual"}:
        raise ContractError("Missing worker input evidence.")
    policy = {"header_bytes": 0} if probe else parameters
    if report["parameters"] != policy:
        raise ContractError("Worker changed the declared header policy.")
    payloads = {}
    for role, data in staged.items():
        evidence = report["inputs"][role]
        keys = {"raw_size", "raw_sha256", "raw_content_hex", "decoded_size", "removed_header_bytes", "normalized_payload_hex", "normalized_sha256"}
        if not isinstance(evidence, dict) or set(evidence) != keys:
            raise ContractError("Invalid input evidence schema.")
        if evidence["raw_sha256"] != hashlib.sha256(data).hexdigest() or evidence["raw_content_hex"] != data.hex() or evidence["raw_size"] != len(data):
            raise ContractError("Worker input checksum/evidence conflict.")
        if evidence["decoded_size"] is not None and (type(evidence["decoded_size"]) is not int or not 0 <= evidence["decoded_size"] <= MAX_INPUT_BYTES):
            raise ContractError("Invalid decoded input size.")
        header = policy["header_bytes"] if role == "expected" else 0
        if type(evidence["removed_header_bytes"]) is not int or evidence["removed_header_bytes"] != header:
            raise ContractError("Invalid header evidence.")
        normalized = evidence["normalized_payload_hex"]
        if normalized is None:
            if evidence["normalized_sha256"] is not None:
                raise ContractError("Invalid normalized checksum.")
        else:
            if not isinstance(normalized, str) or len(normalized) > 2 * MAX_INPUT_BYTES or len(normalized) % 2 or any(c not in "0123456789abcdef" for c in normalized):
                raise ContractError("Invalid normalized bytes.")
            payload = bytes.fromhex(normalized)
            if evidence["normalized_sha256"] != hashlib.sha256(payload).hexdigest():
                raise ContractError("Normalized checksum conflict.")
            payloads[role] = payload
    for error in report["errors"]:
        if not isinstance(error, dict) or set(error) != {"role", "code", "message"} or error["role"] not in {"expected", "actual"}:
            raise ContractError("Invalid worker error schema.")
        if error["code"] not in {"INPUT_TYPE", "INPUT_TOO_LARGE", "INVALID_HEX", "EMPTY_PAYLOAD"} or not isinstance(error["message"], str) or not 1 <= len(error["message"]) <= 240 or any(ord(c) < 32 for c in error["message"]):
            raise ContractError("Invalid worker error details.")
    if not probe and (report["plugin_package_sha256"] != digest or report["plugin_version"] != "0.3.0"):
        raise ContractError("Worker package identity conflict.")
    if type(report["details_limit"]) is not int or report["details_limit"] != 100 or not isinstance(report["details"], list) or len(report["details"]) > 100:
        raise ContractError("Invalid report detail bounds.")
    if evaluated:
        summary = report["summary"]
        fields = {"expected_bytes", "actual_bytes", "overlap_bytes", "overlap_mismatches", "missing_bytes", "extra_bytes", "total_differing_positions", "details_truncated"}
        if not isinstance(summary, dict) or set(summary) != fields:
            raise ContractError("Invalid summary schema.")
        if any(type(summary[key]) is not int or summary[key] < 0 for key in fields - {"details_truncated"}):
            raise ContractError("Invalid summary counters.")
        if set(payloads) != {"expected", "actual"} or not all(payloads.values()):
            raise ContractError("Evaluated report has empty/missing payloads.")
        expected_size, actual_size = len(payloads["expected"]), len(payloads["actual"])
        if (summary["expected_bytes"], summary["actual_bytes"], summary["overlap_bytes"], summary["missing_bytes"], summary["extra_bytes"]) != (
                expected_size, actual_size, min(expected_size, actual_size), max(0, expected_size - actual_size), max(0, actual_size - expected_size)):
            raise ContractError("Inconsistent payload length counters.")
        if summary["overlap_mismatches"] > summary["overlap_bytes"]:
            raise ContractError("Invalid overlapping mismatch count.")
        total = summary["overlap_mismatches"] + summary["missing_bytes"] + summary["extra_bytes"]
        if summary["total_differing_positions"] != total or (report["outcome"] == "PASS") != (total == 0):
            raise ContractError("Inconsistent comparison outcome.")
        if type(summary["details_truncated"]) is not bool or summary["details_truncated"] != (total > len(report["details"])):
            raise ContractError("Invalid truncation indicator.")
        for detail in report["details"]:
            if set(detail) != {"kind", "offset", "expected", "actual"} or detail["kind"] not in {"substitution", "missing", "extra"}:
                raise ContractError("Invalid detail schema.")
            if type(detail["offset"]) is not int or detail["offset"] < 0:
                raise ContractError("Invalid detail offset.")
            for value in (detail["expected"], detail["actual"]):
                if value is not None and (type(value) is not int or not 0 <= value <= 255):
                    raise ContractError("Invalid detail byte.")
    elif report["summary"] is not None or report["details"]:
        raise ContractError("Unevaluated report contains comparisons.")
    return report


def run_can(manifest, expected, actual, wheel, output_dir, *, parameters, limits=Limits(), cancel=None):
    return _run(manifest, {"expected": expected, "actual": actual}, wheel, output_dir,
                parameters=parameters, limits=limits, cancel=cancel, probe=None)


def run_probe(scenario, output_dir, *, limits=Limits(), cancel=None):
    if scenario not in PROBES:
        raise ContractError("Unknown fixed runner probe.")
    return _run(None, {}, None, output_dir, parameters={}, limits=limits, cancel=cancel, probe=scenario)


def _run(manifest, inputs, wheel, output_dir, *, parameters, limits, cancel, probe):
    limits.validate()
    cancel = cancel if cancel is not None else threading.Event()
    output = safe_path(output_dir)
    output.mkdir(mode=0o700, exist_ok=False)
    work = output / "work"
    work.mkdir(mode=0o700)
    result = {"schema_version": 1, "runner_version": "0.4.0", "python_version": sys.version.split()[0],
              "source": "runner_probe" if probe else "simulated", "probe": probe,
              "outcome": "ERROR", "evaluation_status": "NOT_EVALUATED", "reason": "SETUP_ERROR",
              "termination_confirmed": True, "cleanup_status": "NOT_STARTED", "quarantine_required": False,
              "hardware_readiness": "NOT_EVALUATED", "dispatch_available": False, "limits": asdict(limits),
              "process_id": None, "child_exit_code": None, "forced_termination": False, "accounting": None,
              "input_sha256": {}, "report_collected": False, "evidence_status": "COMPLETE"}
    owned, staged = {}, {}
    process = tree = stdout = stderr = None
    attached, gate_open, stopped, started = False, False, True, time.monotonic()
    overflow = threading.Event()
    report = None

    def stage(name, data):
        if disk_usage(work) + len(data) > limits.disk_bytes:
            raise ContractError("Staging exceeds working disk budget.")
        path = work / name
        with path.open("xb") as stream:
            owned[name] = (path.stat().st_dev, path.stat().st_ino)
            stream.write(data)

    try:
        if probe is None:
            spec, header = validate_manifest(manifest, executable=True)
            validate_parameters(spec.name, parameters, declared_header=header)
            digest = verify_wheel(wheel)
            if digest != manifest["plugin_package_sha256"]:
                raise ContractError("Approved package differs from local release.")
            for role in ("expected", "actual"):
                staged[role] = bounded_read(inputs[role], MAX_INPUT_BYTES)
                stage(role + ".hex", staged[role])
                result["input_sha256"][role] = hashlib.sha256(staged[role]).hexdigest()
            stage("plugin.whl", bounded_read(wheel, MAX_WHEEL_BYTES))
            if hashlib.sha256((work / "plugin.whl").read_bytes()).hexdigest() != digest:
                raise ContractError("Package changed during staging.")
        else:
            digest = None
            staged = {"expected": b"AA", "actual": b"AA"}
            if probe == "prepare_error":
                stage("expected.hex", b"AA")
                raise ContractError("Controlled partial preparation failure.")
        if cancel.is_set():
            raise CancelledBeforeLaunch
        tree = create_tree(limits)
        package_root = str(Path(__file__).resolve().parent.parent)
        environment = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        # Use the base interpreter directly, avoiding virtualenv launcher reexec.
        # Start suspended so no worker/descendant can run before containment.
        interpreter = getattr(sys, "_base_executable", sys.executable)
        process = subprocess.Popen([interpreter, "-I", "-B", "-u", "-c", BOOTSTRAP, package_root],
                                   cwd=work, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=environment, shell=False, close_fds=True, **tree.spawn_options())
        stopped = False
        result["process_id"] = process.pid
        tree.attach(process)
        attached = True
        tree.resume(process)
        stdout, stderr = Capture(process.stdout, limits.stdout_bytes, overflow), Capture(process.stderr, limits.stderr_bytes, overflow)
        request = {"schema_version": 1, "manifest": manifest, "parameters": parameters, "probe": probe, "limits": asdict(limits)}
        payload = ("GO\n" + json_report(request)).encode("utf-8")
        if len(payload) > 65536:
            raise ContractError("Worker request exceeds bound.")
        process.stdin.write(payload)
        process.stdin.flush()
        gate_open = True
        deadline = time.monotonic() + limits.wall_seconds
        reason = None
        while process.poll() is None:
            try:
                if cancel.is_set():
                    reason = "CANCEL_REQUESTED"
                elif overflow.is_set():
                    reason = "OUTPUT_LIMIT"
                elif disk_usage(work) > limits.disk_bytes:
                    reason = "DISK_LIMIT"
                elif tree.accounting()["active_processes"] > limits.processes:
                    reason = "PROCESS_LIMIT"
                elif time.monotonic() >= deadline:
                    reason = "WALL_TIMEOUT"
                if reason:
                    break
                time.sleep(.02)
            except KeyboardInterrupt:
                cancel.set()
            except (OSError, ContractError):
                reason = "WORKSPACE_INVALID"
                break
        if reason:
            result.update(outcome="CANCELLED" if reason == "CANCEL_REQUESTED" else "TIMEOUT" if reason == "WALL_TIMEOUT" else "ERROR", reason=reason)
            try:
                process.stdin.write(b"CANCEL\n")
                process.stdin.flush()
            except OSError:
                pass
            if not tree.wait_empty(limits.grace_seconds):
                result["forced_termination"] = True
                tree.stop()
        elif process.poll() is not None:
            result["reason"] = "CHILD_EXIT" if process.returncode else "RESULT_PENDING"
        if tree.accounting()["active_processes"]:
            result["forced_termination"] = True
            tree.stop()
        stopped = tree.wait_empty()
        result["accounting"] = tree.accounting()
        if stopped:
            process.wait(timeout=3)
            stdout.thread.join(timeout=2)
            stderr.thread.join(timeout=2)
            result["child_exit_code"] = process.returncode
            if overflow.is_set() and not reason:
                result.update(outcome="ERROR", reason="OUTPUT_LIMIT")
            elif not reason and process.returncode == 0 and stdout.done.is_set() and stderr.done.is_set():
                try:
                    report = validate_output(bytes(stdout.data), probe=probe, staged=staged, digest=digest, parameters=parameters)
                    result.update(outcome=report["outcome"], evaluation_status=report["evaluation_status"], reason="PLUGIN_RESULT")
                except (ContractError, KeyError, TypeError, ValueError):
                    result.update(outcome="ERROR", reason="MALFORMED_OUTPUT")
    except CancelledBeforeLaunch:
        result.update(outcome="CANCELLED", reason="CANCELLED_BEFORE_LAUNCH")
    except KeyboardInterrupt:
        result.update(outcome="CANCELLED", reason="CANCEL_REQUESTED")
    except (ContractError, OSError, ValueError, subprocess.SubprocessError):
        # Fixed reason only; never expose child environment or arbitrary exceptions.
        result.update(outcome="ERROR", reason="SETUP_ERROR" if not gate_open else "RUNNER_ERROR")
    finally:
        if process is not None and not stopped:
            try:
                if attached:
                    tree.stop()
                    stopped = tree.wait_empty()
                else:
                    # No workload passed the gate; only this bootstrap exists.
                    process.kill()
                    process.wait(timeout=3)
                    stopped = not gate_open
            except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
                stopped = False
        if tree is not None:
            try:
                tree.close()  # Kill-on-close is additional containment, not confirmation.
            except OSError:
                stopped = False
        if process is not None and stopped:
            for capture in (stdout, stderr):
                if capture is not None:
                    capture.thread.join(timeout=2)
                    if not capture.done.is_set():
                        result["evidence_status"] = "INCOMPLETE"
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        result["launch_gate_open"] = gate_open
        result["containment"] = tree.kind if attached else "NOT_ESTABLISHED"
        result["platform"] = sys.platform
        result["disk_enforcement"] = "BOUNDED_STAGE_AND_MONITORED_WORK_DIRECTORY"
        result["resource_policy"] = ("JOB_COMMITTED_MEMORY_AGGREGATE_USER_CPU_HARD_PROCESS_COUNT_AND_CPU_RATE"
                                     if os.name == 'nt' else "PER_PROCESS_RLIMIT_AS_CPU_FSIZE_AND_MONITORED_GROUP_COUNT_NO_RATE_THROTTLE")
    if stdout is not None:
        try:
            (output / "stdout.bin").write_bytes(bytes(stdout.data))
            (output / "stderr.bin").write_bytes(bytes(stderr.data))
        except OSError:
            result["evidence_status"] = "INCOMPLETE"
    if probe and (work / "fixture.tmp").is_file():
        # Only fixed diagnostic code owns this exact scratch name.
        path = work / "fixture.tmp"
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 1024:
            owned["fixture.tmp"] = (info.st_dev, info.st_ino)
    return _finish(output, work, owned, result, report, stopped=stopped)


def _finish(output, work, owned, result, report, *, stopped):
    result["termination_confirmed"] = stopped
    errors = False
    if stopped:
        for name, identity in owned.items():
            path = work / name
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) != identity or not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
                    raise OSError("Owned file identity changed.")
                path.unlink()
            except OSError:
                errors = True
        try:
            work.rmdir()  # Never recursively delete unknown files.
        except OSError:
            errors = True
        result["cleanup_status"] = "ERROR" if errors else "COMPLETE"
    else:
        result["cleanup_status"] = "DEFERRED_UNCONFIRMED_TERMINATION"
    if report is not None:
        try:
            (output / "report.json").write_text(json_report(report), encoding="utf-8", newline="\n")
            result["report_collected"] = True
            if report.get("outcome") != "CANCELLED":
                (output / "report.txt").write_text(human_report(report), encoding="utf-8", newline="\n")
        except OSError:
            result["evidence_status"] = "INCOMPLETE"
    result["quarantine_required"] = not stopped or errors or result["evidence_status"] != "COMPLETE"
    try:
        (output / "run.json").write_text(json_report(result), encoding="utf-8", newline="\n")
    except OSError:
        result.update(evidence_status="INCOMPLETE", quarantine_required=True)
    return result
