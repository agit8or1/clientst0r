"""
Management command to scan system packages for vulnerabilities and updates.
Supports apt (Debian/Ubuntu), yum/dnf (RedHat/CentOS), and pacman (Arch).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
import subprocess
import json
import re
from pathlib import Path


class Command(BaseCommand):
    help = 'Scan system packages for security updates and vulnerabilities'

    def add_arguments(self, parser):
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output results in JSON format'
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='Save results to database'
        )

    def handle(self, *args, **options):
        self.json_output = options['json']
        self.save_db = options['save']

        if not self.json_output:
            self.stdout.write(self.style.SUCCESS('System Package Security Scanner'))
            self.stdout.write('=' * 70)

        # Detect package manager
        pkg_manager = self.detect_package_manager()
        if not pkg_manager:
            self.stdout.write(self.style.ERROR('No supported package manager found'))
            return

        if not self.json_output:
            self.stdout.write(f'Detected package manager: {pkg_manager}')
            self.stdout.write('')

        # Scan packages
        scan_data = self.scan_packages(pkg_manager)

        # Output results
        if self.json_output:
            self.stdout.write(json.dumps(scan_data, indent=2))
        else:
            self.print_results(scan_data)

        # Save to database
        if self.save_db:
            self.save_scan_results(scan_data)

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

    def scan_packages(self, pkg_manager):
        """Scan packages based on package manager"""
        if pkg_manager in ['apt', 'apt-get']:
            return self.scan_apt()
        elif pkg_manager in ['dnf', 'yum']:
            return self.scan_dnf_yum(pkg_manager)
        elif pkg_manager == 'pacman':
            return self.scan_pacman()

        return {}

    def scan_apt(self):
        """Scan Debian/Ubuntu packages"""
        scan_data = {
            'package_manager': 'apt',
            'scan_date': timezone.now().isoformat(),
            'total_packages': 0,
            'upgradeable': 0,
            'security_updates': 0,
            'packages': [],
            'security_packages': [],
        }

        try:
            # Update package cache
            subprocess.run(
                ['sudo', 'apt-get', 'update'],
                capture_output=True,
                timeout=60
            )

            # Get list of upgradeable packages
            result = subprocess.run(
                ['apt', 'list', '--upgradeable'],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse upgradeable packages
            upgradeable = []
            for line in result.stdout.splitlines():
                if '/' in line and 'upgradable' in line.lower():
                    match = re.match(r'([^/]+)/([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+\[upgradable from: ([^\]]+)\]', line)
                    if match:
                        upgradeable.append({
                            'name': match.group(1),
                            'repo': match.group(2),
                            'new_version': match.group(3),
                            'arch': match.group(4),
                            'current_version': match.group(5),
                        })

            scan_data['upgradeable'] = len(upgradeable)
            scan_data['packages'] = upgradeable

            # Check for security updates specifically
            unattended_upgrades_file = Path('/var/log/unattended-upgrades/unattended-upgrades.log')
            if unattended_upgrades_file.exists():
                # Try to get security updates from Ubuntu Security
                result = subprocess.run(
                    ['apt', 'list', '--upgradeable'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                security_packages = []
                for pkg in upgradeable:
                    # Check if package is from security repo
                    if '-security' in pkg.get('repo', '') or 'security' in pkg.get('repo', '').lower():
                        security_packages.append(pkg)

                scan_data['security_updates'] = len(security_packages)
                scan_data['security_packages'] = security_packages

            # Get total installed packages
            result = subprocess.run(
                ['dpkg', '-l'],
                capture_output=True,
                text=True,
                timeout=30
            )
            scan_data['total_packages'] = len([l for l in result.stdout.splitlines() if l.startswith('ii')])

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Package scan timed out'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error scanning apt packages: {e}'))

        return scan_data

    def scan_dnf_yum(self, pkg_manager):
        """Scan RedHat/CentOS packages"""
        scan_data = {
            'package_manager': pkg_manager,
            'scan_date': timezone.now().isoformat(),
            'total_packages': 0,
            'upgradeable': 0,
            'security_updates': 0,
            'packages': [],
            'security_packages': [],
        }

        try:
            # Check for updates
            result = subprocess.run(
                [pkg_manager, 'check-update'],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Parse updates (yum/dnf exit code 100 means updates available)
            if result.returncode == 100 or result.stdout:
                upgradeable = []
                for line in result.stdout.splitlines():
                    if line.strip() and not line.startswith(('Loaded', 'Last', 'Security', 'Updates')):
                        parts = line.split()
                        if len(parts) >= 3:
                            upgradeable.append({
                                'name': parts[0],
                                'new_version': parts[1],
                                'repo': parts[2] if len(parts) > 2 else '',
                            })

                scan_data['upgradeable'] = len(upgradeable)
                scan_data['packages'] = upgradeable

            # Check for security updates
            result = subprocess.run(
                [pkg_manager, 'updateinfo', 'list', 'security'],
                capture_output=True,
                text=True,
                timeout=30
            )

            security_packages = []
            for line in result.stdout.splitlines():
                if '/' in line and any(word in line.lower() for word in ['security', 'cve']):
                    parts = line.split()
                    if len(parts) >= 2:
                        security_packages.append({
                            'advisory': parts[0],
                            'package': parts[2] if len(parts) > 2 else parts[1],
                        })

            scan_data['security_updates'] = len(security_packages)
            scan_data['security_packages'] = security_packages

            # Get total installed packages
            result = subprocess.run(
                ['rpm', '-qa'],
                capture_output=True,
                text=True,
                timeout=30
            )
            scan_data['total_packages'] = len(result.stdout.splitlines())

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Package scan timed out'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error scanning {pkg_manager} packages: {e}'))

        return scan_data

    def scan_pacman(self):
        """Scan Arch Linux packages"""
        scan_data = {
            'package_manager': 'pacman',
            'scan_date': timezone.now().isoformat(),
            'total_packages': 0,
            'upgradeable': 0,
            'security_updates': 0,
            'packages': [],
            'security_packages': [],
        }

        try:
            # Update package database
            subprocess.run(
                ['sudo', 'pacman', '-Sy'],
                capture_output=True,
                timeout=60
            )

            # Check for updates
            result = subprocess.run(
                ['pacman', '-Qu'],
                capture_output=True,
                text=True,
                timeout=30
            )

            upgradeable = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    upgradeable.append({
                        'name': parts[0],
                        'current_version': parts[1],
                        'new_version': parts[3],
                    })

            scan_data['upgradeable'] = len(upgradeable)
            scan_data['packages'] = upgradeable

            # Get total installed packages
            result = subprocess.run(
                ['pacman', '-Q'],
                capture_output=True,
                text=True,
                timeout=30
            )
            scan_data['total_packages'] = len(result.stdout.splitlines())

        except subprocess.TimeoutExpired:
            self.stdout.write(self.style.ERROR('Package scan timed out'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error scanning pacman packages: {e}'))

        return scan_data

    def print_results(self, scan_data):
        """Print scan results in human-readable format"""
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Scan Results:'))
        self.stdout.write(f"Total Packages: {scan_data['total_packages']}")
        self.stdout.write(f"Upgradeable: {scan_data['upgradeable']}")
        self.stdout.write(f"Security Updates: {scan_data['security_updates']}")

        if scan_data['security_updates'] > 0:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Security Updates Available:'))
            self.stdout.write('-' * 70)
            for pkg in scan_data['security_packages'][:10]:
                if 'name' in pkg:
                    self.stdout.write(f"  • {pkg['name']}: {pkg.get('current_version', '?')} → {pkg.get('new_version', '?')}")
                elif 'package' in pkg:
                    self.stdout.write(f"  • {pkg['advisory']}: {pkg['package']}")

            if len(scan_data['security_packages']) > 10:
                self.stdout.write(f"  ... and {len(scan_data['security_packages']) - 10} more")

        if scan_data['upgradeable'] > scan_data['security_updates']:
            other_updates = scan_data['upgradeable'] - scan_data['security_updates']
            self.stdout.write('')
            self.stdout.write(f"Other Updates: {other_updates}")

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('✓ Scan complete'))

    def save_scan_results(self, scan_data):
        """Save scan results to database"""
        from core.models import SystemPackageScan

        SystemPackageScan.objects.create(
            scan_date=timezone.now(),
            package_manager=scan_data['package_manager'],
            total_packages=scan_data['total_packages'],
            upgradeable_packages=scan_data['upgradeable'],
            security_updates=scan_data['security_updates'],
            scan_data=scan_data,
        )

        self.stdout.write(self.style.SUCCESS('Scan results saved to database'))
