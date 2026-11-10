"""Representative records for an upgrade rehearsal. Disposable data only.

Run inside the install being rehearsed, on the OLD release, before upgrading:

    REHEARSAL_STATE=/path/state.json python manage.py shell -c "exec(open('scripts/upgrade_rehearsal/seed.py').read())"

It sticks to model APIs that exist in every release the rehearsal starts
from (v3.17.558 onward) and skips features a release does not have yet
(e.g. vault secure notes, v3.17.659). Everything it creates, and the values
needed to check it later (plaintext secrets, file checksums, the TOTP keys of
the test users), goes into REHEARSAL_STATE for verify_data.py / http_smoke.py.
Never point this at a real install: the state file holds those secrets.
"""
import hashlib
import io
import json
import os
import secrets

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from core.models import Organization, ScheduledTask

STATE = os.environ['REHEARSAL_STATE']
PASSWORD = 'Rehearsal-' + secrets.token_urlsafe(12)
state = {'password': PASSWORD, 'orgs': {}, 'users': {}, 'vault': [], 'attachments': [],
         'tickets': [], 'assets': [], 'documents': []}


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (32, 24), (40, 120, 200)).save(buf, 'PNG')
    return buf.getvalue()


# --- organizations -----------------------------------------------------------
orgs = {}
for key, name in (('a', 'Rehearsal Org A'), ('b', 'Rehearsal Org B')):
    org, _ = Organization.objects.get_or_create(slug=f'rehearsal-{key}', defaults={'name': name})
    orgs[key] = org
    state['orgs'][key] = {'id': org.id, 'name': org.name}

# --- users: superuser with 2FA, org users with 2FA, one user without a device --
from django_otp.plugins.otp_totp.models import TOTPDevice  # noqa: E402
from accounts.models import Membership  # noqa: E402


def make_user(username, *, superuser=False, device=True):
    u = User.objects.filter(username=username).first()
    if u is None:
        if superuser:
            u = User.objects.create_superuser(username, f'{username}@example.invalid', PASSWORD)
        else:
            u = User.objects.create_user(username, f'{username}@example.invalid', PASSWORD)
    info = {'id': u.id, 'username': username}
    if device:
        d = TOTPDevice.objects.filter(user=u).first() or TOTPDevice.objects.create(
            user=u, name='rehearsal', confirmed=True)
        info['totp_key'] = d.key
    state['users'][username] = info
    return u


admin = make_user('rh_admin', superuser=True)
client_a = make_user('rh_client_a')
client_b = make_user('rh_client_b')
make_user('rh_nodevice', device=False)
for u, org in ((client_a, orgs['a']), (client_b, orgs['b'])):
    Membership.objects.get_or_create(user=u, organization=org,
                                     defaults={'role': 'admin', 'is_active': True})

# --- vault: passwords, a TOTP secret, secure notes where the release has them --
from vault.models import Password  # noqa: E402

for key in ('a', 'b'):
    org = orgs[key]
    plain = f'pw-{key}-' + secrets.token_urlsafe(16)
    p = Password(organization=org, title=f'Rehearsal vault {key.upper()}', username=f'svc-{key}',
                 password_type='website', url='https://example.invalid/')
    p.set_password(plain)
    entry = {'org': key, 'title': p.title, 'password': plain}
    if hasattr(p, 'set_secure_notes'):
        notes = f'secure note for {key}: ' + secrets.token_urlsafe(8)
        p.set_secure_notes(notes)
        entry['secure_notes'] = notes
    if hasattr(p, 'set_otp_secret'):
        totp = 'JBSWY3DPEHPK3PXP'
        p.set_otp_secret(totp)
        entry['otp_secret'] = totp
    p.save()
    entry['id'] = p.id
    state['vault'].append(entry)

# --- documents with uploaded files -------------------------------------------
from docs.models import Document  # noqa: E402
from files.models import Attachment  # noqa: E402

for key in ('a', 'b'):
    org = orgs[key]
    doc_kwargs = dict(organization=org, title=f'Rehearsal runbook {key.upper()}',
                      slug=f'rehearsal-runbook-{key}', body='<p>Upgrade rehearsal</p>')
    if 'created_by' in {f.name for f in Document._meta.get_fields()}:
        doc_kwargs['created_by'] = admin
    doc = Document.objects.create(**doc_kwargs)
    state['documents'].append({'org': key, 'id': doc.id, 'title': doc.title})
    for fname, data, ctype in ((f'runbook-{key}.txt', f'rehearsal file {key} '.encode() * 50, 'text/plain'),
                               (f'diagram-{key}.png', _png_bytes(), 'image/png')):
        att = Attachment(organization=org, entity_type='document', entity_id=doc.id,
                         original_filename=fname, file_size=len(data), content_type=ctype,
                         uploaded_by=admin)
        att.file.save(fname, ContentFile(data), save=False)
        att.save()
        att.refresh_from_db()
        with att.file.open('rb') as f:
            stored = f.read()
        state['attachments'].append({'org': key, 'id': att.id, 'name': att.file.name,
                                     'sha256': hashlib.sha256(stored).hexdigest(), 'size': len(stored)})

# --- assets ------------------------------------------------------------------
from assets.models import Asset  # noqa: E402

for key in ('a', 'b'):
    a = Asset.objects.create(organization=orgs[key], name=f'rehearsal-server-{key}',
                             asset_type='server', serial_number=f'SN-{key}-{secrets.token_hex(3)}')
    state['assets'].append({'org': key, 'id': a.id, 'name': a.name, 'serial': a.serial_number})

# --- tickets (PSA reference data first) --------------------------------------
call_command('psa_seed_defaults', verbosity=0)
from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType  # noqa: E402

for key in ('a', 'b'):
    t = Ticket.objects.create(organization=orgs[key], subject=f'Rehearsal ticket {key.upper()}',
                              description='Created before the upgrade.',
                              status=TicketStatus.objects.order_by('id').first(),
                              priority=TicketPriority.objects.order_by('id').first(),
                              ticket_type=TicketType.objects.order_by('id').first(),
                              queue=Queue.objects.order_by('id').first())
    state['tickets'].append({'org': key, 'id': t.id, 'subject': t.subject,
                             'number': t.ticket_number})

# --- scheduler: one cheap local task due, network tasks off -------------------
ScheduledTask.get_or_create_defaults()
ScheduledTask.objects.exclude(task_type='cleanup_stuck_scans').update(enabled=False)
ScheduledTask.objects.filter(task_type='cleanup_stuck_scans').update(
    enabled=True, next_run_at=timezone.now() - timezone.timedelta(minutes=5), last_status='success')
state['scheduler_task'] = 'cleanup_stuck_scans'

from config.version import VERSION  # noqa: E402
state['seeded_on'] = VERSION
with open(STATE, 'w') as f:
    json.dump(state, f, indent=2)
os.chmod(STATE, 0o600)
print(f'seeded on v{VERSION}: {len(state["vault"])} vault entries, {len(state["attachments"])} files, '
      f'{len(state["tickets"])} tickets, {len(state["assets"])} assets, users {sorted(state["users"])}')
