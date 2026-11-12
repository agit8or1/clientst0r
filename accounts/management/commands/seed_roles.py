"""Create / upgrade the built-in roles (accounts.role_seeds). Customized
built-in roles are never overwritten; they are listed for review instead."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed the built-in internal and customer roles idempotently.'

    def handle(self, *args, **opts):
        from accounts.models import RoleTemplate
        from accounts.role_seeds import seed_builtin_roles
        summary = seed_builtin_roles(RoleTemplate, source='seed_roles')
        for key, names in summary.items():
            if names:
                self.stdout.write(f'{key}: {", ".join(names)}')
        self.stdout.write(self.style.SUCCESS('Built-in roles are up to date.'))
