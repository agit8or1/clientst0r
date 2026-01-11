"""
Security scanning utilities for HuduGlue.

Provides vulnerability scanning using pip-audit and dependency checking.
"""

import subprocess
import json
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger('core')


def run_vulnerability_scan():
    """
    Run pip-audit to check for known vulnerabilities.

    Returns:
        dict: Scan results with vulnerabilities count and details
    """
    try:
        result = subprocess.run(
            ['pip-audit', '--format', 'json'],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # No vulnerabilities found
            return {
                'status': 'clean',
                'vulnerabilities': 0,
                'scan_time': datetime.now(),
                'details': []
            }
        else:
            # Parse JSON output
            try:
                data = json.loads(result.stdout)
                vulnerabilities = data.get('vulnerabilities', [])
                return {
                    'status': 'vulnerabilities_found',
                    'vulnerabilities': len(vulnerabilities),
                    'scan_time': datetime.now(),
                    'details': vulnerabilities
                }
            except json.JSONDecodeError:
                return {
                    'status': 'clean',
                    'vulnerabilities': 0,
                    'scan_time': datetime.now(),
                    'details': []
                }

    except subprocess.TimeoutExpired:
        logger.error("Vulnerability scan timed out")
        return {
            'status': 'error',
            'vulnerabilities': None,
            'scan_time': datetime.now(),
            'error': 'Scan timeout'
        }
    except Exception as e:
        logger.error(f"Vulnerability scan failed: {e}")
        return {
            'status': 'error',
            'vulnerabilities': None,
            'scan_time': datetime.now(),
            'error': str(e)
        }


def get_dependency_versions():
    """
    Get versions of critical dependencies.

    Returns:
        dict: Dictionary of package names to versions
    """
    critical_packages = [
        'Django',
        'djangorestframework',
        'gunicorn',
        'cryptography',
        'pillow',
        'requests',
        'anthropic',
        'django-two-factor-auth',
        'django-axes',
    ]

    versions = {}

    try:
        result = subprocess.run(
            ['pip', 'list', '--format', 'json'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            packages = json.loads(result.stdout)
            package_dict = {pkg['name'].lower(): pkg['version'] for pkg in packages}

            for package in critical_packages:
                # Replace hyphens with underscores for Django template compatibility
                key = package.replace('-', '_')
                versions[key] = package_dict.get(package.lower(), 'Unknown')

    except Exception as e:
        logger.error(f"Failed to get dependency versions: {e}")

    return versions
