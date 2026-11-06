"""Assignment-bound SQL evidence, immutable outcomes, current read authorization."""
from django.db.models import Sum
from django.http import Http404, HttpResponse
from contracts.agents_v1 import schema
from contracts.evidence_v1 import (MAX_OUTPUT_TOTAL, OUTPUT_LIMITS, content_sha, output_name,
                                   validate_completion, validate_report_bytes)
from contracts.journal_v1 import checksum
from contracts.runner_v1 import strict_json
from contracts.v1 import ContractError
from .dispatch import enabled, guard, receiver
from .models import ExecutionEvent, ExecutionResult, Job, OutputArtifact, Resource
from .services import audit
from .submissions import Rejected, read_input


def owned(agent_id,raw,payload):
    enabled()
    agent,_=receiver(agent_id,raw)
    attempt=guard(agent,payload['execution_id'],payload['epoch'],payload['claim_token'],allow_finalized=True)
    return agent,attempt


def event(agent_id,raw,payload):
    schema(payload,{'execution_id','epoch','claim_token','sequence','kind'})
    agent,attempt=owned(agent_id,raw,payload)
    sequence,kind=payload['sequence'],payload['kind']
    if type(sequence) is not int or sequence not in (1,2) or kind!={1:'execution_accepted',2:'local_completion_sealed'}[sequence]:
        raise ContractError('Use bounded ordered execution events.')
    value=checksum({'sequence':sequence,'kind':kind})
    existing=ExecutionEvent.objects.filter(attempt=attempt,sequence=sequence).first()
    if existing:
        if existing.body_sha256!=value:raise Rejected('EVENT_CONFLICT','Event replay differs.',409)
    else:
        if hasattr(attempt,'execution_result') or sequence!=attempt.events.count()+1:
            raise Rejected('EVENT_SEQUENCE','Event sequence unavailable.',409)
        ExecutionEvent.objects.create(attempt=attempt,sequence=sequence,kind=kind,body_sha256=value)
        audit(None,agent.project,'execution.event_received',attempt.pk)
    return {'schema_version':1,'execution_id':str(attempt.pk),'epoch':attempt.epoch,'sequence':sequence,'recorded':True}


def upload_output(agent_id,raw,request):
    if request.content_type!='application/octet-stream':raise ContractError('Use bounded binary evidence.')
    identity={'execution_id':request.headers.get('X-Execution-ID'),'epoch':int(request.headers.get('X-Claim-Epoch','0')),
              'claim_token':request.headers.get('X-Claim-Token')}
    agent,attempt=owned(agent_id,raw,identity)
    name=output_name(request.headers.get('X-Evidence-Name'))
    size=request.headers.get('Content-Length') or '0'
    if not size.isascii() or not size.isdecimal() or int(size)>OUTPUT_LIMITS[name]:
        raise Rejected('EVIDENCE_SIZE','Evidence size exceeds bound.',413)
    data=request.read(OUTPUT_LIMITS[name]+1)
    if len(data)!=int(size) or len(data)>OUTPUT_LIMITS[name] or content_sha(data)!=request.headers.get('X-Content-SHA256'):
        raise ContractError('Evidence size/checksum mismatch.')
    if name.endswith('.json'):strict_json(data)
    elif name.endswith('.txt'):
        try:data.decode('utf-8')
        except UnicodeError:raise ContractError('Expected UTF-8 human report.') from None
    existing=OutputArtifact.objects.filter(attempt=attempt,name=name).first()
    if existing:
        if existing.sha256!=content_sha(data) or existing.size!=len(data) or bytes(existing.content)!=data:
            raise Rejected('EVIDENCE_CONFLICT','Original evidence is immutable.',409)
    else:
        total=attempt.outputs.aggregate(total=Sum('size'))['total'] or 0
        if hasattr(attempt,'execution_result') or total+len(data)>MAX_OUTPUT_TOTAL:
            raise Rejected('EVIDENCE_CLOSED','Evidence inventory closed or full.',409)
        existing=OutputArtifact.objects.create(attempt=attempt,name=name,sha256=content_sha(data),size=len(data),content=data)
        audit(None,agent.project,'execution.output_stored',existing.pk)
    return {'schema_version':1,'execution_id':str(attempt.pk),'epoch':attempt.epoch,'name':name,
            'sha256':existing.sha256,'size':existing.size,'stored':True}


def acknowledgement(result):
    return {'schema_version':1,'execution_id':str(result.attempt_id),'epoch':result.attempt.epoch,
            'completion_sha256':result.completion_sha256,'evidence_acknowledged':True,
            'leases_released':False,'hardware_ready':False}


def finalize(agent_id,raw,payload):
    schema(payload,{'execution_id','epoch','claim_token','completion','completion_sha256'})
    agent,attempt=owned(agent_id,raw,payload)
    sealed=payload['completion'];value=checksum(sealed)
    if value!=payload['completion_sha256'] or attempt.receipt_sha256!=value:
        raise Rejected('COMPLETION_CONFLICT','Completion does not match its receipt.',409)
    existing=ExecutionResult.objects.filter(attempt=attempt).first()
    if existing:
        if existing.completion_sha256!=value:raise Rejected('RESULT_CONFLICT','Original outcome is immutable.',409)
        return acknowledgement(existing)
    if attempt.state!='awaiting_evidence':raise Rejected('RESULT_STATE','Completion receipt required.',409)
    result=validate_completion(sealed,attempt.assignment)
    outputs={o.name:o for o in attempt.outputs.all()}
    refs={name:ref for name,ref in sealed['files'].items() if name in OUTPUT_LIMITS}
    if set(outputs)!=set(refs) or any({'size':o.size,'sha256':o.sha256}!=refs[name] for name,o in outputs.items()):
        raise Rejected('EVIDENCE_INCOMPLETE','Upload the complete sealed evidence inventory first.',409)
    if strict_json(bytes(outputs['run/run.json'].content))!=result:
        raise ContractError('Sealed runner record differs from uploaded bytes.')
    if result.get('report_collected'):
        report=validate_report_bytes(bytes(outputs['run/report.json'].content),attempt.assignment,result)
        # Pure validation only. No worker/process or hardware is invoked by HTTP.
        from agent.runner import validate_output
        from workloads.can_payload_compare import human_report
        staged={role:read_input(getattr(attempt.job,role)) for role in ('expected','actual')}
        checked=validate_output(bytes(outputs['run/report.json'].content),probe=None,staged=staged,
                                digest=attempt.assignment['manifest']['plugin_package_sha256'],parameters=attempt.assignment['parameters'])
        if checked!=report or bytes(outputs['run/report.txt'].content)!=human_report(report).encode():
            raise ContractError('Human/JSON report conflict.')
    if list(attempt.events.order_by('sequence').values_list('sequence',flat=True))!=[1,2]:
        raise Rejected('EVENTS_INCOMPLETE','Ordered lifecycle events required.',409)
    envelope={'schema_version':1,'source':'simulated','execution_id':str(attempt.pk),'epoch':attempt.epoch,
              'job_id':str(attempt.job_id),'run_id':str(attempt.job.run.pk),'agent_id':str(agent.pk),
              'project_id':str(agent.project_id),'snapshot':attempt.job.snapshot,'assignment':attempt.assignment,
              'completion_sha256':value,'runner':result,'measurements':{'duration':{'value':result['duration_seconds'],'unit':'seconds'}},
              'hardware_readiness':'NOT_EVALUATED','firmware':None,'sensors':None,
              'assignment_created_at':attempt.created_at.isoformat(),
              'events':[{'sequence':e.sequence,'kind':e.kind,'received_at':e.received_at.isoformat()} for e in attempt.events.order_by('sequence')],
              'outputs':[{'id':str(o.pk),'name':o.name,'size':o.size,'sha256':o.sha256} for o in outputs.values()]}
    stored=ExecutionResult.objects.create(attempt=attempt,completion_sha256=value,outcome=result['outcome'],
        evaluation_status=result['evaluation_status'],cleanup_status=result['cleanup_status'],evidence_status=result['evidence_status'],
        termination_confirmed=True,quarantine_required=result['quarantine_required'],report=envelope)
    state='quarantined' if result['quarantine_required'] else 'completed'
    attempt.state=state;attempt.save(update_fields=['state'])
    Job.objects.filter(pk=attempt.job_id).update(state=state,dispatch_reason='CLEANUP_OR_EVIDENCE_INCOMPLETE' if result['quarantine_required'] else '')
    if result['quarantine_required']:
        Resource.objects.filter(lease__attempt=attempt,lease__released_at=None).update(quarantined=True)
    audit(None,agent.project,'execution.result_recorded',attempt.pk)
    return acknowledgement(stored)


def permitted_job(request,actor,job_id):
    from .api import visible_jobs
    from .submissions import locked_scope
    job=Job.objects.filter(pk=job_id).first()
    if job is None:raise Http404
    user,project,role,member,_=locked_scope(actor,job.batch.project_id)
    permitted=visible_jobs(actor,user,project,role,member).filter(pk=job_id).first()
    if permitted is None:raise Http404
    return permitted


def result_data(job):
    result=ExecutionResult.objects.filter(attempt__job=job).select_related('attempt').first()
    if result is None:return None
    return {**result.report,'received_at':result.received_at.isoformat(),'lifecycle':result.attempt.state,
            'evidence_acknowledged':True,'leases_released':False}


def download_response(output):
    data=bytes(output.content)
    if len(data)!=output.size or content_sha(data)!=output.sha256:
        raise Rejected('EVIDENCE_CORRUPT','Stored evidence failed verification.',503)
    response=HttpResponse(data,content_type='application/octet-stream')
    response['Content-Disposition']='attachment; filename="'+output.name.replace('/','-')+'"'
    response['X-Content-SHA256']=output.sha256
    response['Cache-Control']='private, no-store'
    return response
