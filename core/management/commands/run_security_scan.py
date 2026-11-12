"""
Management command: automated security scan with email alerts.
Runs OS package scan + Snyk (if configured), then emails all superusers
if any vulnerabilities or security updates are found.
"""
import logging
import uuid
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger('core')


class Command(BaseCommand):
    help = 'Run automated security scan and alert superusers on findings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run scan but do not send alerts',
        )
        parser.add_argument(
            '--os-only',
            action='store_true',
            help='Only run OS package scan, skip Snyk',
        )
        parser.add_argument(
            '--snyk-only',
            action='store_true',
            help='Only run Snyk scans, skip OS packages',
        )

    def handle(self, *args, **options):
        from core.models import SystemSetting, SnykScan, SystemPackageScan

        dry_run = options['dry_run']
        os_only = options['os_only']
        snyk_only = options['snyk_only']

        self.stdout.write(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] Automated security scan starting...")
        if dry_run:
            self.stdout.write(self.style.WARNING('  DRY RUN — alerts will not be sent'))

        settings = SystemSetting.get_settings()
        scan_start = timezone.now()
        findings = []  # list of (category, detail) tuples

        # ── OS Package Scan ───────────────────────────────────────────────────
        if not snyk_only:
            self.stdout.write('  Running OS package scan...')
            try:
                call_command('scan_system_packages', save=True, verbosity=0)
                # Fetch the freshly-saved record
                pkg_scan = SystemPackageScan.objects.filter(
                    scan_date__gte=scan_start - timedelta(seconds=30)
                ).order_by('-scan_date').first()

                if pkg_scan:
                    sec = pkg_scan.security_updates or 0
                    upg = pkg_scan.upgradeable_packages or 0
                    self.stdout.write(f"    OS: {sec} security updates, {upg} total upgradeable")
                    if sec > 0:
                        findings.append(('OS Security Updates', f"{sec} security update(s) available ({upg} total upgradeable packages)"))
                    elif upg > 0:
                        self.stdout.write(f"    OS: {upg} non-security updates available (not alerting)")
                else:
                    self.stdout.write(self.style.WARNING('    OS scan result not found in DB'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    OS package scan failed: {e}'))
                logger.error(f'[run_security_scan] OS scan failed: {e}')

        # ── Snyk Scans ────────────────────────────────────────────────────────
        if not os_only and settings.snyk_enabled and settings.snyk_api_token:
            for scan_type in ('open_source', 'code', 'iac'):
                scan_id = f'auto-{scan_type}-{uuid.uuid4().hex[:8]}'
                self.stdout.write(f'  Running Snyk {scan_type} scan...')
                try:
                    call_command('run_snyk_scan', scan_id=scan_id,
                                 scan_type=scan_type, verbosity=0)
                    snyk = SnykScan.objects.filter(scan_id=scan_id).first()
                    if snyk and snyk.status == 'completed':
                        n = snyk.total_vulnerabilities or 0
                        self.stdout.write(f"    Snyk {scan_type}: {n} vulnerabilities "
                                          f"(C:{snyk.critical_count} H:{snyk.high_count} "
                                          f"M:{snyk.medium_count} L:{snyk.low_count})")
                        if n > 0:
                            label = snyk.get_scan_type_display()
                            detail = (
                                f"{n} vulnerability/vulnerabilities — "
                                f"Critical: {snyk.critical_count}, "
                                f"High: {snyk.high_count}, "
                                f"Medium: {snyk.medium_count}, "
                                f"Low: {snyk.low_count}"
                            )
                            findings.append((f'Snyk {label}', detail))
                            if settings.site_url:
                                detail_url = f"{settings.site_url.rstrip('/')}/core/settings/snyk/scans/{snyk.id}/"
                                findings[-1] = (f'Snyk {label}', detail + f"\n  Details: {detail_url}")
                    elif snyk:
                        self.stdout.write(self.style.WARNING(f'    Snyk {scan_type}: {snyk.status}'))
                    else:
                        self.stdout.write(self.style.WARNING(f'    Snyk {scan_type}: no result record'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'    Snyk {scan_type} failed: {e}'))
                    logger.error(f'[run_security_scan] Snyk {scan_type} failed: {e}')
        elif not os_only:
            self.stdout.write('  Snyk not configured or disabled — skipping')

        # ── Alert ─────────────────────────────────────────────────────────────
        if not findings:
            self.stdout.write(self.style.SUCCESS('  No security findings — no alerts sent'))
            return

        self.stdout.write(self.style.WARNING(f'  {len(findings)} finding category/categories — sending alerts...'))

        if dry_run:
            for cat, detail in findings:
                self.stdout.write(f'    [DRY RUN] Would alert: {cat}')
            return

        sent = self._send_alerts(settings, findings)
        if sent:
            self.stdout.write(self.style.SUCCESS(f'  Alerts sent to {sent} superuser(s)'))
        else:
            self.stdout.write(self.style.WARNING('  No alerts sent (no superusers with email, or SMTP not configured)'))

    def _send_alerts(self, settings, findings):
        """Email all superusers about the findings. Returns number of emails sent."""
        from core.superuser_alerts import email_superusers

        site_name = settings.site_name or 'Client St0r'
        site_url = (settings.site_url or '').rstrip('/')
        dashboard_url = f"{site_url}/core/security/" if site_url else ''

        subject = f"[{site_name}] Security Alert — {len(findings)} finding(s) detected"

        lines = [
            f"Automated security scan completed on {timezone.now().strftime('%Y-%m-%d %H:%M UTC')}.",
            f"The following security issues were detected:",
            '',
        ]
        for cat, detail in findings:
            lines.append(f"  ● {cat}")
            for dline in detail.split('\n'):
                lines.append(f"    {dline}")
            lines.append('')

        if dashboard_url:
            lines += [f"View the Security Dashboard: {dashboard_url}", '']

        lines += [
            "---",
            f"This is an automated alert from {site_name}.",
            "To adjust scan frequency or disable alerts, go to Settings → Scheduler.",
        ]
        body = '\n'.join(lines)

        return email_superusers(
            subject, body, settings=settings, log_prefix='run_security_scan',
            write=self.stdout.write,
        )
