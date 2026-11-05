"""Strict local delivery demo contract; not a backend-authenticated assignment."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from .agents_v1 import ids, schema
from .plugins import validate_manifest, validate_parameters
from .runner_v1 import Limits
from .v1 import ContractError, exact_keys, identifier


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ContractError('Expected SHA-256.')
    return value


def parse_delivery(value):
    schema(value, {'source', 'agent_id', 'project_id', 'execution_id', 'job_id', 'device_ids', 'epoch',
                   'deadline', 'manifest', 'parameters', 'inputs', 'limits'})
    if value['source'] != 'local_journal_demo':
        raise ContractError('Only explicit local demonstration deliveries are enabled.')
    result = dict(value)
    for key in ('agent_id','project_id','execution_id','job_id'):
        result[key] = identifier(value[key])
    result['device_ids'] = list(ids(value['device_ids']))
    if type(value['epoch']) is not int or not 1 <= value['epoch'] <= 2**63 - 1:
        raise ContractError('Invalid epoch.')
    try:
        deadline = datetime.fromisoformat(value['deadline'].replace('Z','+00:00'))
        if deadline.utcoffset() is None:
            raise ValueError
        result['deadline'] = deadline.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContractError('Expected an aware execution deadline.') from exc
    spec, header = validate_manifest(value['manifest'], executable=True)
    result['parameters'] = validate_parameters(spec.name, value['parameters'], declared_header=header)
    if not isinstance(value['limits'], dict) or set(value['limits']) != set(asdict(Limits())):
        raise ContractError('Provide the complete bounded runner policy.')
    result['limits'] = asdict(Limits(**value['limits']).validate())
    if not isinstance(value['inputs'], list) or len(value['inputs']) != 2:
        raise ContractError('Explicit expected/actual references required.')
    references = {}
    for reference in value['inputs']:
        exact_keys(reference, {'role','artifact_id','sha256','size'})
        role = reference['role']
        if not isinstance(role,str) or role not in spec.input_roles or role in references:
            raise ContractError('Invalid/duplicate input role.')
        if type(reference['size']) is not int or not 0 <= reference['size'] <= 1024*1024:
            raise ContractError('Invalid bounded input size.')
        references[role] = {**reference, 'artifact_id':identifier(reference['artifact_id']), 'sha256':sha(reference['sha256'])}
    result['inputs'] = [references[role] for role in sorted(references)]
    if len(canonical(result).encode()) > 65536:
        raise ContractError('Delivery too large.')
    return result
