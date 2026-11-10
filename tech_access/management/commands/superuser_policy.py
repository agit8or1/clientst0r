"""Host-level recovery for the superuser-grant approval policy (v3.17.653).

    manage.py superuser_policy                      # show the state
    manage.py superuser_policy --disable --reason "only one admin left"

Running this needs shell access to the server as the application user, which
is already installation-wide control; the application cannot stop it. It is
for an install that can no longer approve anything — for example the second
administrator left. Turning the policy off this way is audited and announced
to the verified recovery contact and every superuser.
"""
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from tech_access.models import ProtectionSettings
from tech_access.services import eligible_admins


class Command(BaseCommand):
    help = 'Show, or (host-level recovery) turn off, the superuser-grant approval policy.'

    def add_arguments(self, parser):
        parser.add_argument('--disable', action='store_true', help='Turn the policy off.')
        parser.add_argument('--reason', default='', help='Required with --disable; written to the audit log.')

    def handle(self, *args, **opts):
        s = ProtectionSettings.load()
        admins = list(eligible_admins().values_list('username', flat=True))
        if not opts['disable']:
            self.stdout.write(f"Superuser grants need approval: {'yes' if s.superuser_grant_requires_approval else 'no'}")
            self.stdout.write(f"Eligible administrators ({len(admins)}): {', '.join(admins) or 'none'}")
            return
        reason = opts['reason'].strip()
        if not reason:
            raise CommandError('--reason is required with --disable.')
        if not s.superuser_grant_requires_approval:
            self.stdout.write('The policy is already off.')
            return
        s.superuser_grant_requires_approval = False
        s.save(update_fields=['superuser_grant_requires_approval', 'updated_at'])
        from audit.models import AuditLog
        AuditLog.log(user=None, action='update', object_type='superuser_policy', object_id=s.pk,
                     description=f'Superuser-grant approval turned off from the host: {reason}'[:1000],
                     extra_data={'event': 'superuser_policy_disabled_on_host', 'reason': reason[:500],
                                 'eligible_admins': admins})
        recipients = set(eligible_admins().exclude(email='').values_list('email', flat=True))
        if s.recovery_email and s.recovery_verified_at:
            recipients.add(s.recovery_email)
        if recipients:
            send_mail('[ClientSt0r] Superuser-grant approval turned off on the host',
                      f'The policy was turned off with manage.py superuser_policy --disable.\n\nReason: {reason}',
                      None, sorted(recipients), fail_silently=True)
        self.stdout.write(self.style.WARNING('Superuser-grant approval is now off. This was audited and announced.'))
