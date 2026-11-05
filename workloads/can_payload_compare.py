"""Pure bounded positional comparison; expected header only, no capture or I/O."""
import hashlib
import json
import re
from contracts.plugins import validate_parameters

MAX_INPUT_BYTES = 1024 * 1024
MAX_DETAILS = 100
HEX = re.compile(rb"[ \t\r\n]*(?:[0-9A-Fa-f]{2}(?:[ \t\r\n]*[0-9A-Fa-f]{2})*)?[ \t\r\n]*")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_report(report):
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def compare(expected, actual, *, header_bytes):
    validate_parameters("can_payload_compare", {"header_bytes": header_bytes})
    report = {"schema_version": 1, "plugin": "can_payload_compare", "source": "simulated",
              "comparison": "positional", "offset_basis": "normalized_payload_zero_based",
              "parameters": {"header_bytes": header_bytes}, "outcome": "ERROR", "evaluation_status": "NOT_EVALUATED",
              "errors": [], "inputs": {}, "summary": None, "details": [], "details_limit": MAX_DETAILS}
    payloads = {}
    for role, raw in (("expected", expected), ("actual", actual)):
        if not isinstance(raw, bytes):
            report["errors"].append({"role": role, "code": "INPUT_TYPE", "message": "Input must be bytes."})
            continue
        if len(raw) > MAX_INPUT_BYTES:
            report["errors"].append({"role": role, "code": "INPUT_TOO_LARGE", "message": "Input exceeds 1 MiB."})
            continue
        evidence = {"raw_size": len(raw), "raw_sha256": sha256(raw), "raw_content_hex": raw.hex(),
                    "decoded_size": None, "removed_header_bytes": header_bytes if role == "expected" else 0,
                    "normalized_payload_hex": None, "normalized_sha256": None}
        report["inputs"][role] = evidence
        if not HEX.fullmatch(raw):
            report["errors"].append({"role": role, "code": "INVALID_HEX", "message": "Expected complete hex byte pairs and ASCII space/tab/CR/LF only."})
            continue
        decoded = bytes.fromhex(raw.decode("ascii"))
        evidence["decoded_size"] = len(decoded)
        payload = decoded[header_bytes:] if role == "expected" else decoded
        evidence.update(normalized_payload_hex=payload.hex(), normalized_sha256=sha256(payload))
        if not payload:
            report["errors"].append({"role": role, "code": "EMPTY_PAYLOAD", "message": "Normalized payload must not be empty."})
            continue
        payloads[role] = payload
    if report["errors"]:
        return report
    expected, actual = payloads["expected"], payloads["actual"]
    overlap = min(len(expected), len(actual))
    mismatches = 0
    for offset in range(overlap):
        if expected[offset] != actual[offset]:
            mismatches += 1
            if len(report["details"]) < MAX_DETAILS:
                report["details"].append({"kind": "substitution", "offset": offset, "expected": expected[offset], "actual": actual[offset]})
    missing, extra = max(0, len(expected) - len(actual)), max(0, len(actual) - len(expected))
    for offset in range(overlap, min(max(len(expected), len(actual)), overlap + MAX_DETAILS - len(report["details"]))):
        report["details"].append({"kind": "missing" if missing else "extra", "offset": offset,
                                  "expected": expected[offset] if missing else None, "actual": actual[offset] if extra else None})
    total = mismatches + missing + extra
    report.update(outcome="FAIL" if total else "PASS", evaluation_status="EVALUATED",
                  summary={"expected_bytes": len(expected), "actual_bytes": len(actual), "overlap_bytes": overlap,
                           "overlap_mismatches": mismatches, "missing_bytes": missing, "extra_bytes": extra,
                           "total_differing_positions": total, "details_truncated": total > len(report["details"])})
    return report


def human_report(report):
    lines = [f"{report['outcome']} - synthetic CAN payload file comparison (no physical capture)",
             "Offsets: zero-based normalized payload; header removed from expected only."]
    for role, evidence in report["inputs"].items():
        lines.append(f"{role}: raw SHA-256 {evidence['raw_sha256']}")
    for error in report["errors"]:
        lines.append(f"ERROR {error['role']}: {error['code']} - {error['message']}")
    summary = report["summary"]
    if summary:
        lines.append(f"Lengths expected={summary['expected_bytes']} actual={summary['actual_bytes']}; "
                     f"overlap mismatches={summary['overlap_mismatches']}; missing={summary['missing_bytes']}; extra={summary['extra_bytes']}")
        for detail in report["details"]:
            expected = "--" if detail["expected"] is None else f"{detail['expected']:02X}"
            actual = "--" if detail["actual"] is None else f"{detail['actual']:02X}"
            lines.append(f"offset {detail['offset']}: {detail['kind']} expected={expected} actual={actual}")
        if summary["details_truncated"]:
            lines.append(f"Details limited to {report['details_limit']}; totals above cover the full payloads.")
    return "\n".join(lines) + "\n"
