"""Opt-in PostgreSQL synthetic allocation. No results or automatic lease release."""
import base64
from dataclasses import asdict
from datetime import timedelta
import hashlib
import hmac
import re
from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from contracts.agents_v1 import ids, schema
from contracts.journal_v1 import parse_delivery, sha
from contracts.plugins import validate_manifest, validate_parameters
from contracts.runner_v1 import Limits
from contracts.v1 import ContractError, identifier
from .agent_services import authenticate_agent, device_scope
from .models import (Agent, AgentCredential, AgentDevice, Attempt, Device, DeviceGrant, DispatchPolicy, Job, Lease,
                     Membership, Project, Resource, Role, TestApproval, TestGrant, TestVersion, User)
from .services import audit, digest
from .submissions import Actor, Rejected, artifact_visible, checksum, current_member, locked_scope, read_input


def enabled():
    if connection.vendor != 'postgresql' or not settings.SIMULATOR_DISPATCH:
        raise Rejected('DISPATCH_DISABLED','Explicit PostgreSQL simulator dispatch opt-in required.',409)


def token_for(attempt):
    body=f'm2b5:{attempt.pk}:{attempt.agent_id}:{attempt.epoch}'.encode()
    return 'hvc_'+base64.urlsafe_b64encode(hmac.new(settings.SECRET_KEY.encode(),body,hashlib.sha256).digest()).decode().rstrip('=')


def resource(kind,key,project=None):
    return Resource.objects.get_or_create(kind=kind,key=key,project=project)[0]


@transaction.atomic
def configure(actor,project_id,agent_id,device_id,version_id,wheel,shared_key):
    user,project,*_=locked_scope(actor,project_id,manager=True)
    agent=Agent.objects.select_for_update().filter(pk=agent_id,project=project,enabled=True,enrolled_at__isnull=False).first()
    device=Device.objects.filter(pk=device_id,project=project,enabled=True,source='simulated').first()
    version=TestVersion.objects.filter(pk=version_id,definition__project=project).first()
    if agent is None or device is None or version is None or not AgentDevice.objects.filter(agent=agent,device=device,active=True).exists():
        raise Rejected('SCOPE_UNAVAILABLE','Use an enrolled agent and its enabled simulated inventory.',403)
    if Attempt.objects.filter(agent=agent).exists() or Lease.objects.filter(resource__project=project,released_at=None,resource__kind='device',resource__key=str(device.pk)).exists():
        raise Rejected('ALLOCATION_HELD','Existing allocation requires reconciliation, not reconfiguration.',409)
    spec,_=validate_manifest(version.manifest,executable=True)
    from workloads.registry import verify_wheel
    package=verify_wheel(wheel)
    if version.manifest['plugin_package_sha256'] != package or not set(spec.capabilities)<=set(device.capabilities):
        raise Rejected('PACKAGE_UNAVAILABLE','Approved installed package/capability mismatch.',409)
    if not TestApproval.objects.filter(version=version,revoked_at=None).exists():
        raise Rejected('UNAPPROVED_VERSION','Separate current version approval required.',403)
    if not isinstance(shared_key,str) or not re.fullmatch('[A-Za-z0-9._:-]{1,80}',shared_key):
        raise ContractError('Use an explicit simple shared station key.')
    shared=resource('shared',shared_key,project)
    if shared.quarantined:
        raise Rejected('RESOURCE_QUARANTINED','Shared resource is unavailable.',409)
    policy,_=DispatchPolicy.objects.update_or_create(device=device,defaults={'agent':agent,'version':version,'enabled':True})
    policy.shared_resources.set([shared])
    agent.execution_enabled=True
    agent.execution_package_sha256=package
    agent.execution_contact_at=None
    agent.save(update_fields=['execution_enabled','execution_package_sha256','execution_contact_at'])
    audit(user,project,'dispatch.simulator_configured',device.pk)
    return policy


def authority(job):
    principal=job.batch.principal
    token_id=job.snapshot.get('submission_token_id')
    if principal and not token_id:
        raise Rejected('LEGACY_CONTEXT','Resubmit with immutable credential identity.',409)
    actor=Actor(job.batch.requester_id,principal.pk if principal else None,token_id)
    user,project,role,_,current_principal=locked_scope(actor,job.batch.project_id)
    member=current_member(user,project)
    if member is None or member.role not in {Role.ADMIN,Role.ENGINEER,Role.OPERATOR} or job.snapshot.get('session_epoch') != user.session_epoch:
        raise Rejected('REQUESTER_REVOKED','Requester authority is unavailable.',403)
    version,device=job.version,job.device
    if not device.enabled or device.source!='simulated' or version.definition.project_id != project.pk or device.project_id != project.pk:
        raise Rejected('FORBIDDEN_DEVICE','Only enabled same-project synthetic inventory can dispatch.',403)
    if not TestGrant.objects.filter(membership=member,version=version,test=version.definition).exists() or not DeviceGrant.objects.filter(membership=member,device=device).exists():
        raise Rejected('GRANT_REVOKED','Current explicit version/device grants required.',403)
    if not TestApproval.objects.filter(version=version,revoked_at=None).exists():
        raise Rejected('APPROVAL_REVOKED','Current approval is unavailable.',403)
    if principal and (not current_principal.versions.filter(pk=version.pk).exists() or not current_principal.devices.filter(pk=device.pk).exists()):
        raise Rejected('SERVICE_SCOPE_REVOKED','Service scope is unavailable.',403)
    spec,header=validate_manifest(version.manifest,executable=True)
    if version.manifest!=job.snapshot['manifest'] or checksum(version.manifest)!=job.snapshot['manifest_sha256'] or not set(spec.capabilities)<=set(device.capabilities):
        raise Rejected('IMMUTABLE_CONTEXT_CONFLICT','Version snapshot/capability mismatch.',409)
    validate_parameters(spec.name,job.parameters,declared_header=header)
    for role,artifact in (('expected',job.expected),('actual',job.actual)):
        if artifact.project_id!=project.pk or not artifact_visible(actor,artifact,user,role=Role.ADMIN if user.is_superuser else member.role) or artifact.sha256!=job.snapshot['inputs'][role]:
            raise Rejected('INPUT_REVOKED','Input authority or accepted checksum is unavailable.',403)
        read_input(artifact)
    return project


def agent_ready(agent,*,fresh=True):
    if not agent.enabled or agent.enrolled_at is None or not agent.execution_enabled or not AgentCredential.objects.filter(agent=agent,revoked_at=None,expires_at__gt=timezone.now()).exists():
        raise Rejected('AGENT_UNAVAILABLE','Agent execution identity is unavailable.',409)
    device_scope(agent)
    if fresh and (agent.execution_contact_at is None or agent.execution_contact_at<timezone.now()-timedelta(seconds=30)):
        raise Rejected('AGENT_CONTACT_STALE','No recent authenticated execution poll.',409)


def receiver(agent_id,raw):
    # Existing assignments follow requester-user -> project -> agent -> attempt,
    # matching submission/security/scheduler locks. Invalid keys lock no user.
    if AgentCredential.objects.filter(agent_id=agent_id,digest=digest(raw),revoked_at=None,expires_at__gt=timezone.now()).exists():
        requester=Attempt.objects.filter(agent_id=agent_id).values_list('job__batch__requester_id',flat=True).first()
        if requester is not None:User.objects.select_for_update().get(pk=requester)
    return authenticate_agent(agent_id,raw)


@transaction.atomic
def schedule_once():
    enabled()
    global_resource=resource('global','single_worker')
    global_resource=Resource.objects.select_for_update().get(pk=global_resource.pk)
    # Expiration quarantines in place. No process/hardware stop is inferred.
    for attempt in Attempt.objects.filter(Q(deadline__lte=timezone.now())|Q(leases__expires_at__lte=timezone.now(),leases__released_at__isnull=True)).exclude(state='quarantined').distinct():
        User.objects.select_for_update().get(pk=attempt.job.batch.requester_id)
        Project.objects.select_for_update().get(pk=attempt.job.batch.project_id)
        Agent.objects.select_for_update().get(pk=attempt.agent_id)
        attempt=Attempt.objects.select_for_update().get(pk=attempt.pk)
        Job.objects.filter(pk=attempt.job_id).update(state='quarantined',dispatch_reason='LEASE_EXPIRED')
        Attempt.objects.filter(pk=attempt.pk).update(state='quarantined')
        Resource.objects.filter(lease__attempt=attempt,lease__released_at=None).update(quarantined=True)
        audit(None,attempt.job.batch.project,'allocation.quarantined',attempt.pk)
    if global_resource.quarantined or Lease.objects.filter(resource=global_resource,released_at=None).exists():
        return None
    candidates=Job.objects.filter(state='queued',device__dispatch_policy__enabled=True,
                                 version_id=F('device__dispatch_policy__version_id')).order_by('created_at','pk')[:20]
    for candidate in candidates:
        if candidate.queue_deadline<=timezone.now():
            Job.objects.filter(pk=candidate.pk,state='queued').update(state='expired',dispatch_reason='QUEUE_EXPIRED')
            audit(None,candidate.batch.project,'queue.expired',candidate.pk)
            continue
        try:
            project=authority(candidate)
            job=Job.objects.select_for_update().get(pk=candidate.pk)
            policy=DispatchPolicy.objects.get(device=job.device,version=job.version,enabled=True)
            agent=Agent.objects.select_for_update().get(pk=policy.agent_id)
            agent_ready(agent)
            if agent.project_id!=project.pk or not AgentDevice.objects.filter(agent=agent,device=job.device,active=True).exists():
                raise Rejected('AGENT_SCOPE_REVOKED','Current agent/device binding required.',403)
            if agent.execution_package_sha256!=job.version.manifest['plugin_package_sha256']:
                raise Rejected('PACKAGE_MISMATCH','Installed package differs from approved version.',409)
            shared=list(policy.shared_resources.all())
            if not shared or any(r.project_id!=project.pk or r.kind!='shared' for r in shared):
                raise Rejected('SHARED_SCOPE_INVALID','Explicit same-project shared resources required.',409)
            resources=[global_resource,resource('device',str(job.device_id),project),resource('agent',str(agent.pk),project),*shared]
            locked=list(Resource.objects.select_for_update().filter(pk__in=[r.pk for r in resources]).order_by('pk'))
            if any(r.quarantined for r in locked) or Lease.objects.filter(resource__in=locked,released_at=None).exists():
                continue
            epoch=global_resource.fencing_epoch+1
            deadline=timezone.now()+timedelta(seconds=90)
            assignment=parse_delivery({'schema_version':1,'source':'server_simulated_assignment','agent_id':str(agent.pk),
                'project_id':str(project.pk),'execution_id':str(__import__('uuid').uuid4()),'job_id':str(job.pk),
                'device_ids':[str(job.device_id)],'epoch':epoch,'deadline':deadline.isoformat(),'manifest':job.version.manifest,
                'parameters':job.parameters,'limits':asdict(Limits(cpu_percent=100 if agent.execution_platform=='Linux' else 50)),
                'inputs':[{'role':role,'artifact_id':str(artifact.pk),'size':artifact.size,'sha256':artifact.sha256}
                          for role,artifact in (('expected',job.expected),('actual',job.actual))]},source='server_simulated_assignment')
            attempt=Attempt(id=assignment['execution_id'],job=job,agent=agent,epoch=epoch,state='reserved',assignment=assignment,deadline=deadline)
            attempt.claim_digest=digest(token_for(attempt))
            attempt.save(force_insert=True)
            for r in locked:
                r.fencing_epoch=epoch;r.save(update_fields=['fencing_epoch'])
                Lease.objects.create(resource=r,attempt=attempt,epoch=epoch,expires_at=deadline)
            job.state='reserved';job.dispatch_reason='';job.save(update_fields=['state','dispatch_reason'])
            audit(None,project,'attempt.assigned',attempt.pk)
            return str(attempt.pk)
        except (Rejected,ContractError,Http404) as exc:
            Job.objects.filter(pk=candidate.pk,state='queued').update(state='blocked',dispatch_reason=getattr(exc,'code','INVALID_VERSION'))
            audit(None,candidate.batch.project,'dispatch.blocked',candidate.pk)
    return None


def guard(agent,execution_id,epoch,claim):
    attempt=Attempt.objects.select_for_update().filter(pk=identifier(execution_id),agent=agent).first()
    if attempt is None or type(epoch) is not int or epoch!=attempt.epoch or not isinstance(claim,str) or not hmac.compare_digest(digest(claim),attempt.claim_digest):
        raise Rejected('STALE_CLAIM','Assignment identity/epoch/token mismatch.',409)
    if attempt.state=='quarantined' or attempt.deadline<=timezone.now():
        raise Rejected('ALLOCATION_UNAVAILABLE','Allocation expired or quarantined; ownership remains held.',409)
    authority(attempt.job)
    agent_ready(agent,fresh=False)
    if agent.execution_package_sha256!=attempt.assignment['manifest']['plugin_package_sha256']:
        raise Rejected('PACKAGE_MISMATCH','Package changed; allocation remains held.',409)
    leases=list(attempt.leases.filter(released_at=None).select_related('resource'))
    if len(leases)<4 or any(l.epoch!=epoch or l.resource.fencing_epoch!=epoch or l.resource.quarantined or l.expires_at<=timezone.now() for l in leases):
        raise Rejected('STALE_FENCE','Resource fencing mismatch; ownership remains held.',409)
    if not AgentDevice.objects.filter(agent=agent,device=attempt.job.device,active=True).exists():
        raise Rejected('AGENT_SCOPE_REVOKED','Agent device binding changed.',403)
    return attempt


def poll(agent_id,raw,payload):
    enabled();schema(payload,{'package_sha256','device_ids','platform'})
    package=sha(payload['package_sha256'])
    agent,_=receiver(agent_id,raw)
    agent_ready(agent,fresh=False)
    if ids(payload['device_ids'])!=device_scope(agent) or payload['platform'] not in ('Windows','Linux') or package!=agent.execution_package_sha256:
        raise Rejected('PACKAGE_OR_SCOPE_MISMATCH','Execution package/scope is not approved.',403)
    agent.execution_contact_at=timezone.now();agent.execution_platform=payload['platform']
    agent.last_contact_at=agent.execution_contact_at
    agent.save(update_fields=['execution_contact_at','execution_platform','last_contact_at'])
    attempt=Attempt.objects.filter(agent=agent).first()
    if attempt is None:
        return {'schema_version':1,'assignment':None,'claim_token':None,'hardware_ready':False}
    claim=token_for(attempt)
    guard(agent,str(attempt.pk),attempt.epoch,claim)
    return {'schema_version':1,'assignment':attempt.assignment,'claim_token':claim,'hardware_ready':False}


def claim(agent_id,raw,payload):
    enabled();schema(payload,{'execution_id','epoch','claim_token'})
    agent,_=receiver(agent_id,raw)
    attempt=guard(agent,payload['execution_id'],payload['epoch'],payload['claim_token'])
    if attempt.state=='reserved':
        attempt.state='running';attempt.save(update_fields=['state'])
        Job.objects.filter(pk=attempt.job_id).update(state='running')
        audit(None,agent.project,'attempt.claimed',attempt.pk)
    return {'schema_version':1,'execution_id':str(attempt.pk),'epoch':attempt.epoch,'state':attempt.state}


def input_bytes(agent_id,raw,payload):
    enabled();schema(payload,{'execution_id','epoch','claim_token','role'})
    agent,_=receiver(agent_id,raw)
    attempt=guard(agent,payload['execution_id'],payload['epoch'],payload['claim_token'])
    if payload['role'] not in ('expected','actual'):
        raise ContractError('Unknown input role.')
    artifact=attempt.job.expected if payload['role']=='expected' else attempt.job.actual
    response=HttpResponse(read_input(artifact),content_type='application/octet-stream')
    response['X-Content-SHA256']=artifact.sha256
    return response


def receipt(agent_id,raw,payload):
    enabled();schema(payload,{'execution_id','epoch','claim_token','completion_sha256'})
    agent,_=receiver(agent_id,raw)
    attempt=guard(agent,payload['execution_id'],payload['epoch'],payload['claim_token'])
    value=sha(payload['completion_sha256'])
    if attempt.state not in ('running','awaiting_evidence') or (attempt.receipt_sha256 and attempt.receipt_sha256!=value):
        raise Rejected('RECEIPT_CONFLICT','Receipt conflicts with current claim.',409)
    if not attempt.receipt_sha256:
        attempt.receipt_sha256=value;attempt.state='awaiting_evidence';attempt.save(update_fields=['receipt_sha256','state'])
        audit(None,agent.project,'attempt.local_receipt_recorded',attempt.pk)
    return {'schema_version':1,'execution_id':str(attempt.pk),'epoch':attempt.epoch,'state':attempt.state,'evidence_acknowledged':False,'leases_released':False}
