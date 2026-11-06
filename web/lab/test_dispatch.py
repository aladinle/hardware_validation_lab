"""Actual PostgreSQL allocation/permission checks; not physical scheduling proof."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from unittest.mock import Mock
from email.message import Message
from io import BytesIO, StringIO

from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, connections, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from agent.transport import AgentError, Transport
from django.utils import timezone
from agent.journal import initialize
from agent.poller import bind
from contracts.dispatch_v1 import poll_reply
from contracts.journal_v1 import parse_delivery
from contracts.v1 import ContractError
from .agent_services import create_agent, enroll, manage_agent
from .dispatch import claim, configure, guard, input_bytes, poll, receipt, schedule_once, token_for
from .models import (Agent, AgentCredential, Attempt, DeviceGrant, DispatchPolicy, Job, Lease, Resource,
                     ServicePrincipal, ServiceToken, TestApproval, TestGrant)
from .submissions import Actor, Rejected, approval, publish, submit, version_grant
from .test_m2a import Fixture
from .test_can_plugin import matching_fixture_wheel


class DispatchFixture(Fixture):
    @classmethod
    def prepare_dispatch(cls):
        cls.prepare()
        cls.wheel=Path(cls.storage.name)/'fixture.whl';matching_fixture_wheel(cls.wheel)
        cls.old_version=cls.version
        cls.version=publish(Actor(cls.admin.pk),cls.project.pk,cls.definition.pk,workload_wheel=cls.wheel)
        approval(Actor(cls.admin.pk),cls.project.pk,cls.version.pk,True)
        version_grant(Actor(cls.admin.pk),cls.project.pk,cls.member.pk,cls.version.pk,True)
        cls.payload['items'][0]['version_id']=str(cls.version.pk)
        cls.agent,ticket=create_agent(Actor(cls.admin.pk),cls.project.pk,'Synthetic receiver',[str(cls.device.pk)])
        cls.credential=enroll(cls.agent.pk,ticket['token'],{'schema_version':1,'agent_version':'0.2.0','platform':'Windows','device_ids':ticket['device_ids']})
        configure(Actor(cls.admin.pk),cls.project.pk,cls.agent.pk,cls.device.pk,cls.version.pk,cls.wheel,'shared-station')
        cls.poll_payload={'schema_version':1,'package_sha256':cls.version.manifest['plugin_package_sha256'],'device_ids':ticket['device_ids'],'platform':'Windows'}

    def api(self,action,payload,token=None):
        return self.client.post(f'/api/v1/agents/{self.agent.pk}/{action}',json.dumps(payload),content_type='application/json',
                                HTTP_AUTHORIZATION='Bearer '+(token or self.credential['token']))

    def queue_job(self,key='job-1'):
        batch,_=submit(Actor(self.operator.pk),key,self.payload)
        return batch.jobs.get()

    def ready(self):
        response=self.api('poll',self.poll_payload)
        self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def allocate(self):
        job=self.queue_job();self.ready()
        result=schedule_once();self.assertIsNotNone(result)
        attempt=Attempt.objects.get(pk=result)
        return job,attempt,{'schema_version':1,'execution_id':str(attempt.pk),'epoch':attempt.epoch,'claim_token':token_for(attempt)}


@skipUnless(connection.vendor=='postgresql','Allocation authority requires real PostgreSQL.')
@override_settings(SIMULATOR_DISPATCH=True)
class DispatchTests(DispatchFixture,TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage=tempfile.TemporaryDirectory(prefix='b5-inputs-')
        cls.config=override_settings(ARTIFACT_ROOT=Path(cls.storage.name)/'inputs');cls.config.enable()
        super().setUpClass();cls.prepare_dispatch()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.config.disable();cls.storage.cleanup()

    def test_configuration_command_accepts_test_version_without_builtin_flag_conflict(self):
        output = StringIO()
        call_command('configure_simulator_dispatch',
            '--project', str(self.project.pk), '--agent', str(self.agent.pk),
            '--device', str(self.device.pk), '--test-version', str(self.version.pk),
            '--administrator', self.admin.email, '--wheel', str(self.wheel),
            '--shared-resource', 'cli-station', '--confirm-simulated', stdout=output)
        self.assertIn('Simulator-only policy configured', output.getvalue())
        policy = DispatchPolicy.objects.get(device=self.device)
        self.assertEqual(policy.version_id, self.version.pk)
        self.assertEqual(policy.shared_resources.get().key, 'cli-station')
        self.assertFalse(Attempt.objects.exists())

    def test_durable_exclusive_assignment_replay_and_scoped_input(self):
        job,attempt,identity=self.allocate()
        self.assertEqual(Lease.objects.filter(attempt=attempt,released_at=None).count(),4)
        job.refresh_from_db();self.assertEqual(job.state,'reserved')
        first=self.ready();second=self.ready()
        self.assertEqual(first,second)
        self.assertNotIn(identity['claim_token'],json.dumps(attempt.assignment))
        packet,token=poll_reply(first,self.credential,self.poll_payload['package_sha256'])
        self.assertEqual(packet['execution_id'],str(attempt.pk));self.assertEqual(token,identity['claim_token'])
        self.assertEqual(self.api('claim',identity).status_code,200)
        self.assertEqual(self.api('claim',identity).status_code,200)
        data=self.api('input',{**identity,'role':'expected'})
        self.assertEqual(data.status_code,200);self.assertEqual(hashlib.sha256(data.content).hexdigest(),self.input.sha256)
        reply=self.api('receipt',{**identity,'completion_sha256':'a'*64})
        self.assertEqual(reply.status_code,200);self.assertFalse(reply.json()['leases_released'])
        self.assertFalse(reply.json()['evidence_acknowledged'])
        self.assertEqual(self.api('receipt',{**identity,'completion_sha256':'a'*64}).status_code,200)
        self.assertEqual(self.api('receipt',{**identity,'completion_sha256':'b'*64}).status_code,409)
        self.assertIsNone(schedule_once());self.assertEqual(Attempt.objects.count(),1)
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)

    def test_revoked_permissions_between_submission_and_dispatch_allocate_nothing(self):
        for kind in ('test','device','approval','user','membership'):
            with self.subTest(kind=kind),transaction.atomic():
                job=self.queue_job(kind);self.ready()
                if kind=='test':TestGrant.objects.filter(membership=self.member,version=self.version).delete()
                if kind=='device':DeviceGrant.objects.filter(membership=self.member,device=self.device).delete()
                if kind=='approval':TestApproval.objects.filter(version=self.version).update(revoked_at=timezone.now())
                if kind=='user':type(self.operator).objects.filter(pk=self.operator.pk).update(is_active=False)
                if kind=='membership':type(self.member).objects.filter(pk=self.member.pk).update(active=False)
                self.assertIsNone(schedule_once());self.assertFalse(Lease.objects.exists());self.assertFalse(Attempt.objects.exists())
                job.refresh_from_db();self.assertEqual(job.state,'blocked')
                transaction.set_rollback(True)

    def test_metadata_unmatched_package_stale_contact_and_queue_expiry(self):
        legacy=deepcopy(self.payload);legacy['items'][0]['version_id']=str(self.old_version.pk)
        submit(Actor(self.operator.pk),'legacy',legacy)
        self.assertIsNone(schedule_once());self.assertFalse(Attempt.objects.exists())
        job=self.queue_job();self.ready()
        Agent.objects.filter(pk=self.agent.pk).update(execution_package_sha256='0'*64)
        self.assertIsNone(schedule_once());job.refresh_from_db();self.assertEqual(job.dispatch_reason,'PACKAGE_MISMATCH')
        Agent.objects.filter(pk=self.agent.pk).update(execution_package_sha256=self.poll_payload['package_sha256'])
        job= self.queue_job('expired')
        Job.objects.filter(pk=job.pk).update(queue_deadline=timezone.now()-timedelta(seconds=1))
        self.assertIsNone(schedule_once());job.refresh_from_db();self.assertEqual(job.state,'expired')
        self.queue_job('stale')
        Agent.objects.filter(pk=self.agent.pk).update(execution_contact_at=timezone.now()-timedelta(seconds=31))
        self.assertIsNone(schedule_once());self.assertFalse(Attempt.objects.exists())

    def test_stale_epoch_scope_and_fence_cannot_claim_read_or_record_receipt(self):
        job,attempt,identity=self.allocate()
        for change in ({'epoch':attempt.epoch+1},{'claim_token':'wrong'},{'execution_id':str(__import__('uuid').uuid4())}):
            wrong={**identity,**change}
            self.assertEqual(self.api('claim',wrong).status_code,409)
            self.assertEqual(self.api('input',{**wrong,'role':'actual'}).status_code,409)
            self.assertEqual(self.api('receipt',{**wrong,'completion_sha256':'a'*64}).status_code,409)
        resource=attempt.leases.first().resource
        Resource.objects.filter(pk=resource.pk).update(fencing_epoch=attempt.epoch+1)
        self.assertEqual(self.api('claim',identity).status_code,409)
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)

    def test_timeout_quarantines_without_release_or_second_allocation(self):
        _,attempt,identity=self.allocate()
        self.queue_job('second')
        # Deadline is immutable in SQL, so time travel instead of rewriting it.
        with patch('lab.dispatch.timezone.now',return_value=attempt.deadline+timedelta(seconds=1)):
            self.assertIsNone(schedule_once())
            self.assertEqual(self.api('claim',identity).status_code,409)
        attempt.refresh_from_db();self.assertEqual(attempt.state,'quarantined')
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)
        self.assertEqual(Resource.objects.filter(quarantined=True).count(),4)

    def test_auth_principal_separation_and_revocation_after_assignment(self):
        _,attempt,identity=self.allocate()
        self.client.force_login(self.admin)
        route=f'/api/v1/agents/{self.agent.pk}/poll'
        self.assertEqual(self.client.post(route,json.dumps(self.poll_payload),content_type='application/json').status_code,401)
        self.assertEqual(self.api('poll',self.poll_payload,token='not-an-agent-token').status_code,401)
        wrong={**self.poll_payload,'package_sha256':'0'*64}
        self.assertEqual(self.api('poll',wrong).status_code,403)
        DeviceGrant.objects.filter(membership=self.member,device=self.device).delete()
        self.assertEqual(self.api('claim',identity).status_code,403)
        self.assertEqual(self.api('input',{**identity,'role':'expected'}).status_code,403)
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)

    def test_disable_flag_and_immutable_assignment(self):
        with override_settings(SIMULATOR_DISPATCH=False):
            self.assertEqual(self.api('poll',self.poll_payload).status_code,409)
            with self.assertRaises(Rejected):schedule_once()
        _,attempt,_=self.allocate()
        with self.assertRaises(DatabaseError),transaction.atomic():
            Attempt.objects.filter(pk=attempt.pk).update(assignment={'changed':True})

    def test_backend_packet_cannot_enter_local_demo_or_change_origin(self):
        _,attempt,_=self.allocate()
        with self.assertRaises(ContractError):parse_delivery(attempt.assignment)
        with tempfile.TemporaryDirectory() as temp:
            j=initialize(Path(temp)/'journal',str(self.agent.pk),str(self.project.pk))
            bind(j,'http://127.0.0.1:8768')
            with self.assertRaises(ValueError):bind(j,'http://127.0.0.1:9999')

    def test_revoked_service_submission_token_and_agent_key_block_dispatch(self):
        principal=ServicePrincipal.objects.create(project=self.project,owner=self.operator,name='Scoped CI')
        principal.versions.add(self.version);principal.devices.add(self.device)
        from .submissions import rotate_token, upload
        key,token=rotate_token(Actor(self.admin.pk),self.project.pk,principal.pk)
        actor=Actor(self.operator.pk,principal.pk,token.pk)
        data=b'00 01 AA FF\n'
        artifact,_=upload(actor,self.project.pk,'ci.hex',hashlib.sha256(data).hexdigest(),data)
        payload=deepcopy(self.payload)
        payload['items'][0].update(expected_artifact_id=str(artifact.pk),actual_artifact_id=str(artifact.pk))
        submit(actor,'ci-job',payload)
        self.ready();ServiceToken.objects.filter(pk=token.pk).update(revoked_at=timezone.now())
        self.assertIsNone(schedule_once());self.assertFalse(Attempt.objects.exists())
        self.assertEqual(self.api('poll',self.poll_payload,token=key).status_code,401)
        self.queue_job('human-job')
        AgentCredential.objects.filter(agent=self.agent).update(revoked_at=timezone.now())
        self.assertIsNone(schedule_once());self.assertFalse(Lease.objects.exists())

    def test_shared_station_busy_creates_no_partial_second_resource_allocation(self):
        _,attempt,_=self.allocate()
        # Test-only global-slot handoff isolates the shared-resource guard. The
        # actual public protocol never releases even this lease in M2B.5.
        Lease.objects.filter(attempt=attempt,resource__kind='global').update(released_at=timezone.now())
        from .models import Device
        device=Device.objects.create(project=self.project,name='Second simulated device',source='simulated',capabilities=['can_payload_files'])
        DeviceGrant.objects.create(membership=self.member,device=device)
        agent,ticket=create_agent(Actor(self.admin.pk),self.project.pk,'Second receiver',[str(device.pk)])
        cred=enroll(agent.pk,ticket['token'],{'schema_version':1,'agent_version':'0.2.0','platform':'Windows','device_ids':ticket['device_ids']})
        configure(Actor(self.admin.pk),self.project.pk,agent.pk,device.pk,self.version.pk,self.wheel,'shared-station')
        payload=deepcopy(self.payload);payload['items'][0]['device_id']=str(device.pk)
        submit(Actor(self.operator.pk),'second-station-user',payload)
        with transaction.atomic():poll(agent.pk,cred['token'],{**self.poll_payload,'device_ids':cred['device_ids']})
        self.assertIsNone(schedule_once())
        self.assertEqual(Attempt.objects.count(),1)
        self.assertEqual(Lease.objects.filter(attempt__agent=agent).count(),0)


@skipUnless(connection.vendor=='postgresql','Allocation concurrency requires PostgreSQL.')
@override_settings(SIMULATOR_DISPATCH=True)
class AllocationConcurrencyTests(DispatchFixture,TransactionTestCase):
    def setUp(self):
        self.storage=tempfile.TemporaryDirectory(prefix='b5-concurrency-')
        type(self).storage=self.storage
        self.config=override_settings(ARTIFACT_ROOT=Path(self.storage.name)/'inputs');self.config.enable()
        self.prepare_dispatch()

    def tearDown(self):
        self.config.disable();self.storage.cleanup()

    def test_two_allocator_connections_leave_one_durable_allocation(self):
        self.queue_job();self.queue_job('second');self.ready()
        barrier=Barrier(2)
        def allocate():
            close_old_connections();barrier.wait()
            try:return schedule_once()
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(lambda _:allocate(),range(2)))
        self.assertEqual(sum(item is not None for item in results),1)
        self.assertEqual(Attempt.objects.count(),1)
        self.assertEqual(Lease.objects.filter(released_at=None).count(),4)


class BinaryTransportTests(SimpleTestCase):
    def transport(self,data,content_type):
        transport=Transport.__new__(Transport)
        transport.base_url='http://127.0.0.1:8768';transport.timeout=5
        response=Mock()
        response.headers=Message();response.headers['Content-Type']=content_type
        response.read=BytesIO(data).read
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        transport.opener=Mock();transport.opener.open.return_value=response
        return transport

    def test_binary_input_limit_and_content_type(self):
        route='/api/v1/agents/test/input'
        self.assertEqual(self.transport(b'AA','application/octet-stream').post_bytes(route,{},'dummy',maximum=2),b'AA')
        for data,mime,maximum in ((b'AAA','application/octet-stream',2),(b'{}','application/json',2)):
            with self.assertRaises(AgentError):self.transport(data,mime).post_bytes(route,{},'dummy',maximum=maximum)

    def test_unsupported_route_is_rejected_before_credentials_are_sent(self):
        transport=self.transport(b'AA','application/octet-stream')
        with self.assertRaises(AgentError):transport.post_bytes('/api/v1/agents/test/input?redirect=bad',{},'dummy')
        transport.opener.open.assert_not_called()
