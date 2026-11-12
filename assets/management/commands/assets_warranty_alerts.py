"""
v3.17.254 — Phase 13 v1: warranty expiry alert cron.

Run daily via cron. Finds Asset rows whose `warranty_expiry` falls
within the warning window (default 30 days), groups by organization,
and sends one digest email per org to that org's owners.

Per-asset deduplication via `last_warranty_alert_sent_at` — an asset
won't trigger another alert until 7 days have passed since the last
one (so an MSP doesn't get the same digest every day for 30 days).

Usage:
    python manage.py assets_warranty_alerts [--days N] [--dry-run]
"""
from collections import defaultdict
from datetime import date, timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import Membership, Role
from assets.models import Asset


class Command(BaseCommand):
    help = 'Email org owners about assets with warranty expiring soon.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=30,
            help='Warn about assets whose warranty expires within this many '
                 'days (default 30).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Don't send mail or stamp last_warranty_alert_sent_at; just "
                 'print what would be sent.',
        )

    def handle(self, *, days=30, dry_run=False, **kwargs):
        cutoff = date.today() + timedelta(days=days)
        # 7-day reminder cool-off so the same asset doesn't re-trigger daily.
        cooldown = timezone.now() - timedelta(days=7)

        qs = Asset.objects.filter(
            warranty_expiry__isnull=False,
            warranty_expiry__lte=cutoff,
            warranty_expiry__gte=date.today(),
        ).filter(
            Q(last_warranty_alert_sent_at__isnull=True)
            | Q(last_warranty_alert_sent_at__lte=cooldown)
        ).select_related('organization')

        per_org = defaultdict(list)
        for a in qs:
            per_org[a.organization].append(a)

        sent = 0
        for org, assets in per_org.items():
            # Active Owner accounts of the customer that can still see its
            # assets (assets_view there); deactivated accounts and roles
            # without asset access no longer receive asset names and serials.
            from accounts.permission_utils import has_perm_for_org
            owners = [
                m.user.email for m in Membership.objects.filter(
                    organization=org, is_active=True, role=Role.OWNER,
                    user__is_active=True,
                ).select_related('user', 'role_template')
                if m.user.email and has_perm_for_org(m.user, org, 'assets_view')
            ]
            if not owners:
                continue

            subject = f'[{org.name}] {len(assets)} asset warranty(ies) expiring soon'
            lines = [
                f'These assets at {org.name} have warranty expiring within {days} days:',
                '',
            ]
            for a in sorted(assets, key=lambda x: x.warranty_expiry):
                serial = f' (s/n {a.serial_number})' if a.serial_number else ''
                vendor = f' from {a.vendor}' if getattr(a, 'vendor', '') else ''
                lines.append(
                    f'  - {a.name}{serial}{vendor}: '
                    f'expires {a.warranty_expiry.isoformat()}'
                )
            lines += [
                '',
                'Renew or replace ahead of the date to avoid service gaps. '
                'Open the asset in Client St0r to update warranty details.',
            ]
            body = '\n'.join(lines)

            if dry_run:
                self.stdout.write(self.style.WARNING(
                    f'[DRY RUN] {org.name}: {len(assets)} assets to '
                    f'{len(owners)} owner(s)'
                ))
                continue

            try:
                send_mail(subject, body, None, owners, fail_silently=False)
                sent += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f'send to {owners} failed: {exc}'
                ))
                continue
            now = timezone.now()
            Asset.objects.filter(
                pk__in=[a.pk for a in assets],
            ).update(last_warranty_alert_sent_at=now)

        self.stdout.write(self.style.SUCCESS(
            f'Warranty alert run @ {timezone.now().isoformat()}: '
            f'{len(per_org)} orgs, {sent} sent, dry_run={dry_run}'
        ))
