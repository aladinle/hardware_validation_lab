"""Actual abrupt client exits after durable backend writes; no production fault knob."""
import argparse
import os
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--mode',choices=['lost-result-reply','partial-upload'],required=True)
parser.add_argument('--state-file',required=True)
parser.add_argument('--journal-root',required=True)
parser.add_argument('--wheel',required=True)
args=parser.parse_args()
from agent.client import load_state
credential,_=load_state(args.state_file)
if Path(args.state_file).name not in {'b6-pass-state.json','b6-fail-state.json'}:
    raise SystemExit('Fault helper requires the exact private review state filename.')
from agent.journal import initialize
if not Path(args.journal_root).exists():initialize(args.journal_root,credential['agent_id'],credential['project_id'])
from agent import poller
from agent.transport import Transport


class InterruptedTransport(Transport):
    uploads=0

    def post(self,path,*values,**options):
        result=super().post(path,*values,**options)
        if path.endswith('/result') and args.mode=='lost-result-reply':
            print('Abrupt exit after SQL finalization, before local acknowledgement.',flush=True)
            os._exit(86)
        return result

    def post_binary(self,*values,**options):
        result=super().post_binary(*values,**options)
        self.uploads+=1
        if self.uploads==2 and args.mode=='partial-upload':
            print('Abrupt exit during partial evidence upload, original local spool retained.',flush=True)
            os._exit(87)
        return result


poller.Transport=InterruptedTransport
poller.poll_once(args.state_file,args.journal_root,args.wheel)
raise SystemExit('Fault checkpoint was not reached.')
