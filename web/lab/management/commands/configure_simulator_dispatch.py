from django.core.management.base import BaseCommand, CommandError
from django.http import Http404
from contracts.v1 import ContractError
from lab.dispatch import configure
from lab.models import User
from lab.submissions import Actor, Rejected


class Command(BaseCommand):
    help='Explicit admin opt-in for one simulated device/version/agent and shared station; no jobs are assigned here.'

    def add_arguments(self,parser):
        for name in ('project','agent','device','test-version','administrator','wheel','shared-resource'):
            parser.add_argument('--'+name,required=True)
        parser.add_argument('--confirm-simulated',action='store_true',required=True)

    def handle(self,*args,**options):
        try:
            user=User.objects.get(email=options['administrator'].lower(),is_active=True)
            policy=configure(Actor(user.pk),options['project'],options['agent'],options['device'],options['test_version'],options['wheel'],options['shared_resource'])
        except (User.DoesNotExist,Rejected,ContractError,Http404,ValueError,OSError) as exc:
            raise CommandError('Simulator configuration rejected; verify current admin, approved version, matching package and scope.') from exc
        self.stdout.write(f'Simulator-only policy configured for device {policy.device_id}; fresh authenticated poll required. No hardware readiness granted.')
