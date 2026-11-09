"""Create the AI gateway key pair (psa_ai/services/gateway_keys.py)."""
from django.core.management.base import BaseCommand, CommandError

from psa_ai.services import gateway_keys


class Command(BaseCommand):
    help = 'Create the key pair AI provider keys are sealed to.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Replace an existing pair. Every stored provider key must then be re-entered.')

    def handle(self, *args, **opts):
        try:
            d = gateway_keys.generate(force=opts['force'])
        except gateway_keys.GatewayKeyError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f'AI gateway keys written to {d}'))
        self.stdout.write('public.key is read by the web app; private.key (0600) only by the gateway.')
        if gateway_keys.mode() != 'worker':
            self.stdout.write(self.style.WARNING(
                'AI_GATEWAY_MODE is in_process: the web app opens provider keys itself (not isolated). '
                'Set AI_GATEWAY_MODE=worker and run ai_gateway_worker for isolation.'))
