"""Real clean-installed Windows runner CLI and cancellation smoke, no SQL."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True)
    parser.add_argument('--wheel', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    python, wheel = str(Path(args.python).resolve()), str(Path(args.wheel).resolve())
    output = Path(tempfile.mkdtemp(prefix='b3-installed-', dir=root/'.local'))

    def command(arguments, code):
        completed = subprocess.run([python, *arguments], cwd=output, capture_output=True, text=True, timeout=30)
        assert completed.returncode == code, (completed.returncode, completed.stdout, completed.stderr)
        return completed

    command(['-c', "import agent.runner,importlib.util; assert 'site-packages' in agent.runner.__file__; assert importlib.util.find_spec('django') is None"], 0)
    manifest = output/'manifest.json'
    command(['-m','workloads','manifest','--wheel',wheel,'--header-bytes','2','--output',str(manifest)],0)
    for filename,outcome,code in (('actual-pass.hex','PASS',0),('actual-mismatch.hex','FAIL',1),('actual-invalid.hex','ERROR',2)):
        command(['-m','agent.runner_cli','run','--wheel',wheel,'--manifest',str(manifest),
                 '--expected',str(root/'examples/can/expected-header.hex'),'--actual',str(root/'examples/can'/filename),
                 '--header-bytes','2','--output-dir',str(output/filename)],code)
        result=json.loads((output/filename/'run.json').read_text())
        assert result['outcome']==outcome and result['termination_confirmed'] and result['cleanup_status']=='COMPLETE',result
        print('PASS installed contained comparator:',outcome,'exit',code)
    for scenario, outcome in (('cooperative','TIMEOUT'),('ignore_cancel','TIMEOUT'),('descendant','TIMEOUT'),
                              ('malformed','ERROR'),('crash','ERROR'),('overflow','ERROR'),('stderr_overflow','ERROR'),
                              ('memory','ERROR'),('cpu','ERROR'),('disk','TIMEOUT'),('prepare_error','ERROR'),('cleanup_error','PASS')):
        command(['-m','agent.runner_cli','probe','--scenario',scenario,'--timeout',
                 '.7' if scenario in {'cooperative','ignore_cancel','descendant','disk'} else '5',
                 '--grace','.3','--cpu-seconds','1','--memory-mb','64','--output-dir',str(output/scenario)],2)
        result=json.loads((output/scenario/'run.json').read_text())
        assert result['outcome']==outcome and result['termination_confirmed'],result
        if scenario=='cleanup_error':
            assert result['cleanup_status']=='ERROR' and result['report_collected'] and result['quarantine_required']
        print('PASS installed probe:',scenario,result['outcome'],result['reason'],'exit 2')
    code = """import json,threading
from agent.runner import run_probe
from contracts.runner_v1 import Limits
event=threading.Event(); timer=threading.Timer(.5,event.set); timer.start()
try:
    result=run_probe('cooperative','cancel',cancel=event,limits=Limits(grace_seconds=1))
finally:
    timer.cancel(); timer.join()
assert result['outcome']=='CANCELLED' and result['termination_confirmed'] and not result['forced_termination'],result
print(json.dumps(result))
"""
    command(['-c',code],0)
    print('PASS installed cooperative cancellation, explicit CANCELLED, no forced kill')
    print('Django-free installed Windows runner evidence:',output.name)


if __name__=='__main__':
    main()
