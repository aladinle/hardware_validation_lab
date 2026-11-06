"""Bounded evidence envelopes. Paths are fixed logical names, never host paths."""
import hashlib
from .agents_v1 import schema
from .journal_v1 import canonical, checksum, sha
from .runner_v1 import strict_json
from .v1 import ContractError

OUTPUT_LIMITS = {'run/run.json':32768, 'run/report.json':8*1024*1024,
                 'run/report.txt':65536, 'run/stdout.bin':8*1024*1024, 'run/stderr.bin':65536}
MAX_OUTPUT_TOTAL = 18*1024*1024


def output_name(value):
    if not isinstance(value,str) or value not in OUTPUT_LIMITS:
        raise ContractError('Unknown fixed evidence name.')
    return value


def validate_completion(seal, packet):
    schema(seal, {'execution_id','epoch','request_hash','result','files'})
    if (seal['execution_id'],seal['epoch'],seal['request_hash']) != (packet['execution_id'],packet['epoch'],checksum(packet)) or type(seal['epoch']) is not int:
        raise ContractError('Completion assignment identity mismatch.')
    files=seal['files']
    allowed=set(OUTPUT_LIMITS)|{'delivery.json','inputs/expected.hex','inputs/actual.hex','inputs/plugin.whl'}
    if not isinstance(files,dict) or not {'delivery.json','inputs/expected.hex','inputs/actual.hex','inputs/plugin.whl','run/run.json'}<=set(files) or not set(files)<=allowed:
        raise ContractError('Invalid sealed file inventory.')
    for name,ref in files.items():
        if not isinstance(ref,dict) or set(ref)!={'size','sha256'} or type(ref['size']) is not int or not 0<=ref['size']<=OUTPUT_LIMITS.get(name,20*1024*1024):
            raise ContractError('Invalid sealed file bound.')
        sha(ref['sha256'])
    if files['delivery.json']!={'size':len(canonical(packet).encode()),'sha256':checksum(packet)}:
        raise ContractError('Sealed delivery mismatch.')
    for ref in packet['inputs']:
        if files['inputs/'+ref['role']+'.hex']!={'size':ref['size'],'sha256':ref['sha256']}:
            raise ContractError('Sealed input mismatch.')
    if files['inputs/plugin.whl']['sha256']!=packet['manifest']['plugin_package_sha256']:
        raise ContractError('Sealed package mismatch.')
    result=seal['result']
    if not isinstance(result,dict) or len(canonical(result).encode())>32768:
        raise ContractError('Invalid bounded runner record.')
    if result.get('schema_version')!=1 or type(result.get('schema_version')) is not int or result.get('source')!='simulated' or result.get('probe') is not None:
        raise ContractError('Only real synthetic runner records are supported.')
    if result.get('outcome') not in {'PASS','FAIL','ERROR','TIMEOUT','CANCELLED'} or result.get('evaluation_status') not in {'EVALUATED','NOT_EVALUATED'}:
        raise ContractError('Unknown outcome/evaluation.')
    if (result['outcome'] in {'PASS','FAIL'}) != (result['evaluation_status']=='EVALUATED'):
        raise ContractError('Inconsistent outcome/evaluation.')
    if result.get('termination_confirmed') is not True or type(result.get('quarantine_required')) is not bool:
        raise ContractError('No confirmed local process termination.')
    if type(result.get('report_collected')) is not bool or type(result.get('launch_gate_open')) is not bool:
        raise ContractError('Invalid collected-report/launch declaration.')
    if result.get('cleanup_status') not in {'COMPLETE','ERROR'} or result.get('evidence_status') not in {'COMPLETE','INCOMPLETE'} or result.get('hardware_readiness')!='NOT_EVALUATED':
        raise ContractError('Invalid separate cleanup/evidence/readiness state.')
    if (result['cleanup_status']!='COMPLETE' or result['evidence_status']!='COMPLETE') and not result['quarantine_required']:
        raise ContractError('Unsafe clean completion assertion.')
    if result['evidence_status']=='COMPLETE' and result['launch_gate_open'] and not {'run/stdout.bin','run/stderr.bin'}<=set(files):
        raise ContractError('Missing completed process capture evidence.')
    if result.get('input_sha256')!={ref['role']:ref['sha256'] for ref in packet['inputs']} or result.get('limits')!=packet['limits']:
        raise ContractError('Runner accepted context conflict.')
    duration=result.get('duration_seconds')
    if type(duration) not in (int,float) or not 0<=duration<=600:
        raise ContractError('Invalid measured duration.')
    if result.get('report_collected') is True and not {'run/report.json','run/report.txt'}<=set(files):
        raise ContractError('Missing collected report.')
    if result['outcome'] in {'PASS','FAIL'} and (result.get('report_collected') is not True or result.get('reason')!='PLUGIN_RESULT'):
        raise ContractError('Assertion outcome requires collected plugin evidence.')
    return result


def validate_report_bytes(raw,packet,result):
    """Bind plugin identity; full CAN evidence validation is reused by backend."""
    report=strict_json(raw)
    if not isinstance(report,dict) or report.get('outcome')!=result['outcome'] or report.get('evaluation_status')!=result['evaluation_status'] or report.get('plugin_package_sha256')!=packet['manifest']['plugin_package_sha256']:
        raise ContractError('Collected report differs from runner outcome/package.')
    return report


def content_sha(raw):
    return hashlib.sha256(raw).hexdigest()
