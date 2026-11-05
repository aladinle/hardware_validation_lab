"""Static versioned plugin contracts; no import paths or commands from requests."""
from dataclasses import dataclass
import re
from .v1 import ContractError, exact_keys


@dataclass(frozen=True)
class PluginContract:
    name: str
    capabilities: tuple[str, ...]
    input_roles: tuple[str, ...]


CAN = PluginContract("can_payload_compare", ("can_payload_files",), ("expected", "actual"))


def plugin_contract(name):
    if name != CAN.name:
        raise ContractError("Unknown installed plugin.")
    return CAN


def validate_parameters(name, parameters, *, declared_header=None):
    plugin_contract(name)
    exact_keys(parameters, {"header_bytes"})
    header = parameters["header_bytes"]
    if type(header) is not int or not 0 <= header <= 4096:
        raise ContractError("header_bytes must be an integer from 0 to 4096.")
    if declared_header is not None and header != declared_header:
        raise ContractError("Parameters must use the approved reference header policy.")
    return {"header_bytes": header}


def executable_manifest(header_bytes, wheel_sha256):
    from .v1 import manifest
    if not isinstance(wheel_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", wheel_sha256):
        raise ContractError("An actual workload wheel SHA-256 is required.")
    content = manifest(header_bytes)
    content.update(plugin_package_sha256=wheel_sha256, execution_available=True,
                   plugin_version="0.3.0", report_schema_version=1,
                   note="Installed synthetic file comparator only; platform dispatch remains unavailable.")
    return content


def validate_manifest(content, *, executable=False):
    from .v1 import manifest
    if not isinstance(content, dict) or type(content.get("schema_version")) is not int or content["schema_version"] != 1:
        raise ContractError("Invalid approved plugin manifest.")
    spec = plugin_contract(content.get("plugin"))
    try:
        header = content["parameter_schema"]["properties"]["header_bytes"]["const"]
        enabled = content["execution_available"]
        if type(enabled) is not bool:
            raise ContractError("Invalid execution declaration.")
        expected = executable_manifest(header, content.get("plugin_package_sha256")) if enabled else manifest(header)
        if content != expected or (executable and not enabled):
            raise ContractError("Unsupported or metadata-only plugin manifest.")
    except (KeyError, TypeError) as exc:
        raise ContractError("Invalid approved plugin manifest.") from exc
    return spec, header
