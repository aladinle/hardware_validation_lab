from django.http import Http404, JsonResponse
from .api import api_view
from .evidence import download_response, permitted_job, result_data
from .models import OutputArtifact


@api_view(['GET'])
def result(request,actor,job_id):
    data=result_data(permitted_job(request,actor,job_id))
    if data is None:raise Http404
    return JsonResponse(data)


@api_view(['GET'])
def output(request,actor,output_id):
    record=OutputArtifact.objects.select_related('attempt__job').filter(pk=output_id).first()
    if record is None:raise Http404
    permitted_job(request,actor,record.attempt.job_id)
    return download_response(record)
