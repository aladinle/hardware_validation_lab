"""Owned crash/replay harness, not a backend client or physical test."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from agent.journal import Journal, durable_write
from contracts.journal_v1 import canonical
from contracts.runner_v1 import strict_json


def main():
    parser=argparse.ArgumentParser()
    for name in ('root','packet','expected','actual','wheel'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--crash-at',choices=('accepted','launch_intent','spawned_before_record','spawned_recorded','gate_recorded','launched','completion_sealed','completion_committed'))
    parser.add_argument('--launch-marker')
    args=parser.parse_args()

    def checkpoint(stage,info):
        if stage=='spawned_before_record' and args.launch_marker:
            durable_write(Path(args.launch_marker),canonical(info).encode())
        if stage==args.crash_at:
            os._exit(86)

    result=Journal(args.root).deliver(strict_json(Path(args.packet).read_bytes()),args.expected,args.actual,args.wheel,_checkpoint=checkpoint)
    print(canonical(result),flush=True)


if __name__=='__main__':
    main()
