"""Emergency recovery for API access control.

Needs shell access to the server (it runs as the application user), which is
the point: there is no HTTP bypass. Every change is written to the audit log.

    manage.py api_access_recover --status
    manage.py api_access_recover --unrestrict            # both surfaces back to Unrestricted
    manage.py api_access_recover --unrestrict --surface webhook
    manage.py api_access_recover --disable-rule 12 --disable-rule 13
    manage.py api_access_recover --disable-all-rules
    manage.py api_access_recover --disable-proxies       # trusted proxies added in Settings
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api_access import policy as P
from api_access.models import ApiAccessRule, ApiAccessSettings, TrustedProxy


class Command(BaseCommand):
    help = 'Inspect or relax API access control from the server shell (lockout recovery).'

    def add_arguments(self, parser):
        parser.add_argument('--status', action='store_true', help='Show modes and active rules.')
        parser.add_argument('--unrestrict', action='store_true',
                            help='Set the global mode to Unrestricted.')
        parser.add_argument('--surface', choices=('api', 'webhook', 'both'), default='both')
        parser.add_argument('--disable-rule', type=int, action='append', default=[],
                            metavar='ID', help='Disable one rule (repeatable).')
        parser.add_argument('--disable-all-rules', action='store_true',
                            help='Disable every rule (they stay listed and can be re-enabled).')
        parser.add_argument('--disable-proxies', action='store_true',
                            help='Disable every trusted proxy added in Settings (.env proxies stay).')

    def handle(self, *args, **opts):
        changing = (opts['unrestrict'] or opts['disable_rule'] or opts['disable_all_rules']
                    or opts['disable_proxies'])
        if not changing:
            opts['status'] = True
        changes = []
        with transaction.atomic():
            settings = ApiAccessSettings.get()
            if opts['unrestrict']:
                if opts['surface'] in ('api', 'both'):
                    settings.api_mode = ApiAccessSettings.MODE_UNRESTRICTED
                if opts['surface'] in ('webhook', 'both'):
                    settings.webhook_mode = ApiAccessSettings.MODE_UNRESTRICTED
                settings.save(update_fields=['api_mode', 'webhook_mode', 'updated_at'])
                changes.append(f'mode set to Unrestricted ({opts["surface"]})')
            if opts['disable_rule']:
                found = set(ApiAccessRule.objects.filter(pk__in=opts['disable_rule'])
                            .values_list('pk', flat=True))
                missing = sorted(set(opts['disable_rule']) - found)
                if missing:
                    raise CommandError(f'No rule with id {", ".join(map(str, missing))}.')
                ApiAccessRule.objects.filter(pk__in=found).update(is_active=False)
                changes.append(f'disabled rules {sorted(found)}')
            if opts['disable_all_rules']:
                n = ApiAccessRule.objects.filter(is_active=True).update(is_active=False)
                changes.append(f'disabled all {n} active rules')
            if opts['disable_proxies']:
                n = TrustedProxy.objects.filter(is_active=True).update(is_active=False)
                changes.append(f'disabled {n} trusted proxies added in Settings')
            if changes:
                ApiAccessSettings.bump()
        if changes:
            P.reset_cache()
            from core.client_ip import reset_managed_cache
            reset_managed_cache()
            from audit.models import AuditLog
            AuditLog.log(user=None, action='update', object_type='ApiAccessSettings',
                         description='API access recovery from the server shell: ' + '; '.join(changes),
                         extra_data={'source': 'api_access_recover', 'changes': changes})
            for line in changes:
                self.stdout.write(self.style.WARNING(line))
            self.stdout.write('Other workers pick up the change on their next API request '
                              '(trusted proxies within 10 seconds).')
        if opts['status']:
            self._status()

    def _status(self):
        s = ApiAccessSettings.get()
        self.stdout.write(f'Policy version {s.policy_version}')
        self.stdout.write(f'  API mode:     {s.api_mode}')
        self.stdout.write(f'  Webhook mode: {s.webhook_mode}')
        proxies = TrustedProxy.objects.filter(is_active=True)
        self.stdout.write(f'Trusted proxies from Settings: {", ".join(p.network for p in proxies) or "none"}')
        rules = ApiAccessRule.objects.filter(is_active=True).order_by('pk')
        self.stdout.write(f'Active rules: {rules.count()}')
        for r in rules:
            exp = f' expires {r.expires_at:%Y-%m-%d %H:%M}' if r.expires_at else ''
            self.stdout.write(f'  #{r.pk} {r.action:5} {r.network:20} {r.surface:7} '
                              f'{r.scope_label()} — {r.name}{exp}')
