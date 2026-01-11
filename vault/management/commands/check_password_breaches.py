"""
Management command to check passwords against breach databases.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from vault.models import Password, PasswordBreachCheck
from vault.breach_checker import PasswordBreachChecker
from audit.models import AuditLog


class Command(BaseCommand):
    help = 'Check all passwords against breach databases (HaveIBeenPwned)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force check even if recently checked'
        )
        parser.add_argument(
            '--password-id',
            type=int,
            help='Check specific password by ID'
        )
        parser.add_argument(
            '--organization-id',
            type=int,
            help='Check passwords for specific organization'
        )

    def handle(self, *args, **options):
        checker = PasswordBreachChecker()

        # Build queryset
        passwords = Password.objects.all()

        if options['password_id']:
            passwords = passwords.filter(id=options['password_id'])

        if options['organization_id']:
            passwords = passwords.filter(organization_id=options['organization_id'])

        # Filter by scan frequency unless forced
        if not options['force']:
            passwords = self._filter_by_scan_frequency(passwords)

        checked = 0
        breached = 0
        errors = 0

        self.stdout.write(f"Checking {passwords.count()} passwords...")

        for password in passwords:
            try:
                plaintext = password.get_password()
                is_breached, count = checker.check_password(plaintext)

                # Create breach check record
                PasswordBreachCheck.objects.create(
                    organization=password.organization,
                    password=password,
                    is_breached=is_breached,
                    breach_count=count
                )

                checked += 1
                if is_breached:
                    breached += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  BREACHED: {password.title} "
                            f"(found {count:,} times in breaches)"
                        )
                    )
                else:
                    if self.verbosity >= 2:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"✓ Safe: {password.title}"
                            )
                        )

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"❌ Error checking password {password.id} ({password.title}): {e}"
                    )
                )

        # Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Checked: {checked} passwords"
            )
        )
        if breached > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  Breached: {breached} passwords need attention"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ No breached passwords found"
                )
            )
        if errors > 0:
            self.stdout.write(
                self.style.ERROR(
                    f"❌ Errors: {errors} passwords could not be checked"
                )
            )
        self.stdout.write("="*60)

        # Log to audit trail
        try:
            AuditLog.objects.create(
                event_type='password_breach_scan',
                description=f"Scanned {checked} passwords, found {breached} breached",
                metadata={
                    'checked': checked,
                    'breached': breached,
                    'errors': errors
                }
            )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Could not create audit log: {e}")
            )

    def _filter_by_scan_frequency(self, passwords):
        """
        Filter passwords based on their scan frequency setting.
        Only returns passwords that need checking based on last check time.
        """
        from django.conf import settings

        # Get default frequency
        default_freq = settings.HIBP_DEFAULT_SCAN_FREQUENCY

        # Calculate which passwords need checking
        now = timezone.now()
        password_ids = []

        for password in passwords.only('id', 'custom_fields'):
            # Get scan frequency for this password (default to 24 hours)
            freq = password.custom_fields.get('hibp_scan_frequency', default_freq) if password.custom_fields else default_freq
            cutoff = now - timedelta(hours=int(freq))

            # Check if password needs scanning
            last_check = password.breach_checks.first()
            if not last_check or last_check.checked_at < cutoff:
                password_ids.append(password.id)

        return Password.objects.filter(id__in=password_ids)
