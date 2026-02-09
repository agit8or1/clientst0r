"""
Management command to run Snyk security scan.
"""
import subprocess
import json
import uuid
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import SnykScan, SystemSetting


class Command(BaseCommand):
    help = 'Run Snyk security scan'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scan-id',
            type=str,
            help='Custom scan ID (auto-generated if not provided)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID who triggered the scan',
        )

    def handle(self, *args, **options):
        from django.contrib.auth.models import User
        
        # Get Snyk settings
        settings = SystemSetting.get_settings()
        
        if not settings.snyk_enabled:
            self.stdout.write(self.style.ERROR('Snyk scanning is not enabled'))
            return
        
        if not settings.snyk_api_token:
            self.stdout.write(self.style.ERROR('Snyk API token is not configured'))
            return
        
        # Create scan record
        scan_id = options.get('scan_id') or f"scan-{uuid.uuid4().hex[:8]}"
        user_id = options.get('user_id')
        triggered_by = None
        
        if user_id:
            try:
                triggered_by = User.objects.get(id=user_id)
            except User.DoesNotExist:
                pass
        
        scan = SnykScan.objects.create(
            scan_id=scan_id,
            status='running',
            severity_threshold=settings.snyk_severity_threshold,
            triggered_by=triggered_by,
        )
        
        self.stdout.write(f'Starting Snyk scan {scan_id}...')

        start_time = timezone.now()

        try:
            # Check if cancellation was requested before starting
            scan.refresh_from_db()
            if scan.cancel_requested:
                scan.status = 'cancelled'
                scan.completed_at = timezone.now()
                scan.error_message = 'Scan cancelled by user before execution'
                scan.save()
                self.stdout.write(self.style.WARNING('Scan cancelled before execution'))
                return

            # Find snyk binary (check multiple locations)
            import os
            import shutil

            snyk_path = None

            # Check common locations in order of preference
            possible_paths = [
                '/usr/local/bin/snyk',  # System-wide symlink (created by install.sh)
                shutil.which('snyk'),   # In PATH
            ]

            # Add NVM path
            nvm_node_path = os.path.expanduser('~/.nvm/versions/node')
            if os.path.exists(nvm_node_path):
                node_versions = sorted([d for d in os.listdir(nvm_node_path) if d.startswith('v')])
                if node_versions:
                    possible_paths.append(os.path.join(nvm_node_path, node_versions[-1], 'bin', 'snyk'))

            # Find first existing path
            for path in possible_paths:
                if path and os.path.exists(path):
                    snyk_path = path
                    break

            if not snyk_path:
                raise FileNotFoundError('Snyk CLI is not installed. Install with: npm install -g snyk')

            # Run Snyk test command (Open Source dependency scanning)
            cmd = [
                snyk_path,
                'test',
                '--json',
                f'--severity-threshold={settings.snyk_severity_threshold}',
            ]

            # Add organization if configured
            if settings.snyk_org_id:
                cmd.append(f'--org={settings.snyk_org_id}')

            # Set environment variables
            env = os.environ.copy()
            env['SNYK_TOKEN'] = settings.snyk_api_token

            # Add nvm node bin to PATH if it exists
            if '/.nvm/' in snyk_path:
                node_bin = os.path.dirname(snyk_path)
                env['PATH'] = f"{node_bin}:{env.get('PATH', '')}"

            # Get project directory dynamically
            from django.conf import settings as django_settings
            project_dir = str(django_settings.BASE_DIR)

            result = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=env
            )
            
            # Parse JSON output
            try:
                output_data = json.loads(result.stdout) if result.stdout else {}
            except json.JSONDecodeError:
                output_data = {}
            
            # Calculate duration
            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()
            
            # Extract vulnerability counts
            vulnerabilities = output_data.get('vulnerabilities', [])
            severity_counts = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
            
            for vuln in vulnerabilities:
                severity = vuln.get('severity', '').lower()
                if severity in severity_counts:
                    severity_counts[severity] += 1
            
            # Update scan record
            scan.status = 'completed'
            scan.completed_at = end_time
            scan.duration_seconds = int(duration)
            scan.total_vulnerabilities = len(vulnerabilities)
            scan.critical_count = severity_counts['critical']
            scan.high_count = severity_counts['high']
            scan.medium_count = severity_counts['medium']
            scan.low_count = severity_counts['low']
            scan.scan_output = result.stdout[:10000]  # Store first 10k chars
            scan.vulnerabilities = output_data
            scan.save()

            # Compare with previous scan and update tracking
            scan.update_vulnerability_tracking()

            # Update last scan time in settings
            settings.snyk_last_scan = end_time
            settings.save()

            # Display results with new/recurring breakdown
            if scan.new_vulnerabilities_count > 0 or scan.recurring_vulnerabilities_count > 0:
                self.stdout.write(self.style.SUCCESS(
                    f'Scan completed: {scan.total_vulnerabilities} vulnerabilities found '
                    f'(Critical: {scan.critical_count}, High: {scan.high_count}, '
                    f'Medium: {scan.medium_count}, Low: {scan.low_count})'
                ))
                self.stdout.write(
                    f'  • New: {scan.new_vulnerabilities_count}'
                )
                self.stdout.write(
                    f'  • Recurring: {scan.recurring_vulnerabilities_count}'
                )
                if scan.resolved_vulnerabilities_count > 0:
                    self.stdout.write(self.style.SUCCESS(
                        f'  • Resolved: {scan.resolved_vulnerabilities_count}'
                    ))
            else:
                self.stdout.write(self.style.SUCCESS('Scan completed: No vulnerabilities found'))

            if scan.has_critical_issues():
                if scan.new_vulnerabilities_count > 0:
                    self.stdout.write(self.style.WARNING(
                        'WARNING: New critical or high severity vulnerabilities detected!'
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        'WARNING: Recurring critical or high severity vulnerabilities still present!'
                    ))
            
        except subprocess.TimeoutExpired:
            scan.status = 'timeout'
            scan.error_message = 'Scan timed out after 5 minutes'
            scan.completed_at = timezone.now()
            duration = (timezone.now() - start_time).total_seconds()
            scan.duration_seconds = int(duration)
            scan.save()
            self.stdout.write(self.style.ERROR('Scan timed out after 5 minutes'))
            
        except Exception as e:
            scan.status = 'failed'
            scan.error_message = str(e)
            scan.completed_at = timezone.now()
            scan.save()
            self.stdout.write(self.style.ERROR(f'Scan failed: {e}'))
