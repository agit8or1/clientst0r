"""
The restricted AI gateway worker.

    CLIENTST0R_PROCESS_ROLE=ai_gateway DJANGO_SETTINGS_MODULE=config.settings_ai_gateway \
        python manage.py ai_gateway_worker

Refuses to start if it can see the vault master key, so a mis-configured
launcher fails closed instead of running unisolated.
"""
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from psa_ai.services import gateway, gateway_keys


def assert_isolated():
    leaked = [n for n in ('APP_MASTER_KEY', 'APP_MASTER_KEY_PREVIOUS', 'SECRET_KEY_FALLBACKS')
              if os.environ.get(n)]
    if getattr(settings, 'APP_MASTER_KEY', '') or getattr(settings, 'APP_MASTER_KEY_PREVIOUS', ''):
        leaked.append('settings.APP_MASTER_KEY')
    if not gateway_keys.is_worker_process():
        raise CommandError('Start this with DJANGO_SETTINGS_MODULE=config.settings_ai_gateway.')
    if leaked:
        raise CommandError(f'Refusing to run: this process can see {", ".join(leaked)}.')


class Command(BaseCommand):
    help = 'Run claimed AI analysis runs in an isolated process.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process what is waiting, then exit.')
        parser.add_argument('--interval', type=float, default=1.0)

    def handle(self, *args, **opts):
        assert_isolated()
        while True:
            done = gateway.run_worker_once()
            if opts['once']:
                self.stdout.write(f'{done} run(s) executed.')
                return
            if not done:
                time.sleep(opts['interval'])
