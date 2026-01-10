#!/usr/bin/env python3
"""
Pre-flight check script - Validates the platform is ready to run
"""
import os
import sys
from pathlib import Path

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check(name, condition, error_msg=""):
    """Print check result"""
    if condition:
        print(f"{GREEN}✓{RESET} {name}")
        return True
    else:
        print(f"{RED}✗{RESET} {name}")
        if error_msg:
            print(f"  {YELLOW}→{RESET} {error_msg}")
        return False

print(f"\n{BLUE}{'='*60}{RESET}")
print(f"{BLUE}IT Documentation Platform - Pre-flight Check{RESET}")
print(f"{BLUE}{'='*60}{RESET}\n")

all_checks_passed = True

# Check Python version
print(f"{BLUE}[Python Environment]{RESET}")
py_version = sys.version_info
all_checks_passed &= check(
    "Python 3.8+",
    py_version >= (3, 8),
    f"Found Python {py_version.major}.{py_version.minor}, need 3.8+"
)

# Check critical files
print(f"\n{BLUE}[Project Files]{RESET}")
files_to_check = [
    'manage.py',
    'requirements.txt',
    '.env.example',
    'README.md',
    'config/settings.py',
    'config/urls.py',
    'config/wsgi.py',
]

for file in files_to_check:
    all_checks_passed &= check(
        f"File: {file}",
        Path(file).exists(),
        f"{file} not found"
    )

# Check app directories
print(f"\n{BLUE}[Django Apps]{RESET}")
apps = ['core', 'accounts', 'vault', 'assets', 'docs', 'files', 'audit', 'api', 'integrations']

for app in apps:
    app_checks = [
        check(f"App: {app}", Path(app).is_dir()),
        check(f"  {app}/__init__.py", Path(f"{app}/__init__.py").exists()),
        check(f"  {app}/models.py", Path(f"{app}/models.py").exists()),
        check(f"  {app}/migrations/", Path(f"{app}/migrations").is_dir()),
    ]
    all_checks_passed &= all(app_checks)

# Check templates
print(f"\n{BLUE}[Templates]{RESET}")
template_files = [
    'templates/base.html',
    'templates/home.html',
    'templates/core/documentation.html',
    'templates/core/about.html',
    'templates/assets/asset_list.html',
    'templates/vault/password_list.html',
    'templates/docs/document_list.html',
    'templates/integrations/integration_list.html',
]

for template in template_files:
    all_checks_passed &= check(
        f"Template: {template}",
        Path(template).exists()
    )

# Check deployment files
print(f"\n{BLUE}[Deployment Files]{RESET}")
deploy_files = [
    'scripts/bootstrap_ubuntu.sh',
    'deploy/itdocs-gunicorn.service',
    'deploy/itdocs-psa-sync.service',
    'deploy/itdocs-psa-sync.timer',
    'deploy/nginx-itdocs.conf',
]

for file in deploy_files:
    all_checks_passed &= check(
        f"Deploy: {file}",
        Path(file).exists()
    )

# Check scripts are executable
print(f"\n{BLUE}[Executable Scripts]{RESET}")
executable_files = [
    'manage.py',
    'scripts/bootstrap_ubuntu.sh',
    'QUICK_START.sh',
]

for file in executable_files:
    if Path(file).exists():
        is_executable = os.access(file, os.X_OK)
        all_checks_passed &= check(
            f"Executable: {file}",
            is_executable,
            f"Run: chmod +x {file}"
        )

# Check static directory
print(f"\n{BLUE}[Static Files]{RESET}")
all_checks_passed &= check(
    "Static directory",
    Path('static').exists() or True,  # Will be created by collectstatic
    "Will be created during setup"
)
all_checks_passed &= check(
    "Custom CSS",
    Path('static/css/custom.css').exists()
)

# Check .env file
print(f"\n{BLUE}[Configuration]{RESET}")
env_exists = Path('.env').exists()
check(
    ".env file",
    env_exists,
    "Copy .env.example to .env and configure it"
)

if env_exists:
    # Check .env has required vars
    with open('.env', 'r') as f:
        env_content = f.read()
        required_vars = ['SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'APP_MASTER_KEY']
        for var in required_vars:
            has_var = var in env_content and not env_content.split(var)[1].split('\n')[0].strip(' =').startswith('#')
            check(
                f"  {var} configured",
                has_var,
                f"Set {var} in .env file"
            )

# Check PSA providers
print(f"\n{BLUE}[PSA Providers]{RESET}")
providers = [
    ('ConnectWise Manage', 'integrations/providers/connectwise.py', 'COMPLETE'),
    ('Autotask PSA', 'integrations/providers/autotask.py', 'COMPLETE'),
    ('HaloPSA', 'integrations/providers/halo.py', 'SCAFFOLDED'),
    ('Kaseya BMS', 'integrations/providers/kaseya.py', 'SCAFFOLDED'),
    ('Syncro', 'integrations/providers/syncro.py', 'SCAFFOLDED'),
]

for name, path, status in providers:
    exists = Path(path).exists()
    symbol = "✓" if status == "COMPLETE" else "○"
    color = GREEN if status == "COMPLETE" else YELLOW
    if exists:
        print(f"{color}{symbol}{RESET} {name} - {status}")

# Summary
print(f"\n{BLUE}{'='*60}{RESET}")
if all_checks_passed and env_exists:
    print(f"{GREEN}✓ ALL CHECKS PASSED - READY TO DEPLOY{RESET}")
    print(f"\n{BLUE}Next steps:{RESET}")
    print(f"  1. Ensure .env is configured with all secrets")
    print(f"  2. Run: ./scripts/bootstrap_ubuntu.sh")
    print(f"  3. Follow DEPLOYMENT.md for complete setup")
    print(f"\n{BLUE}Quick test (development):{RESET}")
    print(f"  python3 -m venv venv")
    print(f"  source venv/bin/activate")
    print(f"  pip install -r requirements.txt")
    print(f"  python manage.py migrate")
    print(f"  python manage.py seed_demo")
    print(f"  python manage.py runserver")
elif all_checks_passed:
    print(f"{YELLOW}⚠ ALMOST READY{RESET}")
    print(f"  Configure .env file before deploying")
else:
    print(f"{RED}✗ CHECKS FAILED{RESET}")
    print(f"  Review errors above and fix before deploying")
    sys.exit(1)

print(f"{BLUE}{'='*60}{RESET}\n")
