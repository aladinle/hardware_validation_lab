import json
import os
from pathlib import Path
import platform
import stat
from datetime import datetime, timezone
import uuid
from contracts.agents_v1 import AGENT_VERSION, MAX_MESSAGE_BYTES, parse_credential, parse_idle_reply
from contracts.v1 import ContractError
from .transport import AgentError, Transport, server_url


def platform_name():
    value = platform.system()
    return value if value in {"Windows", "Linux", "Darwin"} else "Other"


def read_document(path):
    try:
        path = Path(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024 or info.st_size > MAX_MESSAGE_BYTES:
            raise AgentError("Credential file must be a bounded regular file without links.")
        return json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeError):
        raise AgentError("Unable to read a valid private credential file.") from None


def unexpired(document):
    if datetime.fromisoformat(document["expires_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise AgentError("Credential file has expired; contact the project administrator.")


def save_new(path, document):
    path = Path(path)
    # Chosen local state path, never a remote request parameter. Existing state is preserved.
    for ancestor in (path.parent, *path.parent.parents):
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), "st_file_attributes", 0) & 1024):
            raise AgentError("State directory must not traverse links/reparse points.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise AgentError("State file could not be created; existing files are preserved.") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise AgentError("Unable to save private state; ask the administrator to reissue enrollment if needed.") from None
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def enroll_client(base_url, invitation_path, state_path):
    if Path(state_path).exists():
        raise AgentError("State file already exists; choose a new path or use the credential replacement workflow.")
    try:
        invitation = parse_credential(read_document(invitation_path), enrollment=True)
        unexpired(invitation)
        base_url = server_url(base_url)
        response = Transport(base_url).post(f"/api/v1/agents/{invitation['agent_id']}/enroll",
                    {"schema_version": 1, "agent_version": AGENT_VERSION, "platform": platform_name(), "device_ids": invitation["device_ids"]},
                    invitation["token"], "Enrollment")
        credential = parse_credential(response)
        if any(credential[key] != invitation[key] for key in ("agent_id", "project_id", "device_ids")):
            raise AgentError("Enrollment response scope differs from the approved identity.")
        unexpired(credential)
    except ContractError:
        raise AgentError("Enrollment response violates the agent protocol.") from None
    save_new(state_path, {**credential, "server_url": base_url})
    return {"agent_id": credential["agent_id"], "enrolled": True, "execution_available": False}


def load_state(path, *, check_expiry=True):
    raw = read_document(path)
    if not isinstance(raw, dict) or "server_url" not in raw:
        raise AgentError("State file is invalid.")
    origin = server_url(raw["server_url"])
    try:
        document = parse_credential({key: value for key, value in raw.items() if key != "server_url"})
        if check_expiry:
            unexpired(document)
    except ContractError:
        raise AgentError("State file violates the agent protocol.") from None
    return document, origin


def contact_once(path):
    credential, origin = load_state(path)
    heartbeat_id = str(uuid.uuid4())
    payload = {"schema_version": 1, "heartbeat_id": heartbeat_id, "sent_at": datetime.now(timezone.utc).isoformat(),
               "agent_version": AGENT_VERSION, "platform": platform_name(), "device_ids": credential["device_ids"],
               "observations": [], "active_execution_id": None, "ready": False}
    try:
        result = parse_idle_reply(Transport(origin).post(f"/api/v1/agents/{credential['agent_id']}/heartbeat", payload, credential["token"]), credential["agent_id"], heartbeat_id)
    except ContractError:
        raise AgentError("Heartbeat response violates the idle agent protocol.") from None
    # Only allowlisted non-secret status is ever printed by the CLI.
    return {"agent_id": credential["agent_id"], "contact_received": True, "last_contact_at": result["last_contact_at"],
            "assignment": None, "execution_available": False, "devices_ready": False}


def replace_credential(state_path, credential_path, output_path):
    # Save to a NEW path, leaving old state untouched; old token is revoked server-side.
    old, origin = load_state(state_path, check_expiry=False)
    try:
        new = parse_credential(read_document(credential_path))
        unexpired(new)
    except ContractError:
        raise AgentError("Replacement credential is invalid.") from None
    if any(old[key] != new[key] for key in ("agent_id", "project_id", "device_ids")):
        raise AgentError("Replacement must preserve agent/project/device scope; scope changes require reenrollment.")
    save_new(output_path, {**new, "server_url": origin})
    return {"agent_id": new["agent_id"], "credential_saved": True, "execution_available": False}
