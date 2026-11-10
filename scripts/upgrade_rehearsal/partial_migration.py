"""Leave one new migration half applied, the way a crash leaves it on
MySQL/MariaDB (issues #128, #129): run only the first SQL statement of a
migration the target revision adds, against the rehearsal database, without
recording the migration.

    python partial_migration.py NEW_CODE_DIR APP_DIR app/migrations/0077_x.py [...]

NEW_CODE_DIR is a checkout of the target revision (used only for
`sqlmigrate`), APP_DIR the install still running the old code. The first
candidate whose first statement creates a table or adds a column is used;
its label is printed on the last line. Disposable rehearsal data only.
"""
import os
import re
import subprocess
import sys

new_code, app_dir, candidates = sys.argv[1], sys.argv[2], sys.argv[3:]
py = sys.executable

# Only the first new migration of each app: the doctor examines exactly that one.
first_per_app = {}
for path in sorted(candidates):
    app = path.split('/')[0]
    first_per_app.setdefault(app, path)

GOOD = re.compile(r'^(CREATE TABLE (?![`"]new__)|ALTER TABLE \S+ ADD (COLUMN )?)', re.I)

for path in sorted(first_per_app.values()):
    app, name = path.split('/')[0], os.path.basename(path)[:-3]
    r = subprocess.run([py, 'manage.py', 'sqlmigrate', app, name], cwd=new_code,
                       capture_output=True, text=True)
    if r.returncode != 0:
        continue
    lines = [ln for ln in r.stdout.splitlines()
             if ln.strip() and not ln.startswith('--') and ln.strip() not in ('BEGIN;', 'COMMIT;')]
    statements = [s.strip() for s in '\n'.join(lines).split(';\n') if s.strip()]
    if len(statements) < 2 or not GOOD.match(statements[0]):
        continue
    stmt = statements[0].rstrip(';')
    code = ("import os, sys, django\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
            "django.setup()\n"
            "from django.db import connection\n"
            "with connection.cursor() as c:\n"
            "    c.execute(sys.stdin.read())\n")
    r = subprocess.run([py, '-c', code], cwd=app_dir, input=stmt, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'applying the first statement of {app}.{name} failed: {r.stderr[-800:]}')
    print(f'applied only: {stmt[:120]}')
    print(f'{app}.{name}')
    sys.exit(0)
sys.exit('no new migration starts with CREATE TABLE / ADD COLUMN and has more statements')
