"""Create service alerts for fleet vehicles whose service is coming due.

Run hourly by the in-app scheduler (task type vehicles_service_alerts), so
alerts appear without anyone opening the vehicle's page. Safe to run any
time: a schedule with a pending alert never gets a second one.

Usage:
    python manage.py vehicles_service_alerts
"""
from django.core.management.base import BaseCommand

from vehicles.services.service_alerts import generate_all_service_alerts


class Command(BaseCommand):
    help = 'Create pending service alerts for vehicles whose service schedule is due.'

    def handle(self, *args, **options):
        n = generate_all_service_alerts()
        self.stdout.write(f'{n} service alert(s) created.')
