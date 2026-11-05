"""Clean-installed CLI, real process crashes and optional Linux source smoke."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--python',required=True)
    parser.add_argument('--wheel',required=True)
    parser.add_argument('--source',action='store_true',help='Linux source smoke; not a clean installation claim.')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    python,wheel=str(Path(args.python).resolve()),str(Path(args.wheel).resolve())
    evidence=Path(tempfile.mkdtemp(prefix='b4-source-' if args.source else 'b4-installed-',dir=root/'.local'))
    from uuid import uuid4

    def command(arguments, code=0):
        if args.source:
            # Source mode explicitly chooses the repository CLI script while all
            # native worker creation remains fixed inside the runner.
            if arguments[:2]==['-m','workloads']:
                arguments=[str(root/'tests/b4_source_entry.py'),'compare',*arguments[2:]]
            elif arguments[:2]==['-m','agent.journal_cli']:
                arguments=[str(root/'tests/b4_source_entry.py'),'journal',*arguments[2:]]
        result=subprocess.run([python,*arguments],cwd=evidence,capture_output=True,text=True,timeout=30)
        assert result.returncode==code,(result.returncode,result.stdout,result.stderr)
        return json.loads(result.stdout) if result.stdout.strip().startswith('{') else None

    if not args.source:
        command(['-c',"import agent.journal,importlib.util; assert 'site-packages' in agent.journal.__file__; assert importlib.util.find_spec('django') is None"])
    manifest=evidence/'manifest.json'
    command(['-m','workloads','manifest','--wheel',wheel,'--header-bytes','2','--output',str(manifest)])
    journal=evidence/'journal'
    agent,project,device=str(uuid4()),str(uuid4()),str(uuid4())
    command(['-m','agent.journal_cli','init','--root',str(journal),'--agent-id',agent,'--project-id',project])
    packet=evidence/'delivery.json'
    command(['-m','agent.journal_cli','make-delivery','--root',str(journal),'--manifest',str(manifest),
             '--device-id',device,'--expected',str(root/'examples/can/expected-header.hex'),
             '--actual',str(root/'examples/can/actual-pass.hex'),'--output',str(packet)])
    delivery=['-m','agent.journal_cli','deliver','--root',str(journal),'--assignment',str(packet),
              '--expected',str(root/'examples/can/expected-header.hex'),'--actual',str(root/'examples/can/actual-pass.hex'),'--wheel',wheel]
    first=command(delivery)
    repeat=command(delivery)
    assert first['state']=='COMPLETE' and first['result']['outcome']=='PASS'
    assert repeat['completion_hash']==first['completion_hash'] and repeat['result']==first['result']
    assert not repeat['newly_accepted'] and repeat['spawn_records']==1
    print('PASS local CLI delivery/restart replay: one observed spawn, stable result/seal')
    receipt=['-m','agent.journal_cli','ack-local','--root',str(journal),'--execution-id',first['execution_id'],
             '--epoch','1','--completion-sha256',first['completion_hash'],'--confirm-local-demo']
    for _ in range(2):
        ack=command(receipt)
        assert ack['state']=='ACKNOWLEDGED' and ack['ack_source']=='local_demo' and ack['spool_retained']
    wrong=receipt.copy();wrong[wrong.index('--epoch')+1]='2';command(wrong,2)
    print('PASS repeated local-demo ACK, retained spool, stale epoch rejected')

    original=json.loads(packet.read_text())
    for stage in ('accepted','launch_intent','spawned_before_record','launched','completion_sealed','completion_committed'):
        clone=deepcopy(original);clone['execution_id']=str(uuid4());clone['device_ids']=[str(uuid4())]
        folder=evidence/stage;folder.mkdir()
        j=folder/'journal'
        command(['-m','agent.journal_cli','init','--root',str(j),'--agent-id',agent,'--project-id',project])
        request=folder/'delivery.json';request.write_text(json.dumps(clone))
        crash=[str(root/'tests/b4_crash_driver.py'),'--root',str(j),'--packet',str(request),
               '--expected',str(root/'examples/can/expected-header.hex'),'--actual',str(root/'examples/can/actual-pass.hex'),
               '--wheel',wheel,'--crash-at',stage,'--launch-marker',str(folder/'observed-launch.json')]
        # The harness resolves source modules by design. For installed proof use
        # the installed public API in a fresh interpreter with a fixed crash hook.
        if not args.source:
            code="""import json,os,sys
from pathlib import Path
from agent.journal import Journal,durable_write
packet=json.loads(Path(sys.argv[2]).read_text())
def checkpoint(stage,info):
    if stage=='spawned_before_record': durable_write(Path(sys.argv[7]),json.dumps(info).encode())
    if stage==sys.argv[6]: os._exit(86)
Journal(sys.argv[1]).deliver(packet,sys.argv[3],sys.argv[4],sys.argv[5],_checkpoint=checkpoint)
"""
            crash=['-c',code,str(j),str(request),str(root/'examples/can/expected-header.hex'),str(root/'examples/can/actual-pass.hex'),wheel,stage,str(folder/'observed-launch.json')]
        command(crash,86)
        recovered=command(['-m','agent.journal_cli','recover','--root',str(j),'--execution-id',clone['execution_id']])
        expected='COMPLETE' if stage.startswith('completion_') else 'UNCERTAIN'
        assert recovered['state']==expected,recovered
        replay=['-m','agent.journal_cli','deliver','--root',str(j),'--assignment',str(request),
                '--expected',str(root/'examples/can/expected-header.hex'),'--actual',str(root/'examples/can/actual-pass.hex'),'--wheel',wheel]
        replayed=command(replay,0 if expected=='COMPLETE' else 2)
        assert not replayed['newly_accepted'] and replayed['spawn_records']<=1
        print('PASS actual abrupt crash:',stage,'->',expected,'without relaunch')
    print('Journal evidence:',evidence.name)


if __name__=='__main__':
    main()
