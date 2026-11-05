"""Strict, bounded M2A contract; executable plugin implementation arrives in M2B."""
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID


class ContractError(ValueError):
    pass


class Parameters(TypedDict):
    header_bytes: int


@dataclass(frozen=True)
class Item:
    version_id: str
    device_id: str
    expected_artifact_id: str
    actual_artifact_id: str
    parameters: Parameters


@dataclass(frozen=True)
class Submission:
    project_id: str
    items: tuple[Item, ...]
    queue_seconds: int
    software_commit: str | None


def identifier(value):
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ContractError("Expected a UUID identifier.") from exc


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or set(value) - set(required) - set(optional):
        raise ContractError("Missing or unsupported fields.")


def parse_submission(value) -> Submission:
    exact_keys(value, {"project_id", "items"}, {"queue_seconds", "software_commit"})
    queue_seconds = value.get("queue_seconds", 3600)
    if type(queue_seconds) is not int or not 60 <= queue_seconds <= 86400:
        raise ContractError("queue_seconds must be an integer from 60 to 86400.")
    commit = value.get("software_commit")
    if commit is not None and (not isinstance(commit, str) or not 7 <= len(commit) <= 64 or any(c not in "0123456789abcdef" for c in commit)):
        raise ContractError("software_commit must be a lowercase hex revision or null (unknown).")
    if not isinstance(value["items"], list) or not 1 <= len(value["items"]) <= 20:
        raise ContractError("A submission needs 1 to 20 items.")
    items = []
    for raw in value["items"]:
        exact_keys(raw, {"version_id", "device_id", "expected_artifact_id", "actual_artifact_id", "parameters"})
        from .plugins import validate_parameters
        parameters = validate_parameters("can_payload_compare", raw["parameters"])
        items.append(Item(**{key: identifier(raw[key]) for key in ("version_id", "device_id", "expected_artifact_id", "actual_artifact_id")}, parameters=parameters))
    return Submission(identifier(value["project_id"]), tuple(items), queue_seconds, commit)


def manifest(header_bytes: int):
    if type(header_bytes) is not int or not 0 <= header_bytes <= 4096:
        raise ContractError("Invalid declared reference header size.")
    return {"schema_version": 1, "plugin": "can_payload_compare", "plugin_package_sha256": None,
            "execution_available": False, "required_capabilities": ["can_payload_files"],
            "parameter_schema": {"type": "object", "properties": {"header_bytes": {"type": "integer", "const": header_bytes}},
                                 "required": ["header_bytes"], "additionalProperties": False},
            "input_roles": ["expected", "actual"], "source": "simulated",
            "note": "Contract metadata only; no executable package or physical CAN validation."}
