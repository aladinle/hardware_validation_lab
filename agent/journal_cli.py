"""Local-only durable-delivery demo. No backend assignment/upload endpoint."""
import argparse
from dataclasses import asdict
from datetime import timedelta
import hashlib
from pathlib import Path
import sys
from uuid import uuid4

from contracts.journal_v1 import canonical, parse_delivery
from contracts.runner_v1 import Limits, strict_json
from contracts.v1 import ContractError
from .journal import Journal, JournalError, durable_write, initialize, now
from .runner import bounded_read, safe_path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local journal/spool demonstration; no backend dispatch or real upload.')
    commands = parser.add_subparsers(dest='command',required=True)
    init = commands.add_parser('init')
    init.add_argument('--agent-id',required=True)
    init.add_argument('--project-id',required=True)
    init.add_argument('--quota-mb',type=int,default=256)
    make = commands.add_parser('make-delivery')
    make.add_argument('--manifest',required=True)
    make.add_argument('--device-id',required=True,action='append')
    make.add_argument('--output',required=True)
    make.add_argument('--epoch',type=int,default=1)
    deliver = commands.add_parser('deliver')
    deliver.add_argument('--assignment',required=True)
    for item in (make,deliver):
        item.add_argument('--expected',required=True)
        item.add_argument('--actual',required=True)
    deliver.add_argument('--wheel',required=True)
    for item in ('status','recover','ack-local'):
        command = commands.add_parser(item)
        command.add_argument('--execution-id',required=True)
        if item == 'ack-local':
            command.add_argument('--epoch',required=True,type=int)
            command.add_argument('--completion-sha256',required=True)
            command.add_argument('--confirm-local-demo',action='store_true',required=True)
    for command in commands.choices.values():
        command.add_argument('--root',required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            journal = initialize(args.root,args.agent_id,args.project_id,quota_mb=args.quota_mb)
            result = {'initialized':True,'agent_id':journal.meta['agent_id'],'project_id':journal.meta['project_id'],'dispatch_available':False}
        else:
            journal = Journal(args.root)
            if args.command == 'make-delivery':
                manifest = strict_json(bounded_read(args.manifest,65536))
                references = []
                for role in ('expected','actual'):
                    data = bounded_read(getattr(args,role),1024*1024)
                    references.append({'role':role,'artifact_id':str(uuid4()),'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
                packet = parse_delivery({'schema_version':1,'source':'local_journal_demo','agent_id':journal.meta['agent_id'],
                    'project_id':journal.meta['project_id'],'execution_id':str(uuid4()),'job_id':str(uuid4()),'device_ids':args.device_id,
                    'epoch':args.epoch,'deadline':(now()+timedelta(hours=1)).isoformat(),'manifest':manifest,
                    'parameters':{'header_bytes':manifest['parameter_schema']['properties']['header_bytes']['const']},
                    'inputs':references,'limits':asdict(Limits(cpu_percent=50 if sys.platform=='win32' else 100))})
                durable_write(safe_path(args.output),canonical(packet).encode())
                result = {'execution_id':packet['execution_id'],'epoch':packet['epoch'],'source':'local_journal_demo'}
            elif args.command == 'deliver':
                packet = strict_json(bounded_read(args.assignment,65536))
                result = journal.deliver(packet,args.expected,args.actual,args.wheel)
            elif args.command == 'status':
                result = journal.status(args.execution_id)
            elif args.command == 'recover':
                result = journal.reconcile(args.execution_id)
            else:
                result = journal.acknowledge_local(args.execution_id,args.epoch,args.completion_sha256)
        print(canonical(result))
        if args.command == 'deliver':
            outcome = result.get('result') or {}
            if result['state'] not in ('COMPLETE','ACKNOWLEDGED') or outcome.get('quarantine_required') is not False:
                return 2
            return {'PASS':0,'FAIL':1,'ERROR':2,'TIMEOUT':2,'CANCELLED':2}[outcome['outcome']]
        return 0
    except (JournalError,ContractError,OSError,ValueError,KeyError):
        print('Local journal operation rejected; verify identity/epoch, retained evidence, capacity and state. No new retry is authorized.',file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted; retain this journal and reconcile existing execution IDs before further work.',file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
