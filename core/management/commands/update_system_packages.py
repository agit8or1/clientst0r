"""
Management command to update system packages.
OPTIONAL: Only runs when explicitly called. Supports apt, yum/dnf, and pacman.
Can update all packages, security-only, or specific packages.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import re
import subprocess
from pathlib import Path

# Debian/RPM/Arch package names (optionally with an :arch suffix). Must start
# with an alphanumeric, so a value can never be read as a command-line option
# (e.g. `-oDPkg::Pre-Invoke=...`) by the package manager running under sudo.
PACKAGE_NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9.+_-]*(:[a-z0-9_-]+)?')


def parse_package_list(value):
    """Split a comma-separated package list, rejecting anything that isn't a package name."""
    names = [name.strip() for name in (value or '').split(',') if name.strip()]
    bad = [name for name in names if not PACKAGE_NAME.fullmatch(name)]
    if bad:
        raise CommandError(f'Invalid package name(s): {", ".join(bad)}')
    return names


class Command(BaseCommand):
    help = 'Update system packages (optional - must be explicitly run)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--security-only',
            action='store_true',
            help='Only install security updates'
        )
        parser.add_argument(
            '--package',
            type=str,
            help='Update specific package(s) - comma separated'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating'
        )
        parser.add_argument(
            '--auto-approve',
            action='store_true',
            help='Automatically approve updates without prompting'
        )

    def handle(self, *args, **options):
        self.security_only = options['security_only']
        self.packages = parse_package_list(options['package'])
        self.dry_run = options['dry_run']
        self.auto_approve = options['auto_approve']

        self.stdout.write(self.style.SUCCESS('System Package Updater'))
        self.stdout.write('=' * 70)

        if self.dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
            self.stdout.write('')

        # Detect package manager
        pkg_manager = self.detect_package_manager()
        if not pkg_manager:
            self.stdout.write(self.style.ERROR('No supported package manager found'))
            return

        self.stdout.write(f'Detected package manager: {pkg_manager}')
        self.stdout.write('')

        # Confirm before proceeding (unless auto-approve)
        if not self.auto_approve and not self.dry_run:
            if self.security_only:
                self.stdout.write(self.style.WARNING('This will install SECURITY updates only.'))
            elif self.packages:
                self.stdout.write(self.style.WARNING(f'This will update: {", ".join(self.packages)}'))
            else:
                self.stdout.write(self.style.WARNING('This will update ALL packages on the system.'))

            response = input('Continue? [y/N]: ')
            if response.lower() != 'y':
                self.stdout.write('Update cancelled.')
                return

        # Perform update
        success = self.update_packages(pkg_manager)

        if success:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ Update complete'))

            # Save update log
            self.log_update(pkg_manager)
        else:
            self.stdout.write(self.style.ERROR('✗ Update failed'))

    def detect_package_manager(self):
        """Detect which package manager is available"""
        managers = {
            'apt': '/usr/bin/apt',
            'apt-get': '/usr/bin/apt-get',
            'dnf': '/usr/bin/dnf',
            'yum': '/usr/bin/yum',
            'pacman': '/usr/bin/pacman',
        }

        for name, path in managers.items():
            if Path(path).exists():
                return name

        return None

    def update_packages(self, pkg_manager):
        """Update packages based on package manager"""
        if pkg_manager in ['apt', 'apt-get']:
            return self.update_apt()
        elif pkg_manager in ['dnf', 'yum']:
            return self.update_dnf_yum(pkg_manager)
        elif pkg_manager == 'pacman':
            return self.update_pacman()

        return False

    def update_apt(self):
        """Update Debian/Ubuntu packages"""
        import os
        apt_env = os.environ.copy()
        apt_env['DEBIAN_FRONTEND'] = 'noninteractive'
        apt_env['DEBCONF_NONINTERACTIVE_SEEN'] = 'true'
        apt_env['DEBCONF_FRONTEND'] = 'noninteractive'

        try:
            # Update package cache
            self.stdout.write('Updating package cache...')
            result = subprocess.run(
                ['sudo', '-n', 'apt-get', '-q', 'update'],
                capture_output=True,
                text=True,
                timeout=120,
                env=apt_env,
                stdin=subprocess.DEVNULL,
            )

            if result.returncode != 0:
                self.stdout.write(self.style.ERROR(f'Failed to update cache: {result.stderr}'))
                # Non-fatal — continue with potentially stale cache
                self.stdout.write(self.style.WARNING('Continuing with existing cache...'))

            # Build update command
            if self.dry_run:
                cmd = ['apt-get', '--dry-run']
            else:
                cmd = ['sudo', '-n', 'apt-get', '-y', '-o', 'Dpkg::Options::=--force-confdef',
                       '-o', 'Dpkg::Options::=--force-confold']

            if self.security_only:
                # Install only security updates
                cmd.extend(['install', '--only-upgrade'])
                # Get security packages
                list_result = subprocess.run(
                    ['apt', 'list', '--upgradeable'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                security_packages = []
                for line in list_result.stdout.splitlines():
                    if 'security' in line.lower() and '/' in line:
                        pkg_name = line.split('/')[0]
                        security_packages.append(pkg_name)

                if not security_packages:
                    self.stdout.write(self.style.SUCCESS('No security updates available'))
                    return True

                cmd.extend(security_packages)
                self.stdout.write(f'Installing {len(security_packages)} security updates...')

            elif self.packages:
                # Update specific packages
                cmd.extend(['install', '--only-upgrade'] + self.packages)
                self.stdout.write(f'Updating {len(self.packages)} package(s)...')

            else:
                # Update all packages
                cmd.extend(['upgrade'])
                self.stdout.write('Updating all packages...')

            # Execute update
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                env=apt_env,
                stdin=subprocess.DEVNULL,
            )

            if self.dry_run:
                self.stdout.write(result.stdout)
                return True

            if result.stdout:
                self.stdout.write(result.stdout)
            if result.stderr:
                self.stdout.write(result.stderr)

            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS('Packages updated successfully'))
                return True
            else:
                self.stdout.write(self.style.ERROR(f'Update failed (exit {result.returncode}): {result.stderr}'))
                return False

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Update timed out after 10 minutes'))
            return False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error updating packages: {e}'))
            return False

    def update_dnf_yum(self, pkg_manager):
        """Update RedHat/CentOS packages"""
        try:
            # Build update command
            if self.dry_run:
                cmd = [pkg_manager, 'check-update']
            else:
                cmd = ['sudo', pkg_manager, '-y']

            if self.security_only:
                cmd.extend(['update', '--security'])
                self.stdout.write('Installing security updates...')
            elif self.packages:
                cmd.extend(['update'] + self.packages)
                self.stdout.write(f'Updating {len(self.packages)} package(s)...')
            else:
                cmd.append('update')
                self.stdout.write('Updating all packages...')

            # Execute update
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if self.dry_run:
                self.stdout.write(result.stdout)
                return True

            # dnf/yum returns 100 for available updates, 0 for success
            if result.returncode in [0, 100]:
                self.stdout.write(self.style.SUCCESS('Packages updated successfully'))
                return True
            else:
                self.stdout.write(self.style.ERROR(f'Update failed: {result.stderr}'))
                return False

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Update timed out'))
            return False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error updating packages: {e}'))
            return False

    def update_pacman(self):
        """Update Arch Linux packages"""
        try:
            # Build update command
            if self.dry_run:
                cmd = ['pacman', '-Qu']
                self.stdout.write('Available updates:')
            else:
                cmd = ['sudo', 'pacman', '-Syu', '--noconfirm']

                if self.packages:
                    cmd = ['sudo', 'pacman', '-S', '--noconfirm'] + self.packages
                    self.stdout.write(f'Updating {len(self.packages)} package(s)...')
                else:
                    self.stdout.write('Updating all packages...')

            # Execute update
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )

            if self.dry_run:
                self.stdout.write(result.stdout)
                return True

            if result.returncode == 0:
                self.stdout.write(self.style.SUCCESS('Packages updated successfully'))
                return True
            else:
                self.stdout.write(self.style.ERROR(f'Update failed: {result.stderr}'))
                return False

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Update timed out'))
            return False
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error updating packages: {e}'))
            return False

    def log_update(self, pkg_manager):
        """Log the update to database"""
        from core.models import SystemPackageScan

        # Create a log entry for the update
        SystemPackageScan.objects.create(
            package_manager=pkg_manager,
            total_packages=0,
            upgradeable_packages=0,
            security_updates=0,
            scan_data={
                'action': 'update',
                'security_only': self.security_only,
                'packages': self.packages,
                'timestamp': timezone.now().isoformat(),
            }
        )
