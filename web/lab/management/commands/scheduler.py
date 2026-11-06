import time
from django.core.management.base import BaseCommand, CommandError
from lab.dispatch import schedule_once
from lab.submissions import Rejected


class Command(BaseCommand):
    help='Separate bounded PostgreSQL simulator allocator. Never runs plugins in HTTP workers.'

    def add_arguments(self,parser):
        parser.add_argument('--iterations',type=int,default=1)
        parser.add_argument('--interval',type=float,default=1)
        parser.add_argument('--confirm-simulated',action='store_true',required=True)

    def handle(self,*args,**options):
        if not 1<=options['iterations']<=1000 or not .1<=options['interval']<=60:
            raise CommandError('Use bounded iterations/interval.')
        try:
            for index in range(options['iterations']):
                execution=schedule_once()
                self.stdout.write(f'Assigned {execution}' if execution else 'No eligible allocation; existing/uncertain ownership stays held.')
                if index+1<options['iterations']:time.sleep(options['interval'])
        except Rejected as exc:
            raise CommandError(exc.message) from exc
