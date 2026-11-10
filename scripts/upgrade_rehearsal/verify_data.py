"""Check, from inside the install, that everything seed.py created is still
there and usable. Exits non-zero on the first broken expectation.

    REHEARSAL_STATE=/path/state.json python manage.py shell -c "exec(open('scripts/upgrade_rehearsal/verify_data.py').read())"

Checks: organizations and memberships, 2FA devices, every vault entry
decrypts to the value it was created with (password, TOTP secret, secure
notes where present), every uploaded file is on disk with the same bytes,
tickets / assets / documents are intact and tenant-scoped, and one
scheduler tick runs the due task.
"""
import hashlib
import json
import os
import sys

from django.core.management import call_command
from django.utils import timezone

state = json.load(open(os.environ['REHEARSAL_STATE']))
failures = []


def check(cond, what):
    print(('  ok    ' if cond else '  FAIL  ') + what)
    if not cond:
        failures.append(what)


from config.version import VERSION  # noqa: E402
print(f'verify_data on v{VERSION} (seeded on v{state["seeded_on"]})')

from core.models import Organization, ScheduledTask  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from accounts.models import Membership  # noqa: E402
from django_otp.plugins.otp_totp.models import TOTPDevice  # noqa: E402

orgs = {k: Organization.objects.filter(id=v['id']).first() for k, v in state['orgs'].items()}
check(all(orgs.values()), 'organizations present')
for name, info in state['users'].items():
    u = User.objects.filter(id=info['id'], username=name).first()
    check(u is not None and u.check_password(state['password']), f'user {name} present, password still valid')
    if 'totp_key' in info:
        check(TOTPDevice.objects.filter(user_id=info['id'], key=info['totp_key'], confirmed=True).exists(),
              f'user {name} 2FA device intact')
check(Membership.objects.filter(user__username='rh_client_a', organization=orgs['a'], is_active=True).exists()
      and not Membership.objects.filter(user__username='rh_client_a', organization=orgs['b']).exists(),
      'memberships: client A belongs to org A only')

from vault.models import Password  # noqa: E402
for e in state['vault']:
    p = Password.objects.filter(id=e['id']).first()
    check(p is not None and p.organization_id == orgs[e['org']].id, f'vault entry {e["id"]} present in org {e["org"]}')
    if p is None:
        continue
    try:
        check(p.get_password() == e['password'], f'vault entry {e["id"]}: password decrypts')
    except Exception as ex:
        check(False, f'vault entry {e["id"]}: password decrypts ({ex.__class__.__name__}: {ex})')
    if 'otp_secret' in e and hasattr(p, 'get_otp_secret'):
        try:
            check(p.get_otp_secret() == e['otp_secret'], f'vault entry {e["id"]}: TOTP secret decrypts')
        except Exception as ex:
            check(False, f'vault entry {e["id"]}: TOTP secret decrypts ({ex})')
    if 'secure_notes' in e and hasattr(p, 'get_secure_notes'):
        try:
            check(p.get_secure_notes() == e['secure_notes'], f'vault entry {e["id"]}: secure notes decrypt')
        except Exception as ex:
            check(False, f'vault entry {e["id"]}: secure notes decrypt ({ex})')

from files.models import Attachment  # noqa: E402
for a in state['attachments']:
    att = Attachment.objects.filter(id=a['id']).first()
    check(att is not None and att.organization_id == orgs[a['org']].id, f'attachment {a["id"]} row in org {a["org"]}')
    if att is None:
        continue
    try:
        with att.file.open('rb') as f:
            data = f.read()
        check(hashlib.sha256(data).hexdigest() == a['sha256'], f'attachment {a["id"]} ({a["name"]}): file bytes unchanged')
    except Exception as ex:
        check(False, f'attachment {a["id"]}: file readable ({ex})')

from psa.models import Ticket  # noqa: E402
from assets.models import Asset  # noqa: E402
from docs.models import Document  # noqa: E402
for t in state['tickets']:
    check(Ticket.objects.filter(id=t['id'], subject=t['subject'], organization=orgs[t['org']]).exists(),
          f'ticket {t["id"]} intact in org {t["org"]}')
for a in state['assets']:
    check(Asset.objects.filter(id=a['id'], serial_number=a['serial'], organization=orgs[a['org']]).exists(),
          f'asset {a["id"]} intact in org {a["org"]}')
for d in state['documents']:
    check(Document.objects.filter(id=d['id'], title=d['title'], organization=orgs[d['org']]).exists(),
          f'document {d["id"]} intact in org {d["org"]}')

# Tenant scoping through the org-scoped manager the views use.
try:
    scoped = Password.objects.for_organization(orgs['a']) if hasattr(Password.objects, 'for_organization') \
        else Password.objects.filter(organization=orgs['a'])
    titles = set(scoped.values_list('title', flat=True))
    check('Rehearsal vault A' in titles and 'Rehearsal vault B' not in titles,
          'vault entries are scoped to their organization')
except Exception as ex:
    check(False, f'org-scoped query ({ex})')

# One scheduler tick runs the due task.
task_type = state['scheduler_task']
ScheduledTask.objects.filter(task_type=task_type).update(
    enabled=True, next_run_at=timezone.now() - timezone.timedelta(minutes=1), last_status='success')
before = ScheduledTask.objects.get(task_type=task_type).run_count
call_command('run_scheduler')
task = ScheduledTask.objects.get(task_type=task_type)
check(task.run_count == before + 1 and task.last_status == 'success',
      f'scheduler tick ran {task_type} (run_count {before} -> {task.run_count}, status {task.last_status})')

if failures:
    print(f'verify_data: {len(failures)} FAILURE(S)')
    sys.exit(1)
print('verify_data: all checks passed')
