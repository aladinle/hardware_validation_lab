"""Explicit simulator polling client. No output upload/ACK or resource release."""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import time
from contracts.agents_v1 import schema
from contracts.dispatch_v1 import poll_reply
from contracts.journal_v1 import canonical
from contracts.v1 import ContractError
from workloads.registry import verify_wheel
from .client import load_state
from .journal import Journal, JournalError, durable_write, initialize
from .runner import bounded_read, safe_path
from .transport import AgentError, Transport


def bind(journal,origin):
    with journal.connect(write=True) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS server_binding(id INTEGER PRIMARY KEY CHECK(id=1),origin TEXT NOT NULL)')
        existing=connection.execute('SELECT origin FROM server_binding WHERE id=1').fetchone()
        if existing and existing['origin']!=origin:
            raise JournalError('Journal is bound to another authenticated backend.')
        if not existing:
            if connection.execute('SELECT count(*) FROM executions').fetchone()[0]:
                raise JournalError('Use a new empty server journal, not a prior demo ledger.')
            connection.execute('INSERT INTO server_binding VALUES(1,?)',(origin,))


def poll_once(state_file,journal_root,wheel):
    credential,origin=load_state(state_file)
    journal=Journal(journal_root)
    if (journal.meta['agent_id'],journal.meta['project_id'])!=(credential['agent_id'],credential['project_id']):
        raise JournalError('Journal receiver identity mismatch.')
    package=verify_wheel(wheel)
    transport=Transport(origin)
    route=f"/api/v1/agents/{credential['agent_id']}"
    response=transport.post(route+'/poll',{'schema_version':1,'package_sha256':package,'device_ids':credential['device_ids'],
                                          'platform':'Windows' if os.name=='nt' else 'Linux' if sys.platform.startswith('linux') else 'Other'},credential['token'])
    packet,claim=poll_reply(response,credential,package)
    bind(journal,origin)
    if packet is None:
        return {'assignment_received':False,'hardware_ready':False,'source':'simulated'}
    identity={'schema_version':1,'execution_id':packet['execution_id'],'epoch':packet['epoch'],'claim_token':claim}
    accepted=transport.post(route+'/claim',identity,credential['token'])
    schema(accepted,{'execution_id','epoch','state'})
    if (accepted['execution_id'],accepted['epoch'])!=(packet['execution_id'],packet['epoch']) or accepted['state'] not in ('running','awaiting_evidence'):
        raise AgentError('Claim reply violates assignment identity.')
    with journal.connect() as connection:
        existing=connection.execute('SELECT 1 FROM executions WHERE execution_id=?',(packet['execution_id'],)).fetchone()
    incoming=safe_path(journal.root/'incoming'/packet['execution_id'])
    if not existing:
        incoming.mkdir(parents=True,exist_ok=True,mode=0o700)
        for reference in packet['inputs']:
            path=incoming/(reference['role']+'.hex')
            if path.exists():
                data=bounded_read(path,1024*1024)
            else:
                data=transport.post_bytes(route+'/input',{**identity,'role':reference['role']},credential['token'],maximum=reference['size'])
            if len(data)!=reference['size'] or hashlib.sha256(data).hexdigest()!=reference['sha256']:
                raise AgentError('Scoped input checksum differs from assignment.')
            if not path.exists():
                try:durable_write(path,data)
                except FileExistsError:
                    if bounded_read(path,1024*1024)!=data:raise JournalError('Concurrent input cache conflict.')
    # Recheck current authority/fence immediately before the local launch path.
    checked=transport.post(route+'/claim',identity,credential['token'])
    schema(checked,{'execution_id','epoch','state'})
    if (checked['execution_id'],checked['epoch'])!=(packet['execution_id'],packet['epoch']) or checked['state'] not in ('running','awaiting_evidence'):
        raise AgentError('Final claim identity changed before journal handoff.')
    result=journal.deliver(packet,incoming/'expected.hex',incoming/'actual.hex',wheel,_server=True)
    receipt_recorded=False
    if result['state'] in ('COMPLETE','ACKNOWLEDGED'):
        receipt=transport.post(route+'/receipt',{**identity,'completion_sha256':result['completion_hash']},credential['token'])
        schema(receipt,{'execution_id','epoch','state','evidence_acknowledged','leases_released'})
        if (receipt['execution_id'],receipt['epoch'])!=(packet['execution_id'],packet['epoch']) or receipt['state']!='awaiting_evidence' or receipt['evidence_acknowledged'] is not False or receipt['leases_released'] is not False:
            raise AgentError('Unexpected evidence/release acknowledgement.')
        receipt_recorded=True
    # Retain the owned incoming cache too in this single-assignment gate; no
    # arbitrary recursive cleanup or automatic evidence ACK is performed.
    return {'assignment_received':True,'execution_id':packet['execution_id'],'epoch':packet['epoch'],'journal_state':result['state'],
            'newly_accepted':result['newly_accepted'],'local_outcome':result['result']['outcome'] if result['result'] else None,
            'receipt_recorded':receipt_recorded,'evidence_acknowledged':False,'leases_released':False,'hardware_ready':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Explicit outbound synthetic polling; no hardware or output upload.')
    parser.add_argument('--state-file',required=True)
    parser.add_argument('--journal-root',required=True)
    parser.add_argument('--wheel',required=True)
    parser.add_argument('--init-journal',action='store_true',help='Create a new receiver-scoped journal; never overwrite an old one.')
    parser.add_argument('--count',type=int,default=1)
    parser.add_argument('--interval',type=float,default=1)
    args=parser.parse_args(argv)
    try:
        if not 1<=args.count<=1000 or not .1<=args.interval<=60:raise AgentError('Use bounded count/interval.')
        if args.init_journal:
            credential,_=load_state(args.state_file)
            initialize(args.journal_root,credential['agent_id'],credential['project_id'])
        for index in range(args.count):
            result=poll_once(args.state_file,args.journal_root,args.wheel)
            print(canonical(result),flush=True)
            if index+1<args.count:time.sleep(args.interval)
        return 0
    except (AgentError,JournalError,ContractError,OSError,ValueError) as exc:
        print('Simulator poll rejected or unavailable; retained journal/evidence must be reconciled before reuse.',file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__=='__main__':raise SystemExit(main())
