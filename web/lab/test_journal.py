"""Local SQLite/process crash tests. Not PostgreSQL scheduling evidence."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent.journal import Journal, JournalError, initialize, now
from agent.process_identity import identity, inspect
from contracts.journal_v1 import canonical, parse_delivery
from contracts.runner_v1 import Limits
from contracts.v1 import ContractError
from contracts.plugins import executable_manifest
from workloads.registry import verify_wheel
from .test_can_plugin import matching_fixture_wheel


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.repo=Path(__file__).resolve().parents[2]
        self.storage=tempfile.TemporaryDirectory(prefix='b4-test-',dir=self.repo/'.local')
        self.base=Path(self.storage.name).resolve()
        self.assertTrue(self.base.is_relative_to((self.repo/'.local').resolve()))
        self.addCleanup(self.storage.cleanup)
        self.journal=initialize(self.base/'journal',str(uuid4()),str(uuid4()),quota_mb=1024)
        self.expected=self.base/'expected.hex'; self.expected.write_bytes(b'DE AD 00 01 AA FF\n')
        self.actual=self.base/'actual.hex'; self.actual.write_bytes(b'00 01 AA FF\n')
        self.wheel=self.base/'fixture.whl'; matching_fixture_wheel(self.wheel)
        self.packet={'schema_version':1,'source':'local_journal_demo','agent_id':self.journal.meta['agent_id'],
            'project_id':self.journal.meta['project_id'],'execution_id':str(uuid4()),'job_id':str(uuid4()),
            'device_ids':[str(uuid4())],'epoch':1,'deadline':(now()+timedelta(hours=1)).isoformat(),
            'manifest':executable_manifest(2,verify_wheel(self.wheel)),'parameters':{'header_bytes':2},'limits':asdict(Limits(cpu_percent=50 if sys.platform=='win32' else 100)),
            'inputs':[{'role':role,'artifact_id':str(uuid4()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':len(path.read_bytes())}
                      for role,path in [('expected',self.expected),('actual',self.actual)]]}
        self.packet_file=self.base/'delivery.json'; self.packet_file.write_text(canonical(self.packet))

    def command(self, *, crash=None, marker=None):
        command=[sys.executable,str(self.repo/'tests/b4_crash_driver.py'),'--root',str(self.journal.root),
            '--packet',str(self.packet_file),'--expected',str(self.expected),'--actual',str(self.actual),'--wheel',str(self.wheel)]
        if crash: command+=['--crash-at',crash]
        if marker: command+=['--launch-marker',str(marker)]
        return command

    def driver(self, *, crash=None, marker=None):
        result=subprocess.run(self.command(crash=crash,marker=marker),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,86 if crash else 0,result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def test_delivery_replay_survives_new_process_and_input_removal(self):
        marker=self.base/'launch.json'
        first=self.driver(marker=marker)
        self.assertEqual(first['state'],'COMPLETE')
        self.assertEqual(first['result']['outcome'],'PASS')
        self.assertEqual((first['launch_intents'],first['spawn_records']),(1,1))
        self.expected.unlink(); self.actual.unlink(); self.wheel.unlink()
        repeat=self.driver(marker=self.base/'must-not-launch.json')
        self.assertFalse(repeat['newly_accepted'])
        self.assertEqual(first['completion_hash'],repeat['completion_hash'])
        self.assertEqual(first['result'],repeat['result'])
        self.assertFalse((self.base/'must-not-launch.json').exists())

    def test_competing_deliveries_record_one_native_process_creation(self):
        children=[subprocess.Popen(self.command(marker=self.base/f'launch-{i}.json'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(2)]
        results=[]
        for child in children:
            stdout,stderr=child.communicate(timeout=30)
            self.assertEqual(child.returncode,0,stderr)
            results.append(json.loads(stdout))
        self.assertEqual(sum(r['newly_accepted'] for r in results),1)
        self.assertEqual(len(list(self.base.glob('launch-*.json'))),1)
        final=Journal(self.journal.root).reconcile(self.packet['execution_id'])
        self.assertEqual(final['state'],'COMPLETE')
        self.assertEqual((final['launch_intents'],final['spawn_records']),(1,1))

    def test_epoch_content_and_identity_conflicts_do_not_launch(self):
        self.driver()
        for change in ({'epoch':2},{'job_id':str(uuid4())},{'agent_id':str(uuid4())},{'project_id':str(uuid4())}):
            packet={**self.packet,**change}
            with self.assertRaises(JournalError):
                self.journal.deliver(packet,self.expected,self.actual,self.wheel)
        self.assertEqual(self.journal.status(self.packet['execution_id'])['spawn_records'],1)

    def test_expired_new_delivery_rejected_but_expired_replay_is_stable(self):
        expired={**self.packet,'deadline':(now()-timedelta(seconds=1)).isoformat()}
        with self.assertRaises(JournalError): self.journal.accept(expired)
        first=self.driver()
        with patch('agent.journal.now',return_value=now()+timedelta(days=1)):
            _,accepted=self.journal.accept(self.packet)
        self.assertFalse(accepted)
        self.assertEqual(first['completion_hash'],self.journal.status(self.packet['execution_id'])['completion_hash'])

    def test_crash_before_launch_and_gap_before_pid_record_never_relaunch(self):
        for stage in ('accepted','launch_intent','spawned_before_record','launched'):
            with self.subTest(stage=stage):
                if stage!='accepted':
                    self.packet['execution_id']=str(uuid4()); self.packet['device_ids']=[str(uuid4())]
                    self.packet_file.write_text(canonical(self.packet))
                marker=self.base/f'{stage}.json'
                self.driver(crash=stage,marker=marker)
                replay=self.driver(marker=self.base/f'no-retry-{stage}.json')
                self.assertEqual(replay['state'],'UNCERTAIN')
                self.assertFalse((self.base/f'no-retry-{stage}.json').exists())
                if marker.exists():
                    child=json.loads(marker.read_text())
                    deadline=time.monotonic()+8
                    while inspect(child)=='ALIVE' and time.monotonic()<deadline: time.sleep(.05)
                    self.assertIn(inspect(child),('GONE','DIFFERENT'))
                blocked=deepcopy(self.packet); blocked['execution_id']=str(uuid4())
                with self.assertRaises(JournalError): self.journal.accept(blocked)

    def test_valid_seal_recovers_sql_commit_gap_without_new_process(self):
        self.driver(crash='completion_sealed',marker=self.base/'launch.json')
        self.assertEqual(self.journal.row(self.packet['execution_id'])['state'],'RUNNING')
        recovered=self.driver(marker=self.base/'must-not-launch.json')
        self.assertEqual(recovered['state'],'COMPLETE')
        self.assertEqual(recovered['result']['outcome'],'PASS')
        self.assertFalse((self.base/'must-not-launch.json').exists())

    def test_commit_before_lost_reply_and_repeated_local_ack_keep_spool(self):
        self.driver(crash='completion_committed')
        status=self.journal.reconcile(self.packet['execution_id'])
        for _ in range(2):
            receipt=self.journal.acknowledge_local(status['execution_id'],1,status['completion_hash'])
            self.assertEqual(receipt['state'],'ACKNOWLEDGED')
            self.assertTrue(receipt['spool_retained'])
        self.assertEqual(receipt['ack_source'],'local_demo')
        with self.assertRaises(JournalError): self.journal.acknowledge_local(status['execution_id'],2,status['completion_hash'])
        with self.assertRaises(JournalError): self.journal.acknowledge_local(status['execution_id'],1,'0'*64)
        repeat=self.driver()
        self.assertEqual(repeat['state'],'ACKNOWLEDGED')
        self.assertEqual(repeat['spawn_records'],1)
        self.assertEqual(self.journal.reconcile(status['execution_id'].upper())['completion_hash'],status['completion_hash'])

    def test_evidence_conflict_refuses_ack_and_never_overwrites_result(self):
        status=self.driver()
        path=self.journal.spool/status['execution_id']/'run/report.json'
        path.write_bytes(b'changed')
        with self.assertRaises(JournalError): self.journal.acknowledge_local(status['execution_id'],1,status['completion_hash'])
        with self.assertRaises(JournalError): self.journal.reconcile(status['execution_id'])
        self.assertEqual(self.journal.status(status['execution_id'])['result']['outcome'],'PASS')
        self.assertEqual(path.read_bytes(),b'changed')

    def test_capacity_and_missing_ledger_fail_closed(self):
        small=initialize(self.base/'small',self.packet['agent_id'],self.packet['project_id'],quota_mb=64)
        with self.assertRaises(JournalError): small.accept(self.packet)
        self.driver()
        self.journal.db.unlink()
        with self.assertRaises(JournalError): Journal(self.journal.root)
        with self.assertRaises(FileExistsError): initialize(self.journal.root,self.packet['agent_id'],self.packet['project_id'])
        self.assertTrue((self.journal.spool/self.packet['execution_id']/'completion.json').exists())

    def test_live_supervisor_and_unknown_pid_are_not_expired_by_time(self):
        self.journal.accept(self.packet)
        row=self.journal.reconcile(self.packet['execution_id'])
        self.assertEqual(row['state'],'ACCEPTED')
        with patch('agent.journal.inspect',return_value='UNKNOWN'):
            row=self.journal.reconcile(self.packet['execution_id'])
        self.assertEqual(row['state'],'UNCERTAIN')
        token=identity(); self.assertEqual(inspect(token),'ALIVE')
        self.assertEqual(inspect({**token,'birth':'different'}),'DIFFERENT')

    def test_strict_roles_epoch_and_command_fields(self):
        for changes in ({'epoch':True},{'epoch':0},{'command':'anything'},{'source':'backend'}, {'inputs':[]}):
            with self.assertRaises(ContractError): parse_delivery({**self.packet,**changes})
        packet=deepcopy(self.packet);packet['inputs'][1]['role']=packet['inputs'][0]['role']
        with self.assertRaises(ContractError): parse_delivery(packet)

    def test_record_cap_keeps_dedup_record_and_corrupt_db_is_not_replaced(self):
        limited=initialize(self.base/'limited',self.packet['agent_id'],self.packet['project_id'],max_records=1)
        limited.accept(self.packet)
        packet={**self.packet,'execution_id':str(uuid4()),'device_ids':[str(uuid4())]}
        with self.assertRaises(JournalError): limited.accept(packet)
        self.assertFalse(limited.accept(self.packet)[1])
        corrupt=initialize(self.base/'corrupt',self.packet['agent_id'],self.packet['project_id'])
        corrupt.db.write_bytes(b'not a SQLite database')
        with self.assertRaises(JournalError): Journal(corrupt.root)
        self.assertEqual(corrupt.db.read_bytes(),b'not a SQLite database')

    def test_invalid_source_checksum_does_not_claim_device_or_execution(self):
        self.actual.write_bytes(b'00 01 AB FF')
        with self.assertRaises(JournalError):
            self.journal.deliver(self.packet,self.expected,self.actual,self.wheel)
        with self.journal.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM executions').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT count(*) FROM device_owners').fetchone()[0],0)
