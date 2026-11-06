"""Isolated PostgreSQL/HTTP/native-agent review fixture. No user lab data."""
import hashlib
import json
import os
from pathlib import Path
import sys
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'web'))
if os.environ.get('LAB_DB')!='postgres' or os.environ.get('PGDATABASE') not in {'hardware_lab_b5_review','hardware_lab_b5_final_review'}:
    raise SystemExit('Use only named isolated M2B.5 review PostgreSQL databases.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from lab.agent_services import create_agent, manage_agent
from lab.dispatch import configure
from lab.models import (Agent, AgentCredential, AgentEnrollment, Attempt, Device, DeviceGrant, Job, Lease, Membership,
                        Project, Resource, Role, User)
from lab.services import audit
from lab.submissions import Actor, approval, edit_draft, publish, submit, upload, version_grant

prefix='b5-final' if os.environ['PGDATABASE']=='hardware_lab_b5_final_review' else 'b5'
private=root/f'.local/{prefix}-review-meta.json'
mode=sys.argv[1]
if mode=='prepare':
    call_command('migrate',verbosity=0)
    if User.objects.exists():raise SystemExit('Existing review data preserved; use check/configure/retire.')
    admin=User.objects.create_user(username='b5-review@localhost.test',email='b5-review@localhost.test')
    admin.set_unusable_password();admin.save(update_fields=['password'])
    project=Project.objects.create(name='M2B.5 isolated assignment review')
    member=Membership.objects.create(project=project,user=admin,role=Role.ADMIN)
    device=Device.objects.create(project=project,name='Isolated synthetic CAN files (no discovery)',source='simulated',capabilities=['can_payload_files'])
    DeviceGrant.objects.create(membership=member,device=device)
    definition=edit_draft(Actor(admin.pk),project.pk,{'name':'Synthetic CAN dispatch review','header_bytes':2})
    old=publish(Actor(admin.pk),project.pk,definition.pk)
    new=publish(Actor(admin.pk),project.pk,definition.pk,workload_wheel=sys.argv[2])
    for version in (old,new):
        approval(Actor(admin.pk),project.pk,version.pk,True)
        version_grant(Actor(admin.pk),project.pk,member.pk,version.pk,True)
    artifacts={}
    for role,name in (('expected','expected-header.hex'),('actual','actual-pass.hex')):
        raw=(root/'examples/can'/name).read_bytes()
        artifacts[role]=upload(Actor(admin.pk),project.pk,name,hashlib.sha256(raw).hexdigest(),raw)[0]
    jobs=[]
    for key,version in (('metadata-only',old),('synthetic-executable',new)):
        payload={'project_id':str(project.pk),'items':[{'version_id':str(version.pk),'device_id':str(device.pk),
            'expected_artifact_id':str(artifacts['expected'].pk),'actual_artifact_id':str(artifacts['actual'].pk),'parameters':{'header_bytes':2}}]}
        batch,_=submit(Actor(admin.pk),key,payload);jobs.append(str(batch.jobs.get().pk))
    agent,ticket=create_agent(Actor(admin.pk),project.pk,'Isolated native receiver',[str(device.pk)])
    from agent.journal import durable_write
    durable_write(root/f'.local/{prefix}-enrollment.json',json.dumps(ticket).encode())
    durable_write(private,json.dumps({'admin':admin.pk,'project':str(project.pk),'device':str(device.pk),'version':str(new.pk),
        'agent':str(agent.pk),'old_job':jobs[0],'job':jobs[1]}).encode())
    print('Prepared isolated queued metadata/executable fixtures and enrollment. No assignment or hardware result.')
else:
    data=json.loads(private.read_text())
    if mode=='configure':
        configure(Actor(data['admin']),data['project'],data['agent'],data['device'],data['version'],sys.argv[2],'isolated-shared-station')
        print('Configured explicit simulator scope; authenticated native poll still required.')
    elif mode=='upgrade-package':
        if Attempt.objects.exists():raise SystemExit('Existing allocation preserved; no package substitution permitted.')
        from lab.models import TestVersion
        previous=TestVersion.objects.get(pk=data['version'])
        version=publish(Actor(data['admin']),data['project'],previous.definition_id,workload_wheel=sys.argv[2])
        approval(Actor(data['admin']),data['project'],version.pk,True)
        member=Membership.objects.get(user_id=data['admin'],project_id=data['project'])
        version_grant(Actor(data['admin']),data['project'],member.pk,version.pk,True)
        old=Job.objects.get(pk=data['job'])
        payload={'project_id':data['project'],'items':[{'version_id':str(version.pk),'device_id':data['device'],
            'expected_artifact_id':str(old.expected_id),'actual_artifact_id':str(old.actual_id),'parameters':old.parameters}]}
        batch,_=submit(Actor(data['admin']),'final-package-reviewed',payload)
        data.update(version=str(version.pk),job=str(batch.jobs.get().pk));private.write_text(json.dumps(data))
        print('Published/granted a new immutable review version for the final package; prior queued versions retained.')
    elif mode=='check':
        assert Job.objects.get(pk=data['old_job']).state=='queued'
        assert not Attempt.objects.filter(job_id=data['old_job']).exists()
        attempt=Attempt.objects.get(job_id=data['job'])
        assert attempt.state=='awaiting_evidence' and len(attempt.receipt_sha256)==64
        assert attempt.leases.filter(released_at=None).count()==4
        from agent.journal import Journal
        status=Journal(root/f'.local/{prefix}-agent-journal').reconcile(str(attempt.pk))
        assert status['state']=='COMPLETE' and status['result']['outcome']=='PASS' and status['spawn_records']==1
        assert status['completion_hash']==attempt.receipt_sha256 and status['ack_source'] is None
        from agent.journal import JournalError
        try:
            Journal(root/f'.local/{prefix}-agent-journal').acknowledge_local(str(attempt.pk),attempt.epoch,status['completion_hash'])
        except JournalError:pass
        else:raise AssertionError('Server assignment accepted a fake local-demo evidence acknowledgement.')
        print('PASS real HTTP/native journal: one assignment/spawn, local PASS, identical replay, receipt only; four leases held, no evidence ACK; legacy job stays queued.')
        (root/f'.local/{prefix}-live-verification.json').write_text(json.dumps({'assignment_id':str(attempt.pk),'epoch':attempt.epoch,
            'backend_state':attempt.state,'journal_state':status['state'],'local_outcome':status['result']['outcome'],
            'spawn_records':status['spawn_records'],'held_leases':4,'evidence_acknowledged':False,'legacy_job_queued':True}))
    elif mode=='render':
        import re,shutil
        from django.test import Client
        from django.urls import reverse
        user=User.objects.get(pk=data['admin']);client=Client(HTTP_HOST='127.0.0.1');client.force_login(user)
        response=client.get(reverse('agents',args=[data['project']]))
        assert response.status_code==200
        html=response.content.decode().replace('<main id="main" class="content">','<main id="main" class="content"><div class="notice">Layout snapshot · isolated synthetic contact data · forms inactive · no hardware readiness</div>')
        html=re.sub(r'<input type="hidden" name="csrfmiddlewaretoken"[^>]*>','',html)
        html=re.sub(r'<form\b[^>]*>','<div>',html).replace('</form>','</div>').replace('<button ','<button disabled ')
        folder=root/'.local/b5-preview';(folder/'static').mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/'web/static/lab.css',folder/'static/lab.css');(folder/'agents.html').write_text(html,encoding='utf-8')
        print('Rendered labeled actual-template layout snapshot; no active forms or credential values.')
    elif mode=='revoke':
        with transaction.atomic():
            DeviceGrant.objects.filter(membership__user_id=data['admin'],device_id=data['device']).delete()
            audit(User.objects.get(pk=data['admin']),Project.objects.get(pk=data['project']),'grant.review_revoked',data['device'])
        print('Revoked isolated requester grant; allocation must remain held.')
    elif mode=='recover-enrollment':
        if Attempt.objects.exists():raise SystemExit('Existing allocations preserved; no fixture reset permitted.')
        DeviceGrant.objects.get_or_create(membership=Membership.objects.get(user_id=data['admin'],project_id=data['project']),device_id=data['device'])
        ticket=manage_agent(Actor(data['admin']),data['project'],data['agent'],'reenroll')
        path=root/f'.local/{prefix}-enrollment.json';path.unlink()
        from agent.journal import durable_write
        durable_write(path,json.dumps(ticket).encode())
        old=Job.objects.get(pk=data['job'])
        payload={'project_id':data['project'],'items':[{'version_id':data['version'],'device_id':data['device'],
            'expected_artifact_id':str(old.expected_id),'actual_artifact_id':str(old.actual_id),'parameters':old.parameters}]}
        batch,_=submit(Actor(data['admin']),'fresh-after-ambiguous-enrollment',payload)
        data['job']=str(batch.jobs.get().pk);private.write_text(json.dumps(data))
        print('Explicitly reissued isolated enrollment, revoked the lost key, restored test grant and created a new queued review request. Prior records retained.')
    elif mode=='retire':
        with transaction.atomic():
            user=User.objects.select_for_update().get(pk=data['admin']);user.is_active=False;user.session_epoch+=1;user.save(update_fields=['is_active','session_epoch'])
            Agent.objects.filter(pk=data['agent']).update(enabled=False,execution_enabled=False,execution_contact_at=None)
            AgentCredential.objects.filter(agent_id=data['agent'],revoked_at=None).update(revoked_at=timezone.now())
            AgentEnrollment.objects.filter(agent_id=data['agent'],revoked_at=None).update(revoked_at=timezone.now())
            Attempt.objects.all().update(state='quarantined')
            Resource.objects.filter(lease__released_at=None).update(quarantined=True)
            Job.objects.filter(pk=data['job']).update(state='quarantined',dispatch_reason='REVIEW_RETIRED')
            audit(user,Project.objects.get(pk=data['project']),'review.scope_retired',data['agent'])
        for name in (f'{prefix}-review-meta.json',f'{prefix}-enrollment.json',f'{prefix}-state.json'):(root/'.local'/name).unlink(missing_ok=True)
        print('Retired only isolated review account/keys; journal, records and held/quarantined allocation retained.')
    else:raise SystemExit('Use prepare/configure/check/revoke/retire.')
