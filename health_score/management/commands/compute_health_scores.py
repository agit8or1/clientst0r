"""Compute and store today's customer health snapshot for every active client
(registered with the scheduler as `compute_health_scores`, nightly)."""
from django.core.management.base import BaseCommand

from core.models import Organization
from health_score import scoring


class Command(BaseCommand):
    help = 'Compute customer health snapshots (all active clients, or --client ID).'

    def add_arguments(self, parser):
        parser.add_argument('--client', type=int, action='append', help='Only this organization id (repeatable).')

    def handle(self, *args, **options):
        qs = Organization.objects.filter(is_active=True)
        if options.get('client'):
            qs = qs.filter(pk__in=options['client'])
        done = failed = 0
        for client in qs.iterator():
            try:
                scoring.compute_and_save(client)
                done += 1
            except Exception as exc:  # noqa: BLE001 - one client must not stop the run
                failed += 1
                self.stderr.write(f'{client.pk} {client.name}: {exc}')
        self.stdout.write(f'Health snapshots computed: {done}, failed: {failed}')
