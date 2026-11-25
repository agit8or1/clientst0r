"""Fill the vault pages of the demo: a credential that needs approval to
reveal, with pending and decided reveal requests and a break-glass event;
breach-check results; secure notes on one entry; My Vault notes; and secure
notes in an inbox, a sent list and the secret-links list.

Isolated demo database only. Idempotent: rows are found by title first.
Every name, note and value is invented.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

_db = str(settings.DATABASES['default'].get('NAME', ''))
_demo = os.environ.get('DEMO_DIR', '')
if not _demo or not _db.startswith(_demo):
    sys.exit(f'refusing to seed: {_db!r} is not under DEMO_DIR')

from core.models import Organization, SecureNote, SecureNoteAccessLog
from vault.models import Password, PasswordBreachCheck, PersonalVault, VaultRevealRequest

User = get_user_model()
now = timezone.now()
org = Organization.objects.get(name='Northwind Logistics')
lead = User.objects.get(username='demo.tech')
priya = User.objects.get(username='demo.ipatel')
mo = User.objects.get(username='demo.mokafor')


def entry(title):
    return Password.objects.get(organization=org, title=title)


# --- approval-gated credential + reveal requests ---------------------------
gated = entry('Microsoft 365 — break-glass admin')
if not gated.requires_reveal_approval:
    gated.requires_reveal_approval = True
    gated.save(update_fields=['requires_reveal_approval'])

REQUESTS = [
    # requester, justification, status, hours ago, break-glass, decided by, notes
    (priya, 'Ticket PSA-2026-000019: the conditional access policy locked out every admin. '
            'Need the break-glass account to restore access during the 14:00 change window.',
     'pending', 1, False, None, ''),
    (mo, 'Quarterly test of the emergency sign-in, scheduled in change CR-118.',
     'approved', 30, False, lead, 'Approved for the scheduled test. Rotate afterwards.'),
    (priya, 'Re-enable a licence on the shared mailbox.',
     'denied', 54, False, lead, 'Use your own delegated admin role for this.'),
    (mo, 'Tenant-wide outage at 02:10, on-call could not reach an approver. '
         'Used to disable the faulty sign-in policy, see PSA-2026-000017.',
     'approved', 76, True, mo, '[BREAK-GLASS] self-approved emergency access'),
]
for who, why, status, hrs, bg, by, notes in REQUESTS:
    r, created = VaultRevealRequest.objects.get_or_create(
        password=gated, requester=who, justification=why,
        defaults={'status': status, 'is_break_glass': bg})
    if created or r.status != status:
        r.status = status
        r.is_break_glass = bg
        if status != 'pending':
            r.decided_by = by
            r.decided_at = now - timedelta(hours=hrs - 0.2)
            r.decision_notes = notes
            r.expires_at = r.decided_at + timedelta(hours=1)
            if status == 'approved':
                r.revealed_at = r.decided_at + timedelta(minutes=4)
        r.save()
    VaultRevealRequest.objects.filter(pk=r.pk).update(requested_at=now - timedelta(hours=hrs))

# --- breach checks + secure notes on a plain entry -------------------------
dc = entry('NWL-DC01 — local administrator')
if not dc.breach_checks.exists():
    PasswordBreachCheck.objects.create(password=dc, is_breached=False, breach_count=0)
if not dc.has_secure_notes:
    dc.set_secure_notes('DSRM password is in the sealed envelope in the depot safe.')
    dc.notes = dc.notes or 'Local administrator on the primary domain controller. LAPS covers member servers only.'
    dc.save(update_fields=['encrypted_notes', 'notes'])
wifi = entry('Warehouse Wi-Fi — scanner PSK')
if not wifi.breach_checks.exists():
    PasswordBreachCheck.objects.create(password=wifi, is_breached=True, breach_count=4127)

# --- My Vault ---------------------------------------------------------------
for title, category, fav, text in [
    ('On-call bridge numbers', 'Notes', True, 'Bridge: +1 555 0100, PIN 0000 (invented).'),
    ('Lab switch console', 'Snippets', False, 'screen /dev/ttyUSB0 9600'),
    ('Vendor support PINs', 'Notes', False, 'Example Networks support PIN: 0000 (invented).'),
]:
    if not PersonalVault.objects.filter(user=lead, title=title).exists():
        item = PersonalVault(user=lead, title=title, category=category, is_favorite=fav)
        item.set_content(text)
        item.save()

# --- Secure notes -----------------------------------------------------------
def note(sender, title, text, **kw):
    n = SecureNote.objects.filter(sender=sender, title=title).first()
    if n:
        return n
    recips = kw.pop('recipients', [])
    n = SecureNote(sender=sender, title=title, organization=org, **kw)
    n.set_content(text)
    if n.link_only:
        n.generate_access_token()
    n.save()
    if recips:
        n.recipients.set(recips)
    return n

note(priya, 'Temporary admin PIN for the WMS upgrade', 'PIN 0000 (invented), valid until Friday.',
     recipients=[lead], read_once=True, expires_at=now + timedelta(days=7))
n = note(mo, 'Firewall maintenance window notes', 'Failover tested, primary back at 02:40.',
         recipients=[lead])
n.read_by.add(lead)
note(lead, 'Courier account for the depot', 'Account number 000-000 (invented).',
     recipients=[priya, mo], expires_at=now + timedelta(days=30))
link = note(lead, 'New starter Wi-Fi details', 'Guest SSID NWL-Guest, key in the welcome pack (invented).',
            link_only=True, label='Onboarding', max_views=3, expires_at=now + timedelta(days=7))
if not link.access_logs.exists():
    SecureNoteAccessLog.objects.create(secure_note=link, ip_address='203.0.113.24',
                                       user_agent='Mozilla/5.0 (Windows NT 10.0) Example')
    link.read_count = 1
    link.save(update_fields=['read_count'])
SecureNote.objects.filter(sender=lead, link_only=True, title__startswith='Secure message for',
                          label='').update(label='Ticket secure message')
print('vault demo data ready')
