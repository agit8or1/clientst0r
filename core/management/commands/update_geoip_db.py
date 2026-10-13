"""
Download the DB-IP country database used by the GeoIP firewall (v3.17.598).

    manage.py update_geoip_db                 # always download
    manage.py update_geoip_db --max-age-days 25   # only if missing or older

The app update runs the second form, so the file stays at most about a month
old without a separate timer.
"""
import time

from django.core.management.base import BaseCommand, CommandError

from core import geoip_db


class Command(BaseCommand):
    help = 'Download the DB-IP country database used by the GeoIP firewall'

    def add_arguments(self, parser):
        parser.add_argument('--max-age-days', type=int, default=0,
                            help='Skip if the current file is newer than this')

    def handle(self, *args, **opts):
        path = geoip_db.db_path()
        max_age = opts['max_age_days']
        if max_age and path.exists() and time.time() - path.stat().st_mtime < max_age * 86400:
            self.stdout.write(f'GeoIP database is current ({path})')
            return
        try:
            installed = geoip_db.download()
        except Exception as exc:
            raise CommandError(f'GeoIP database download failed: {exc}')
        self.stdout.write(self.style.SUCCESS(f'GeoIP database updated: {installed}'))
