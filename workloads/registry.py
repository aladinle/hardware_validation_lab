"""Fixed registry and locally verified release artifact. Never imports user code."""
from pathlib import Path
from io import BytesIO
import zipfile
from contracts.plugins import validate_manifest, validate_parameters
from contracts.v1 import ContractError
from .can_payload_compare import compare, sha256

MAX_WHEEL_BYTES = 20 * 1024 * 1024


def verify_wheel(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_WHEEL_BYTES:
        raise ContractError("Expected a bounded regular local workload wheel.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_WHEEL_BYTES + 1)
    if len(raw) > MAX_WHEEL_BYTES:
        raise ContractError("Workload wheel exceeds the size limit.")
    # Compare every shipped module with this installed implementation. The wheel
    # digest identifies this release artifact, not a claimed digest of source text.
    root = Path(__file__).resolve().parent.parent
    sources = {str(p.relative_to(root)).replace('\\', '/'): p.read_bytes()
               for package in ("contracts", "agent", "workloads") for p in (root / package).glob("*.py")}
    try:
        with zipfile.ZipFile(BytesIO(raw)) as wheel:
            names = wheel.namelist()
            if len(names) != len(set(names)) or set(sources) != {n for n in names if n.startswith(("contracts/", "agent/", "workloads/"))}:
                raise ContractError("Wheel modules differ from the installed release.")
            for name, content in sources.items():
                info = wheel.getinfo(name)
                if info.file_size != len(content) or wheel.read(info) != content:
                    raise ContractError("Wheel modules differ from the installed release.")
            metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
            if len(metadata) != 1 or wheel.getinfo(metadata[0]).file_size > 65536:
                raise ContractError("Invalid release metadata.")
            lines = wheel.read(metadata[0]).decode('utf-8').splitlines()
            if lines.count('Name: hardware-validation-lab-contracts') != 1 or lines.count('Version: 0.4.0') != 1:
                raise ContractError("Unsupported release package/version.")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeError) as exc:
        raise ContractError("Unable to verify workload wheel.") from exc
    return sha256(raw)


def run(approved_manifest, inputs, parameters, *, wheel_path):
    spec, header = validate_manifest(approved_manifest, executable=True)
    parameters = validate_parameters(spec.name, parameters, declared_header=header)
    if not isinstance(inputs, dict) or set(inputs) != set(spec.input_roles):
        raise ContractError("Explicit expected and actual input roles are required.")
    digest = verify_wheel(wheel_path)
    if digest != approved_manifest["plugin_package_sha256"]:
        raise ContractError("Installed package digest does not match the approved version.")
    result = compare(inputs["expected"], inputs["actual"], **parameters)
    result["plugin_package_sha256"] = digest
    result["plugin_version"] = approved_manifest["plugin_version"]
    return result
