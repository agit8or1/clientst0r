"""
Management command to detect and fix migration issues automatically.
Self-healing migration system.

Usage:
    python manage.py heal_migrations [--dry-run]
"""
import os
import subprocess
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader
import logging

logger = logging.getLogger('core')


class Command(BaseCommand):
    help = 'Detect and fix migration issues automatically (self-healing)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        self.stdout.write(
            self.style.SUCCESS('\n🔧 Client St0r Migration Self-Healing System\n')
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 DRY RUN MODE - No changes will be made\n')
            )

        fixed_count = 0

        # Step 1: Detect orphan migrations (exist locally but not in git)
        self.stdout.write('Checking for orphan migrations...')
        orphans = self.find_orphan_migrations()

        if orphans:
            self.stdout.write(
                self.style.WARNING(
                    f'\n⚠️  Found {len(orphans)} locally-generated migration(s):\n'
                )
            )
            for orphan in orphans:
                self.stdout.write(f'  - {orphan["app"]}.{orphan["name"]}')

            if not dry_run:
                self.stdout.write('\nFaking and removing orphan migrations...')
                for orphan in orphans:
                    self.fake_and_remove_migration(orphan)
                    fixed_count += 1
                self.stdout.write(self.style.SUCCESS('✅ Orphan migrations removed\n'))
            else:
                self.stdout.write('  Would fake-apply and remove these migrations\n')
        else:
            self.stdout.write(self.style.SUCCESS('✅ No orphan migrations found\n'))

        # Step 2: Check for migration conflicts
        self.stdout.write('Checking for migration conflicts...')
        conflicts = self.check_migration_conflicts()

        if conflicts:
            self.stdout.write(
                self.style.WARNING(
                    f'\n⚠️  Found migration conflicts:\n{conflicts}\n'
                )
            )
            if not dry_run:
                self.stdout.write('This requires manual resolution via git pull')
            else:
                self.stdout.write('  Would require git pull to resolve\n')
        else:
            self.stdout.write(self.style.SUCCESS('✅ No migration conflicts\n'))

        # Step 3: Check for unapplied migrations
        self.stdout.write('Checking for unapplied migrations...')
        unapplied = self.get_unapplied_migrations()

        if unapplied:
            self.stdout.write(
                self.style.WARNING(
                    f'\n⚠️  Found {len(unapplied)} unapplied migration(s)\n'
                )
            )
            for migration in unapplied:
                self.stdout.write(f'  - {migration}')

            if not dry_run:
                self.stdout.write('\nApplying migrations...')
                self.apply_migrations()
                self.stdout.write(self.style.SUCCESS('✅ Migrations applied\n'))
                fixed_count += len(unapplied)
            else:
                self.stdout.write('  Would apply these migrations\n')
        else:
            self.stdout.write(self.style.SUCCESS('✅ All migrations applied\n'))

        # Summary
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ DRY RUN COMPLETE\n\n'
                    f'Would fix: {fixed_count} issue(s)\n'
                    f'Run without --dry-run to apply fixes.\n'
                )
            )
        else:
            if fixed_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n✅ HEALING COMPLETE\n\n'
                        f'Fixed: {fixed_count} issue(s)\n'
                        f'Your migrations are now healthy!\n'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        '\n✅ ALL HEALTHY\n\nNo migration issues detected!\n'
                    )
                )

    def find_orphan_migrations(self):
        """Find migrations that exist locally but not in git repository."""
        orphans = []

        try:
            # Get list of tracked migration files in git
            result = subprocess.run(
                ['git', 'ls-tree', '-r', '--name-only', 'HEAD'],
                capture_output=True,
                text=True,
                check=True
            )
            git_files = set(result.stdout.strip().split('\n'))

            # Check each app's migrations directory
            for app_config in settings.INSTALLED_APPS:
                if app_config.startswith('django.'):
                    continue

                try:
                    app_name = app_config.split('.')[-1]
                    migrations_dir = os.path.join(settings.BASE_DIR, app_name, 'migrations')

                    if not os.path.exists(migrations_dir):
                        continue

                    # Check each migration file
                    for filename in os.listdir(migrations_dir):
                        if filename.startswith('0') and filename.endswith('.py'):
                            relative_path = os.path.join(app_name, 'migrations', filename)

                            # If file exists locally but not in git, it's an orphan
                            if relative_path not in git_files:
                                migration_name = filename.replace('.py', '')
                                orphans.append({
                                    'app': app_name,
                                    'name': migration_name,
                                    'file': os.path.join(migrations_dir, filename)
                                })

                except Exception as e:
                    logger.warning(f"Error checking {app_name} migrations: {e}")

        except subprocess.CalledProcessError:
            logger.error("Git command failed - are you in a git repository?")

        return orphans

    def fake_and_remove_migration(self, orphan):
        """Fake-apply and remove an orphan migration."""
        try:
            # Try to fake-apply the migration
            subprocess.run(
                ['python', 'manage.py', 'migrate', '--fake', orphan['app'], orphan['name']],
                capture_output=True,
                check=False  # Don't fail if migration doesn't exist in DB
            )

            # Remove the file
            if os.path.exists(orphan['file']):
                os.remove(orphan['file'])
                logger.info(f"Removed orphan migration: {orphan['app']}.{orphan['name']}")

        except Exception as e:
            logger.error(f"Error removing orphan migration {orphan['name']}: {e}")

    def check_migration_conflicts(self):
        """Check for migration conflicts."""
        try:
            loader = MigrationLoader(connection)
            conflicts = loader.detect_conflicts()

            if conflicts:
                conflict_messages = []
                for app_label, migration_names in conflicts.items():
                    conflict_messages.append(
                        f"  {app_label}: {', '.join(migration_names)}"
                    )
                return '\n'.join(conflict_messages)

        except Exception as e:
            logger.error(f"Error checking for conflicts: {e}")

        return None

    def get_unapplied_migrations(self):
        """Get list of unapplied migrations."""
        try:
            loader = MigrationLoader(connection)
            graph = loader.graph
            plan = []

            # Get all unapplied migrations
            for app_label, migration_name in graph.leaf_nodes():
                if (app_label, migration_name) not in loader.applied_migrations:
                    plan.append(f"{app_label}.{migration_name}")

            return plan

        except Exception as e:
            logger.error(f"Error getting unapplied migrations: {e}")
            return []

    def apply_migrations(self):
        """Apply pending migrations."""
        try:
            subprocess.run(
                ['python', 'manage.py', 'migrate'],
                check=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Error applying migrations: {e}")
            raise
