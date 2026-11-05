"""Actual Linux process-group/resource probes; no Windows or SQL claims."""
from pathlib import Path
import json
import sys
import tempfile
import threading

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from agent.runner import run_can, run_probe
from contracts.plugins import executable_manifest
from contracts.runner_v1 import Limits
from workloads.registry import verify_wheel


def main():
    assert sys.platform.startswith('linux')
    wheel = Path(sys.argv[1]).resolve()
    output = Path(tempfile.mkdtemp(prefix='b3-linux-', dir=root / '.local'))
    limits = Limits(cpu_percent=100, wall_seconds=5)
    digest = verify_wheel(wheel)
    manifest = executable_manifest(2, digest)
    for name, outcome in (('actual-pass.hex', 'PASS'), ('actual-mismatch.hex', 'FAIL'), ('actual-invalid.hex', 'ERROR')):
        result = run_can(manifest, root/'examples/can/expected-header.hex', root/'examples/can'/name,
                         wheel, output/name, parameters={'header_bytes': 2}, limits=limits)
        assert result['outcome'] == outcome, result
        assert result['termination_confirmed'] and result['cleanup_status'] == 'COMPLETE', result
        print('PASS Linux CAN:', outcome)
    for scenario in ('cooperative','ignore_cancel','descendant','crash','malformed','overflow','memory','cpu','disk'):
        short = Limits(cpu_percent=100, wall_seconds=.6 if scenario in {'cooperative','ignore_cancel','descendant'} else 5,
                       grace_seconds=.3, stdout_bytes=1024, memory_mb=64, cpu_seconds=1, disk_bytes=32768)
        result = run_probe(scenario, output/scenario, limits=short)
        expected = 'TIMEOUT' if scenario in {'cooperative','ignore_cancel','descendant'} else 'ERROR'
        assert result['outcome'] == expected, result
        assert result['termination_confirmed'] and result['cleanup_status'] == 'COMPLETE', result
        if scenario == 'descendant':
            assert result['accounting']['total_processes'] >= 2
        print('PASS Linux probe:', scenario, result['outcome'], result['reason'])
    cancel = threading.Event()
    timer = threading.Timer(.5, cancel.set)
    timer.start()
    try:
        result = run_probe('cooperative', output/'cancel', limits=limits, cancel=cancel)
    finally:
        timer.cancel()
        timer.join()
    assert result['outcome'] == 'CANCELLED' and not result['forced_termination'], result
    print('PASS Linux cooperative cancellation')
    result = run_probe('descendant', output/'process-limit', limits=Limits(cpu_percent=100, processes=1, grace_seconds=.1))
    assert result['reason']=='PROCESS_LIMIT' and result['termination_confirmed'],result
    print('PASS Linux monitored process count')
    link = output/'linked-input.hex'
    link.symlink_to(root/'examples/can/expected-header.hex')
    result = run_can(manifest, link, root/'examples/can/actual-pass.hex', wheel, output/'link-denied',
                     parameters={'header_bytes':2}, limits=limits)
    assert result['outcome']=='ERROR' and result['process_id'] is None,result
    print('PASS Linux actual symlink input rejection before launch')
    (output/'smoke.json').write_text(json.dumps({'platform':sys.platform,'wheel_sha256':digest,'checks':15}))
    print('Linux evidence directory:',output.name)


if __name__ == '__main__':
    main()
