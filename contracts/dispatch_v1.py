"""Authenticated simulator polling contracts; no remote executable/path fields."""
import re
from .agents_v1 import schema
from .journal_v1 import parse_delivery
from .v1 import ContractError


def poll_reply(value,credential,package):
    schema(value,{'assignment','claim_token','hardware_ready'})
    if value['hardware_ready'] is not False:
        raise ContractError('No physical readiness assertion is supported.')
    if value['assignment'] is None:
        if value['claim_token'] is not None:raise ContractError('Unexpected idle claim.')
        return None,None
    packet=parse_delivery(value['assignment'],source='server_simulated_assignment')
    if (packet['agent_id'],packet['project_id'])!=(credential['agent_id'],credential['project_id']) or not set(packet['device_ids'])<=set(credential['device_ids']):
        raise ContractError('Assignment receiver/scope mismatch.')
    if packet['manifest']['plugin_package_sha256']!=package or not isinstance(value['claim_token'],str) or not re.fullmatch('hvc_[A-Za-z0-9_-]{43}',value['claim_token']):
        raise ContractError('Assignment package/claim mismatch.')
    return packet,value['claim_token']
