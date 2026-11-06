"""Real PostgreSQL upload/finalization authorization and native evidence fixtures."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import connection, DatabaseError, transaction, close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from agent.runner import run_can
from contracts.evidence_v1 import OUTPUT_LIMITS
from contracts.journal_v1 import canonical, checksum
from contracts.runner_v1 import Limits
from .agent_services import create_agent, enroll
from .dispatch import receipt, schedule_once
from .models import (Attempt, DeviceGrant, ExecutionEvent, ExecutionResult, Job, Lease, OutputArtifact,
                     Resource, ServicePrincipal, ServiceToken, TestGrant)
from .services import digest
from .submissions import Actor, rotate_token, submit, upload
from .test_dispatch import DispatchFixture


@skipUnless(connection.vendor=='postgresql','Evidence transaction authority requires PostgreSQL.')
@override_settings(SIMULATOR_DISPATCH=True)
class EvidenceTests(DispatchFixture,TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage=tempfile.TemporaryDirectory(prefix='b6-inputs-')
        cls.config=override_settings(ARTIFACT_ROOT=Path(cls.storage.name)/'inputs');cls.config.enable()
        super().setUpClass();cls.prepare_dispatch()
        root=Path(cls.storage.name)
        (root/'expected.hex').write_bytes(b'00 01 AA FF\n');(root/'actual.hex').write_bytes(b'00 01 AA FF\n')
        cls.native=run_can(cls.version.manifest,root/'expected.hex',root/'actual.hex',cls.wheel,root/'run',parameters={'header_bytes':0},limits=Limits())
        if cls.native['outcome']!='PASS':raise AssertionError(cls.native)
        cls.output_bytes={'run/'+p.name:p.read_bytes() for p in (root/'run').iterdir() if p.is_file()}

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.config.disable();cls.storage.cleanup()

    def setup_result(self):
        self.job,self.attempt,self.identity=self.allocate()
        self.assertEqual(self.api('claim',self.identity).status_code,200)
        packet=self.attempt.assignment
        files={name:{'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in self.output_bytes.items()}
        files['delivery.json']={'size':len(canonical(packet).encode()),'sha256':checksum(packet)}
        files['inputs/plugin.whl']={'size':self.wheel.stat().st_size,'sha256':packet['manifest']['plugin_package_sha256']}
        for ref in packet['inputs']:files['inputs/'+ref['role']+'.hex']={'size':ref['size'],'sha256':ref['sha256']}
        self.seal={'schema_version':1,'execution_id':str(self.attempt.pk),'epoch':self.attempt.epoch,
                   'request_hash':checksum(packet),'result':deepcopy(self.native),'files':files}
        self.value=checksum(self.seal)
        return self.attempt

    def event(self,sequence):
        return self.api('events',{**self.identity,'sequence':sequence,'kind':{1:'execution_accepted',2:'local_completion_sealed'}[sequence]})

    def upload_output(self,name,raw=None,identity=None,token=None,**headers):
        raw=self.output_bytes[name] if raw is None else raw
        identity=identity or self.identity
        return self.client.post(f'/api/v1/agents/{self.agent.pk}/output',raw,content_type='application/octet-stream',CONTENT_TYPE='application/octet-stream',
            HTTP_AUTHORIZATION='Bearer '+(token or self.credential['token']),HTTP_X_EXECUTION_ID=identity['execution_id'],
            HTTP_X_CLAIM_EPOCH=str(identity['epoch']),HTTP_X_CLAIM_TOKEN=identity['claim_token'],HTTP_X_EVIDENCE_NAME=name,
            HTTP_X_CONTENT_SHA256=headers.pop('HTTP_X_CONTENT_SHA256',hashlib.sha256(raw).hexdigest()),**headers)

    def stage(self):
        for seq in (1,2):self.assertEqual(self.event(seq).status_code,200)
        for name in self.output_bytes:
            response=self.upload_output(name)
            self.assertEqual(response.status_code,200,(name,response.content))
        reply=self.api('receipt',{**self.identity,'completion_sha256':self.value})
        self.assertEqual(reply.status_code,200)

    def finalize(self,**updates):
        return self.api('result',{**self.identity,'completion':self.seal,'completion_sha256':self.value,**updates})

    def test_complete_replay_download_and_immutable_original(self):
        self.setup_result();self.stage()
        first=self.finalize();self.assertEqual(first.status_code,200,first.content)
        self.assertTrue(first.json()['evidence_acknowledged']);self.assertFalse(first.json()['leases_released'])
        self.assertEqual(self.finalize().json(),first.json())
        self.assertEqual(ExecutionResult.objects.count(),1)
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)
        self.job.refresh_from_db();self.assertEqual(self.job.state,'completed')
        self.client.force_login(self.operator)
        report=self.client.get(f'/api/v1/jobs/{self.job.pk}/result')
        self.assertEqual(report.status_code,200);self.assertEqual(report.json()['runner']['outcome'],'PASS')
        self.assertNotIn(self.identity['claim_token'],report.content.decode())
        for output in OutputArtifact.objects.all():
            reply=self.client.get(f'/api/v1/outputs/{output.pk}')
            self.assertEqual(reply.status_code,200);self.assertEqual(reply.content,self.output_bytes[output.name])
            self.assertIn('attachment',reply['Content-Disposition'])
        page=self.client.get(reverse('job_page',args=[self.project.pk,self.job.pk]))
        self.assertContains(page,'Stored execution result');self.assertContains(page,'PASS')
        self.assertEqual(self.client.get(f'/api/v1/jobs/{self.job.pk}').json()['outcome'],'PASS')
        for model in (ExecutionEvent,OutputArtifact,ExecutionResult):
            with self.assertRaises(DatabaseError), transaction.atomic():model.objects.filter(pk=model.objects.first().pk).delete()

    def test_incomplete_evidence_never_finalizes_and_retry_can_finish(self):
        self.setup_result()
        self.api('receipt',{**self.identity,'completion_sha256':self.value})
        self.assertEqual(self.finalize().status_code,409)
        self.assertFalse(ExecutionResult.objects.exists());self.assertEqual(Lease.objects.filter(released_at=None).count(),4)
        self.stage();self.assertEqual(self.finalize().status_code,200)

    def test_upload_replay_conflict_checksum_type_and_path_bounds(self):
        self.setup_result()
        first=self.upload_output('run/report.txt');self.assertEqual(first.status_code,200)
        self.assertEqual(self.upload_output('run/report.txt').json(),first.json())
        self.assertEqual(self.upload_output('run/report.txt',b'different').status_code,409)
        self.assertEqual(self.upload_output('run/report.txt',HTTP_X_CONTENT_SHA256='0'*64).status_code,400)
        for name,raw,status in (('../secret',b'a',400),('run/report.json',b'not JSON',400),('run/report.txt',b'\xff',400),('run/stderr.bin',b'a'*(65536+1),413)):
            self.assertEqual(self.upload_output(name,raw).status_code,status,name)
        self.assertEqual(OutputArtifact.objects.count(),1)

    def test_event_sequence_replay_is_bounded(self):
        self.setup_result()
        self.assertEqual(self.event(2).status_code,409)
        self.assertEqual(self.event(1).status_code,200);self.assertEqual(self.event(1).status_code,200)
        self.assertEqual(self.event(2).status_code,200)
        self.assertEqual(ExecutionEvent.objects.count(),2)
        self.assertEqual(self.api('events',{**self.identity,'sequence':True,'kind':'execution_accepted'}).status_code,400)

    def test_stale_claim_epoch_and_expiry_cannot_store_or_finalize(self):
        self.setup_result()
        for key,val in (('claim_token','wrong'),('epoch',self.attempt.epoch+1)):
            identity={**self.identity,key:val}
            self.assertEqual(self.upload_output('run/run.json',identity=identity).status_code,409)
            self.assertEqual(self.finalize(**{key:val}).status_code,409)
        with transaction.atomic():
            Lease.objects.filter(attempt=self.attempt).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.upload_output('run/run.json').status_code,409)
        self.assertEqual(self.finalize().status_code,409)
        self.assertFalse(ExecutionResult.objects.exists());self.assertFalse(OutputArtifact.objects.exists())

    def test_lost_final_reply_replays_after_deadline_without_release(self):
        self.setup_result();self.stage();first=self.finalize();self.assertEqual(first.status_code,200)
        Lease.objects.filter(attempt=self.attempt).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.event(1).status_code,200)
        self.assertEqual(self.upload_output('run/run.json').status_code,200)
        self.assertEqual(self.finalize().json(),first.json())
        self.assertIsNone(schedule_once())
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)

    def test_cross_agent_user_project_service_and_revoked_read_denial(self):
        self.setup_result();self.stage();self.assertEqual(self.finalize().status_code,200)
        artifact=OutputArtifact.objects.first();url=f'/api/v1/outputs/{artifact.pk}'
        self.client.force_login(self.viewer);self.assertEqual(self.client.get(url).status_code,404)
        from .models import Membership, Role, User
        foreign=User.objects.create_user(username='foreign@b6.test',email='foreign@b6.test')
        Membership.objects.create(user=foreign,project=self.other,role=Role.ADMIN)
        self.client.force_login(foreign);self.assertEqual(self.client.get(url).status_code,404)
        principal=ServicePrincipal.objects.create(project=self.project,owner=self.operator,name='other service')
        secret,token=rotate_token(Actor(self.admin.pk),self.project.pk,principal.pk)
        self.assertEqual(self.client.get(url,HTTP_AUTHORIZATION='Bearer '+secret).status_code,404)
        self.client.force_login(self.operator)
        DeviceGrant.objects.filter(membership=self.member,device=self.device).delete()
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.finalize().status_code,403)

    def test_wrong_agent_and_cookie_cannot_upload(self):
        self.setup_result()
        # Another valid same-project agent credential must not inherit this assignment.
        from .models import Device
        device=Device.objects.create(project=self.project,name='Other',source='simulated',capabilities=['can_payload_files'])
        agent,ticket=create_agent(Actor(self.admin.pk),self.project.pk,'Other',[str(device.pk)])
        credential=enroll(agent.pk,ticket['token'],{'schema_version':1,'agent_version':'0.2.0','platform':'Windows','device_ids':ticket['device_ids']})
        self.assertEqual(self.upload_output('run/run.json',token=credential['token']).status_code,401)
        response=self.client.post(f'/api/v1/agents/{agent.pk}/events',json.dumps({**self.identity,'sequence':1,'kind':'execution_accepted'}),
            content_type='application/json',HTTP_AUTHORIZATION='Bearer '+credential['token'])
        self.assertEqual(response.status_code,409)
        self.client.force_login(self.admin)
        response=self.client.post(f'/api/v1/agents/{self.agent.pk}/events',json.dumps(self.identity),content_type='application/json')
        self.assertEqual(response.status_code,401)

    def test_cleanup_failure_preserves_pass_and_quarantines(self):
        self.setup_result()
        self.seal['result'].update(cleanup_status='ERROR',quarantine_required=True)
        raw=(canonical(self.seal['result'])+'\n').encode()
        self.output_bytes={**self.output_bytes,'run/run.json':raw}
        self.seal['files']['run/run.json']={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        self.value=checksum(self.seal);self.stage()
        first=self.finalize();self.assertEqual(first.status_code,200,first.content)
        result=ExecutionResult.objects.get();self.assertEqual(result.outcome,'PASS');self.assertEqual(result.cleanup_status,'ERROR')
        self.job.refresh_from_db();self.assertEqual(self.job.state,'quarantined')
        self.assertEqual(Resource.objects.filter(quarantined=True).count(),4)
        self.assertEqual(self.finalize().json(),first.json())

    def test_context_conflict_does_not_hide_original_or_release(self):
        self.setup_result();self.stage();self.assertEqual(self.finalize().status_code,200)
        changed=deepcopy(self.seal);changed['result']['outcome']='FAIL'
        self.assertEqual(self.finalize(completion=changed,completion_sha256=checksum(changed)).status_code,409)
        self.assertEqual(ExecutionResult.objects.get().outcome,'PASS')
        self.assertFalse(Lease.objects.filter(released_at__isnull=False).exists())

    def test_correct_service_can_read_but_another_or_revoked_token_cannot(self):
        principal=ServicePrincipal.objects.create(project=self.project,owner=self.operator,name='Scoped submitting service')
        principal.versions.add(self.version);principal.devices.add(self.device)
        secret,token=rotate_token(Actor(self.admin.pk),self.project.pk,principal.pk)
        service_input,_=upload(Actor(self.operator.pk,principal.pk,token.pk),self.project.pk,'service.hex',
            hashlib.sha256(b'00 01 AA FF\n').hexdigest(),b'00 01 AA FF\n')
        self.payload=deepcopy(self.payload)
        self.payload['items'][0].update(expected_artifact_id=str(service_input.pk),actual_artifact_id=str(service_input.pk))
        def service_job():return submit(Actor(self.operator.pk,principal.pk,token.pk),'service-job',self.payload)[0].jobs.get()
        with patch.object(self,'queue_job',side_effect=service_job):self.setup_result()
        self.stage();self.assertEqual(self.finalize().status_code,200)
        url=f'/api/v1/outputs/{OutputArtifact.objects.first().pk}'
        self.assertEqual(self.client.get(url,HTTP_AUTHORIZATION='Bearer '+secret).status_code,200)
        ServiceToken.objects.filter(pk=token.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.client.get(url,HTTP_AUTHORIZATION='Bearer '+secret).status_code,401)
        self.assertEqual(self.finalize().status_code,401)


@skipUnless(connection.vendor=='postgresql','Upload concurrency requires PostgreSQL.')
@override_settings(SIMULATOR_DISPATCH=True)
class EvidenceConcurrencyTests(DispatchFixture,TransactionTestCase):
    def setUp(self):
        self.storage=tempfile.TemporaryDirectory(prefix='b6-concurrent-');type(self).storage=self.storage
        self.config=override_settings(ARTIFACT_ROOT=Path(self.storage.name)/'inputs');self.config.enable()
        self.prepare_dispatch()

    def tearDown(self):
        self.config.disable();self.storage.cleanup()

    def test_two_connections_commit_one_immutable_output(self):
        _,attempt,identity=self.allocate()
        self.assertEqual(self.api('claim',identity).status_code,200)
        barrier=Barrier(2);raw=b'bounded evidence'
        def upload(_):
            close_old_connections();barrier.wait()
            try:
                reply=Client().post(f'/api/v1/agents/{self.agent.pk}/output',raw,content_type='application/octet-stream',
                    HTTP_AUTHORIZATION='Bearer '+self.credential['token'],HTTP_X_EXECUTION_ID=str(attempt.pk),
                    HTTP_X_CLAIM_EPOCH=str(attempt.epoch),HTTP_X_CLAIM_TOKEN=identity['claim_token'],
                    HTTP_X_EVIDENCE_NAME='run/report.txt',HTTP_X_CONTENT_SHA256=hashlib.sha256(raw).hexdigest())
                return reply.status_code,reply.json()
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:replies=list(pool.map(upload,range(2)))
        self.assertEqual(replies[0],replies[1]);self.assertEqual(replies[0][0],200)
        self.assertEqual(OutputArtifact.objects.count(),1)
