"""
Management command to check for system updates.
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from core.updater import UpdateService
import json


class Command(BaseCommand):
    help = 'Check for Client St0r updates from GitHub'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Automatically apply updates if available'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update check (ignore cache)'
        )

    def handle(self, *args, **options):
        updater = UpdateService()

        # Check cache first (unless force flag)
        cache_key = 'system_update_check'
        if not options['force']:
            cached_result = cache.get(cache_key)
            if cached_result:
                self.stdout.write(
                    self.style.SUCCESS('Using cached update check result')
                )
                result = cached_result
            else:
                result = updater.check_for_updates()
                # Cache for 1 hour
                cache.set(cache_key, result, 3600)
        else:
            result = updater.check_for_updates()
            cache.set(cache_key, result, 3600)

        # Display results
        self.stdout.write(f"Current version: {result['current_version']}")
        self.stdout.write(f"Latest version:  {result.get('latest_version', 'Unknown')}")

        if result.get('error'):
            self.stdout.write(
                self.style.ERROR(f"Error checking for updates: {result['error']}")
            )
            return

        if result['update_available']:
            self.stdout.write(
                self.style.WARNING(
                    f"\nUpdate available: v{result['latest_version']}"
                )
            )
            self.stdout.write(f"Release URL: {result.get('release_url', 'N/A')}")
            self.stdout.write("\nRelease Notes:")
            self.stdout.write("-" * 60)
            self.stdout.write(result.get('release_notes', 'No release notes'))
            self.stdout.write("-" * 60)

            # Apply update if --apply flag is set
            if options['apply']:
                self.stdout.write(
                    self.style.WARNING('\nApplying update...')
                )
                update_result = updater.perform_update()

                if update_result['success']:
                    self.stdout.write(
                        self.style.SUCCESS('\nUpdate completed successfully!')
                    )
                    self.stdout.write('\nSteps completed:')
                    for step in update_result['steps_completed']:
                        self.stdout.write(f"  ✓ {step}")
                else:
                    self.stdout.write(
                        self.style.ERROR('\nUpdate failed!')
                    )
                    self.stdout.write(f"Error: {update_result.get('error')}")

                # Show output
                self.stdout.write('\nUpdate output:')
                for line in update_result['output']:
                    self.stdout.write(f"  {line}")

        else:
            self.stdout.write(
                self.style.SUCCESS('\nSystem is up to date!')
            )
