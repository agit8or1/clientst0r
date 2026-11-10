"""
Management command to auto-sync network device connections and import assets.

Run via cron:
    */30 * * * * /home/administrator/venv/bin/python manage.py sync_network_assets

Or schedule via Settings > General.

Only syncs connections where auto_sync_assets=True and enough time has passed
since last_asset_sync_at (based on sync_interval_minutes).

UniFi goes through the same implementation as the manual Import to Assets
page (integrations.network_assets): device type from the controller's
product type / features / model, each site's devices into the customer the
site maps to, dedup by controller + MAC/serial within that customer. Sites
that are unmapped or mapped ambiguously are skipped and reported on the
connection's health, never guessed.
"""
from datetime import timedelta
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Auto-sync network device connections and import to asset registry'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Ignore sync_interval_minutes and sync every auto-sync connection now')

    def handle(self, *args, **options):
        from integrations.models import UnifiConnection, OmadaConnection, GrandstreamConnection
        from integrations.network_assets import summary_message, sync_flat_connection, sync_unifi_connection

        now = timezone.now()
        force = options.get('force')
        synced = 0
        errors = 0
        partial = 0

        def _report(label, conn, result):
            nonlocal synced, errors, partial
            if result['status'] == 'error':
                errors += 1
                self.stderr.write(self.style.ERROR(f"[{label}] {conn.name}: ERROR — {result['error']}"))
                return
            synced += 1
            line = f"[{label}] {conn.name}: synced, {summary_message(result)}"
            if result['status'] == 'partial':
                partial += 1
                self.stdout.write(self.style.WARNING(line + ' (partial)'))
                for it in result.get('issues', [])[:10]:
                    self.stdout.write(f"    - {it['message']} {it.get('action', '')}".rstrip())
            else:
                self.stdout.write(self.style.SUCCESS(line))

        for conn in UnifiConnection.objects.filter(is_active=True, auto_sync_assets=True):
            if not force and not self._should_sync(conn, now):
                continue
            try:
                _report('UniFi', conn, sync_unifi_connection(conn))
            except Exception as e:  # sync_unifi_connection records its own errors
                errors += 1
                logger.error('sync_network_assets UniFi %s failed', conn.name, exc_info=True)
                self.stderr.write(self.style.ERROR(f"[UniFi] {conn.name}: ERROR — {type(e).__name__}"))

        for conn in OmadaConnection.objects.filter(is_active=True, auto_sync_assets=True):
            if not force and not self._should_sync(conn, now):
                continue
            try:
                from integrations.providers.omada import OmadaProvider
                creds = conn.get_credentials()
                provider = OmadaProvider(host=conn.host, username=creds.get('username', ''),
                                         password=creds.get('password', ''), verify_ssl=conn.verify_ssl)
                _report('Omada', conn, sync_flat_connection(conn, 'omada', provider, import_assets=True))
            except Exception as e:
                errors += 1
                logger.error('sync_network_assets Omada %s failed', conn.name, exc_info=True)
                self.stderr.write(self.style.ERROR(f"[Omada] {conn.name}: ERROR — {type(e).__name__}"))

        for conn in GrandstreamConnection.objects.filter(is_active=True, auto_sync_assets=True):
            if not force and not self._should_sync(conn, now):
                continue
            try:
                from integrations.providers.grandstream import GrandstreamProvider
                creds = conn.get_credentials()
                provider = GrandstreamProvider(host=conn.host, api_key=creds.get('api_key', ''),
                                               verify_ssl=conn.verify_ssl)
                _report('Grandstream', conn,
                        sync_flat_connection(conn, 'grandstream', provider, import_assets=True))
            except Exception as e:
                errors += 1
                logger.error('sync_network_assets Grandstream %s failed', conn.name, exc_info=True)
                self.stderr.write(self.style.ERROR(f"[Grandstream] {conn.name}: ERROR — {type(e).__name__}"))

        self.stdout.write(f"\nDone. {synced} synced ({partial} partial), {errors} error(s).")

    def _should_sync(self, conn, now):
        """Return True if this connection is due for a sync."""
        interval = getattr(conn, 'sync_interval_minutes', 720)
        if interval == 0:
            return False
        last = getattr(conn, 'last_asset_sync_at', None)
        if last is None:
            return True
        return (now - last) >= timedelta(minutes=interval)
