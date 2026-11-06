"""Guarded isolated PostgreSQL/native HTTP evidence review, never user lab data."""
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

root=Path(__file__).resolve().parent.parent
database=os.environ.get('PGDATABASE')
if os.environ.get('LAB_DB')!='postgres' or database not in {'hardware_lab_b6_pass_review','hardware_lab_b6_fail_review'}:
    raise SystemExit('Only the two named isolated M2B.6 review databases are allowed.')
sys.path.insert(0,str(root/'web'));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from agent.journal import Journal, durable_write
from lab.agent_services import create_agent
from lab.models import (Agent, AgentCredential, AgentEnrollment, Attempt, Device, DeviceGrant, ExecutionResult, Job, Lease,
                        Membership, OutputArtifact, Project, Resource, Role, User)
from lab.services import audit
from lab.submissions import Actor, approval, edit_draft, publish, submit, upload, version_grant

prefix='b6-pass' if database=='hardware_lab_b6_pass_review' else 'b6-fail'
meta=root/f'.local/{prefix}-meta.json'
mode=sys.argv[1]
if mode=='prepare':
    call_command('migrate',verbosity=0)
    if User.objects.exists():raise SystemExit('Existing review data preserved; no fixture reset.')
    user=User.objects.create_user(username=prefix+'@localhost.test',email=prefix+'@localhost.test')
    user.set_unusable_password();user.save(update_fields=['password'])
    project=Project.objects.create(name='M2B.6 isolated '+prefix)
    member=Membership.objects.create(project=project,user=user,role=Role.ADMIN)
    device=Device.objects.create(project=project,name='Synthetic CAN files, no discovery',source='simulated',capabilities=['can_payload_files'])
    DeviceGrant.objects.create(membership=member,device=device)
    draft=edit_draft(Actor(user.pk),project.pk,{'name':'CAN evidence review','header_bytes':2})
    legacy=publish(Actor(user.pk),project.pk,draft.pk)
    version=publish(Actor(user.pk),project.pk,draft.pk,workload_wheel=sys.argv[2])
    for v in (legacy,version):
        approval(Actor(user.pk),project.pk,v.pk,True);version_grant(Actor(user.pk),project.pk,member.pk,v.pk,True)
    artifacts={}
    for role,name in (('expected','expected-header.hex'),('actual','actual-pass.hex' if prefix=='b6-pass' else 'actual-missing.hex')):
        raw=(root/'examples/can'/name).read_bytes()
        artifacts[role]=upload(Actor(user.pk),project.pk,name,hashlib.sha256(raw).hexdigest(),raw)[0]
    jobs=[]
    for v,key in ((legacy,'metadata-only'),(version,'executable')):
        batch,_=submit(Actor(user.pk),key,{'project_id':str(project.pk),'items':[{'version_id':str(v.pk),'device_id':str(device.pk),
            'expected_artifact_id':str(artifacts['expected'].pk),'actual_artifact_id':str(artifacts['actual'].pk),'parameters':{'header_bytes':2}}]})
        jobs.append(str(batch.jobs.get().pk))
    agent,ticket=create_agent(Actor(user.pk),project.pk,'Native synthetic evidence receiver',[str(device.pk)])
    durable_write(root/f'.local/{prefix}-enrollment.json',json.dumps(ticket).encode())
    durable_write(meta,json.dumps({'user':user.pk,'project':str(project.pk),'device':str(device.pk),'version':str(version.pk),
        'agent':str(agent.pk),'legacy_job':jobs[0],'job':jobs[1]}).encode())
    print('Prepared isolated scope, immutable versions, queued fixtures and private enrollment. No assignment.')
else:
    data=json.loads(meta.read_text())
    if mode=='configure':
        call_command('configure_simulator_dispatch','--project',data['project'],'--agent',data['agent'],'--device',data['device'],
            '--test-version',data['version'],'--administrator',prefix+'@localhost.test','--wheel',sys.argv[2],
            '--shared-resource','isolated-b6-station','--confirm-simulated')
    elif mode in ('pending','check'):
        attempt=Attempt.objects.get(job_id=data['job'])
        journal=Journal(root/f'.local/{prefix}-journal');state=journal.reconcile(str(attempt.pk))
        assert state['spawn_records']==1 and attempt.leases.filter(released_at=None).count()==4
        assert Job.objects.get(pk=data['legacy_job']).state=='queued' and not Attempt.objects.filter(job_id=data['legacy_job']).exists()
        if mode=='pending':
            assert state['state']=='COMPLETE' and state['ack_source'] is None
            print('Interrupted client retains COMPLETE spool, one spawn, four leases; SQL result present:',ExecutionResult.objects.exists())
        else:
            result=ExecutionResult.objects.get(attempt=attempt)
            expected='PASS' if prefix=='b6-pass' else 'FAIL'
            assert result.outcome==state['result']['outcome']==expected
            assert state['state']=='ACKNOWLEDGED' and state['ack_source']=='authenticated_backend'
            assert result.completion_sha256==state['completion_hash'] and attempt.state=='completed'
            client=Client(HTTP_HOST='127.0.0.1');client.force_login(User.objects.get(pk=data['user']))
            cookie=client.cookies['sessionid'].value
            server=sys.argv[2]
            with urlopen(Request(server+f'/api/v1/jobs/{attempt.job_id}/result',headers={'Cookie':'sessionid='+cookie}),timeout=5) as response:
                report=json.load(response)
            assert report['runner']['outcome']==expected and report['evidence_acknowledged'] is True
            for output in OutputArtifact.objects.filter(attempt=attempt):
                with urlopen(Request(server+f'/api/v1/outputs/{output.pk}',headers={'Cookie':'sessionid='+cookie}),timeout=5) as response:
                    raw=response.read(output.size+1)
                assert hashlib.sha256(raw).hexdigest()==output.sha256 and raw==(journal.spool/str(attempt.pk)/output.name).read_bytes()
            page=client.get(reverse('job_page',args=[data['project'],data['job']]))
            assert page.status_code==200 and b'Stored execution result' in page.content
            folder=root/f'.local/{prefix}-preview';(folder/'static').mkdir(parents=True,exist_ok=True)
            import shutil
            import re
            shutil.copyfile(root/'web/static/lab.css',folder/'static/lab.css')
            html=page.content.decode().replace('<h1>Test request</h1>','<div class="notice">Read-only layout snapshot · isolated synthetic evidence</div><h1>Test request</h1>')
            html=re.sub(r'<input type="hidden" name="csrfmiddlewaretoken"[^>]*>','',html)
            html=re.sub(r'<form\b[^>]*>','<div>',html).replace('</form>','</div>').replace('<button ','<button disabled ')
            (folder/'job.html').write_text(html,encoding='utf-8')
            proof={'execution_id':str(attempt.pk),'outcome':expected,'state':attempt.state,'journal_state':state['state'],
                'spawn_records':state['spawn_records'],'held_leases':4,'outputs':attempt.outputs.count(),'events':attempt.events.count(),
                'evidence_acknowledged':True,'leases_released':False,'actual_http_downloads_verified':True}
            (root/f'.local/{prefix}-verification.json').write_text(json.dumps(proof),encoding='utf-8')
            print(json.dumps(proof))
    elif mode=='retire':
        with transaction.atomic():
            user=User.objects.select_for_update().get(pk=data['user']);user.is_active=False;user.session_epoch+=1;user.save(update_fields=['is_active','session_epoch'])
            Agent.objects.filter(pk=data['agent']).update(enabled=False,execution_enabled=False,execution_contact_at=None)
            AgentCredential.objects.filter(agent_id=data['agent'],revoked_at=None).update(revoked_at=timezone.now())
            AgentEnrollment.objects.filter(agent_id=data['agent'],revoked_at=None).update(revoked_at=timezone.now())
            Resource.objects.filter(lease__released_at=None).update(quarantined=True)
            audit(user,Project.objects.get(pk=data['project']),'review.scope_retired',data['agent'])
        for name in (f'{prefix}-meta.json',f'{prefix}-enrollment.json',f'{prefix}-state.json'):(root/'.local'/name).unlink(missing_ok=True)
        print('Retired isolated account and agent credentials. Original outcomes/evidence/held leases retained.')
    else:raise SystemExit('Use prepare/configure/pending/check/retire.')
