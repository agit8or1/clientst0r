"""
Seed test passwords with various security levels for testing breach detection.
"""
from django.core.management.base import BaseCommand
from vault.models import Password
from core.models import Organization
from django.contrib.auth.models import User
from vault.breach_checker import PasswordBreachChecker
import secrets
import string


class Command(BaseCommand):
    help = 'Create test passwords (weak, strong, compromised) for breach detection testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization-id',
            type=int,
            help='Organization ID (default: first org)'
        )
        parser.add_argument(
            '--delete-old',
            action='store_true',
            help='Delete existing demo passwords first'
        )

    def handle(self, *args, **options):
        # Get organization
        if options['organization_id']:
            org = Organization.objects.get(id=options['organization_id'])
        else:
            org = Organization.objects.first()

        if not org:
            self.stdout.write(self.style.ERROR("No organization found"))
            return

        # Get admin user
        user = User.objects.filter(is_staff=True).first()
        if not user:
            user = User.objects.first()

        self.stdout.write(f"Creating test passwords for organization: {org.name}\n")

        # Delete old demo passwords if requested
        if options['delete_old']:
            old_passwords = Password.objects.filter(
                organization=org,
                title__in=[
                    'AWS Console',
                    'Core Switch Management',
                    'Edge Firewall Admin',
                    'prod-db-01 Database',
                    'prod-web-01 Root'
                ]
            )
            count = old_passwords.count()
            old_passwords.delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} old demo passwords\n"))

        # Test password definitions
        test_passwords = [
            # WEAK PASSWORDS (will likely be breached)
            {
                'title': 'Test - Weak Password 1',
                'username': 'admin',
                'password': 'password',
                'url': 'https://example.com',
                'password_type': 'website',
                'notes': 'WEAK: Common password "password" - should be heavily breached',
                'expected': 'BREACHED'
            },
            {
                'title': 'Test - Weak Password 2',
                'username': 'administrator',
                'password': 'password123',
                'url': 'https://test.example.com',
                'password_type': 'website',
                'notes': 'WEAK: Common password "password123" - should be breached',
                'expected': 'BREACHED'
            },
            {
                'title': 'Test - Weak Password 3',
                'username': 'root',
                'password': 'qwerty123',
                'url': 'https://server.example.com',
                'password_type': 'server',
                'notes': 'WEAK: Keyboard pattern "qwerty123" - likely breached',
                'expected': 'BREACHED'
            },
            {
                'title': 'Test - Weak Password 4',
                'username': 'user',
                'password': 'letmein',
                'url': 'https://portal.example.com',
                'password_type': 'website',
                'notes': 'WEAK: Common phrase "letmein" - should be breached',
                'expected': 'BREACHED'
            },
            {
                'title': 'Test - Weak Password 5',
                'username': 'admin',
                'password': 'Welcome123',
                'url': 'https://admin.example.com',
                'password_type': 'website',
                'notes': 'WEAK: Common corporate password "Welcome123" - likely breached',
                'expected': 'BREACHED'
            },

            # STRONG PASSWORDS (should be safe)
            {
                'title': 'Test - Strong Password 1',
                'username': 'secure_user_1',
                'password': self.generate_strong_password(24),
                'url': 'https://secure1.example.com',
                'password_type': 'website',
                'notes': 'STRONG: 24-char random password with all character types - should be safe',
                'expected': 'SAFE'
            },
            {
                'title': 'Test - Strong Password 2',
                'username': 'secure_user_2',
                'password': self.generate_strong_password(32),
                'url': 'https://secure2.example.com',
                'password_type': 'database',
                'notes': 'STRONG: 32-char random password - should be safe',
                'expected': 'SAFE'
            },
            {
                'title': 'Test - Strong Password 3',
                'username': 'secure_admin',
                'password': self.generate_strong_password(20),
                'url': 'https://secure3.example.com',
                'password_type': 'server',
                'notes': 'STRONG: 20-char random password - should be safe',
                'expected': 'SAFE'
            },
            {
                'title': 'Test - Strong Password 4',
                'username': 'api_user',
                'password': self.generate_strong_password(28),
                'url': 'https://api.example.com',
                'password_type': 'api_key',
                'notes': 'STRONG: 28-char random password - should be safe',
                'expected': 'SAFE'
            },
            {
                'title': 'Test - Strong Password 5',
                'username': 'prod_user',
                'password': self.generate_strong_password(26),
                'url': 'https://prod.example.com',
                'password_type': 'website',
                'notes': 'STRONG: 26-char random password - should be safe',
                'expected': 'SAFE'
            },
        ]

        created = 0
        checker = PasswordBreachChecker()

        for pwd_data in test_passwords:
            plaintext = pwd_data.pop('password')
            expected = pwd_data.pop('expected')

            # Create password
            password = Password(
                organization=org,
                created_by=user,
                last_modified_by=user,
                **pwd_data
            )
            password.set_password(plaintext)
            password.save()

            # Check breach status
            try:
                is_breached, count = checker.check_password(plaintext)

                if is_breached:
                    status = self.style.ERROR(f"BREACHED ({count:,} times)")
                else:
                    status = self.style.SUCCESS("SAFE")

                match = "✓" if (is_breached and expected == 'BREACHED') or (not is_breached and expected == 'SAFE') else "✗"

                self.stdout.write(
                    f"{match} Created: {pwd_data['title'][:40]:<40} | Status: {status} | Expected: {expected}"
                )

                created += 1

            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"⚠ Created: {pwd_data['title']} (breach check failed: {e})")
                )

        self.stdout.write(f"\n{self.style.SUCCESS(f'Successfully created {created} test passwords')}")
        self.stdout.write("\nTest the breach detection:")
        self.stdout.write("  1. Go to Vault → Passwords")
        self.stdout.write("  2. View security status indicators")
        self.stdout.write("  3. Click 'Test Now' on each password")
        self.stdout.write("  4. Or run: python manage.py check_password_breaches\n")

    def generate_strong_password(self, length=24):
        """Generate cryptographically strong random password."""
        alphabet = string.ascii_letters + string.digits + '!@#$%^&*()_+-=[]{}|;:,.<>?'

        # Ensure at least one of each character type
        password = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
            secrets.choice('!@#$%^&*()_+-=[]{}|;:,.<>?')
        ]

        # Fill the rest with random characters
        password.extend(secrets.choice(alphabet) for _ in range(length - 4))

        # Shuffle to avoid predictable patterns
        password_list = list(password)
        secrets.SystemRandom().shuffle(password_list)

        return ''.join(password_list)
