"""
Management command to test password decryption and identify problematic passwords.
"""
from django.core.management.base import BaseCommand
from vault.models import Password
from django.db.models import Q
import logging

logger = logging.getLogger('vault')


class Command(BaseCommand):
    help = 'Test decryption of all passwords to identify those encrypted with old/wrong keys'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password-id',
            type=int,
            help='Test specific password ID'
        )
        parser.add_argument(
            '--organization-id',
            type=int,
            help='Test passwords for specific organization'
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Prompt to re-encrypt passwords that fail (interactive)'
        )

    def handle(self, *args, **options):
        # Build queryset
        passwords = Password.objects.all()

        if options['password_id']:
            passwords = passwords.filter(id=options['password_id'])
        if options['organization_id']:
            passwords = passwords.filter(organization_id=options['organization_id'])

        # Filter only passwords with encrypted data (not OTP-only)
        passwords = passwords.exclude(
            Q(password_type='otp') & Q(encrypted_password='')
        )

        total = passwords.count()
        successful = 0
        failed = 0
        failed_passwords = []

        self.stdout.write(f"\nTesting decryption of {total} passwords...\n")

        for password in passwords:
            if not password.encrypted_password:
                continue

            try:
                # Attempt decryption
                plaintext = password.get_password()

                if plaintext:
                    successful += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ ID {password.id}: {password.title} - OK")
                    )
                else:
                    failed += 1
                    failed_passwords.append(password)
                    self.stdout.write(
                        self.style.WARNING(f"⚠ ID {password.id}: {password.title} - Empty password")
                    )

            except Exception as e:
                failed += 1
                failed_passwords.append(password)
                self.stdout.write(
                    self.style.ERROR(f"✗ ID {password.id}: {password.title} - FAILED: {str(e)}")
                )

        # Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write(f"Total: {total}")
        self.stdout.write(self.style.SUCCESS(f"Successful: {successful}"))
        self.stdout.write(self.style.ERROR(f"Failed: {failed}"))
        self.stdout.write("="*60 + "\n")

        if failed_passwords:
            self.stdout.write(self.style.WARNING("\nPasswords that failed decryption:"))
            for pwd in failed_passwords:
                self.stdout.write(
                    f"  - ID {pwd.id}: {pwd.title} (Org: {pwd.organization.name})"
                )

            self.stdout.write("\n" + self.style.WARNING("ACTION REQUIRED:"))
            self.stdout.write("These passwords were encrypted with a different master key.")
            self.stdout.write("To fix:")
            self.stdout.write("  1. Edit each password in the web interface")
            self.stdout.write("  2. Re-enter the plaintext password")
            self.stdout.write("  3. Save (will re-encrypt with current key)")
            self.stdout.write("\nAlternatively, if you have the old master key:")
            self.stdout.write("  1. Temporarily restore old APP_MASTER_KEY in .env")
            self.stdout.write("  2. Run: python manage.py migrate_encryption")
            self.stdout.write("  3. Restore new APP_MASTER_KEY\n")
        else:
            self.stdout.write(self.style.SUCCESS("\n✓ All passwords decrypt successfully!\n"))
