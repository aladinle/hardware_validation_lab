"""Agent protocol v1. Only enrollment and idle heartbeat are operational in M2B.1."""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from .v1 import ContractError, exact_keys, identifier

SCHEMA_VERSION = 1
AGENT_VERSION = "0.2.0"
MAX_MESSAGE_BYTES = 65536


def text(value, maximum=80):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
        raise ContractError("Invalid bounded text.")
    return value


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]{0,20})?", value) or len(value) > 40:
        raise ContractError("Invalid version.")
    return value


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(text(value, 40).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ContractError("Expected timezone-aware ISO timestamp.") from exc
    if parsed.utcoffset() is None:
        raise ContractError("A timezone offset is required.")
    return value


def ids(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ContractError("Provide 1-20 device identifiers.")
    values = tuple(identifier(item) for item in value)
    if len(set(values)) != len(values):
        raise ContractError("Duplicate device identifier.")
    return tuple(sorted(values))


def schema(value, required, optional=()):
    exact_keys(value, {"schema_version", *required}, optional)
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise ContractError("Unsupported protocol version.")


@dataclass(frozen=True)
class EnrollmentRequest:
    agent_version: str
    platform: Literal["Windows", "Linux", "Darwin", "Other"]
    device_ids: tuple[str, ...]


def parse_enrollment(value):
    schema(value, {"agent_version", "platform", "device_ids"})
    if value["platform"] not in ("Windows", "Linux", "Darwin", "Other"):
        raise ContractError("Invalid reported platform.")
    return EnrollmentRequest(version(value["agent_version"]), value["platform"], ids(value["device_ids"]))


@dataclass(frozen=True)
class HeartbeatRequest:
    heartbeat_id: str
    sent_at: str
    agent_version: str
    platform: str
    device_ids: tuple[str, ...]


def parse_heartbeat(value):
    schema(value, {"heartbeat_id", "sent_at", "agent_version", "platform", "device_ids", "observations", "active_execution_id", "ready"})
    if value["observations"] != [] or value["active_execution_id"] is not None or value["ready"] is not False:
        raise ContractError("M2B.1 supports idle contact only, without device discovery/readiness/execution.")
    enrollment = parse_enrollment({key: value[key] for key in ("schema_version", "agent_version", "platform", "device_ids")})
    return HeartbeatRequest(identifier(value["heartbeat_id"]), timestamp(value["sent_at"]), enrollment.agent_version, enrollment.platform, enrollment.device_ids)


def parse_credential(value, *, enrollment=False):
    schema(value, {"agent_id", "project_id", "device_ids", "token", "expires_at", "credential_kind"})
    prefix, kind = ("hve_", "enrollment") if enrollment else ("hva_", "agent")
    token = value["token"]
    if value["credential_kind"] != kind or not isinstance(token, str) or not re.fullmatch(prefix + r"[A-Za-z0-9_-]{43}", token):
        raise ContractError("Invalid credential document.")
    return {**value, "agent_id": identifier(value["agent_id"]), "project_id": identifier(value["project_id"]),
            "device_ids": list(ids(value["device_ids"])), "expires_at": timestamp(value["expires_at"])}


def parse_idle_reply(value, agent_id, heartbeat_id):
    schema(value, {"agent_id", "heartbeat_id", "server_time", "last_contact_at", "replayed", "assignment", "execution_available", "devices_connected", "ready"})
    if identifier(value["agent_id"]) != identifier(agent_id) or identifier(value["heartbeat_id"]) != identifier(heartbeat_id):
        raise ContractError("Reply identity mismatch.")
    if value["assignment"] is not None or value["execution_available"] is not False or value["devices_connected"] != [] or value["ready"] is not False or type(value["replayed"]) is not bool:
        raise ContractError("Unexpected execution/readiness reply.")
    timestamp(value["server_time"])
    timestamp(value["last_contact_at"])
    return value


# Future wire types are definitions, not enabled endpoints or an execution engine.
@dataclass(frozen=True)
class InputReference:
    artifact_id: str
    sha256: str
    size: int
    role: Literal["expected", "actual"]


@dataclass(frozen=True)
class Assignment:
    schema_version: int
    execution_id: str
    job_id: str
    device_ids: tuple[str, ...]
    epoch: int
    plugin_id: str
    plugin_package_sha256: str
    deadline: str
    inputs: tuple[InputReference, ...]


@dataclass(frozen=True)
class Cancellation:
    schema_version: int
    execution_id: str
    epoch: int
    state: Literal["requested", "acknowledged", "termination_confirmed"]


@dataclass(frozen=True)
class ProgressEvent:
    schema_version: int
    execution_id: str
    epoch: int
    sequence: int
    stage: Literal["preparing", "running", "collecting"]


@dataclass(frozen=True)
class Result:
    schema_version: int
    execution_id: str
    epoch: int
    outcome: Literal["PASS", "FAIL", "ERROR", "TIMEOUT", "CANCELLED"]
    evaluation_status: Literal["evaluated", "not_evaluated"]
    report_artifact_id: str


@dataclass(frozen=True)
class ArtifactDeclaration:
    schema_version: int
    execution_id: str
    epoch: int
    artifact_id: str
    sha256: str
    size: int
    media_type: Literal["application/json", "text/plain", "application/octet-stream"]
