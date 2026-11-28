"""Wallboard displays for the demo (roadmap 83.6): the Service Desk board on
two screens, one paired TV in the NOC and one display link on a signage
player in reception, plus a revoked TV, so the Displays page shows each
state.

Isolated demo database only. The credentials are random and thrown away
(only their HMACs are stored, as the application does), so none of these
displays can actually be opened. Idempotent: a rerun replaces its own rows.
"""
import os, sys
from datetime import timedelta

_ROOT = os.environ.get('DEMO_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, 'scripts', 'demo')); os.chdir(_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_settings')
import django; django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from reports import displays as D  # noqa: E402
from reports.models import Wallboard, WallboardDisplay  # noqa: E402

NAMES = ('NOC TV left', 'Reception signage', 'Old lobby TV')

board = Wallboard.objects.filter(organization__isnull=True, name='Service Desk').first()
if board is None:
    print('  displays: no Service Desk board, skipped')
    raise SystemExit(0)
tech = User.objects.get(username='demo.tech')
now = timezone.now()
WallboardDisplay.objects.filter(wallboard=board, name__in=NAMES).delete()

# Everything the board's widgets read, across every customer: what a
# superuser approving a global board records.
scope = {'org_ids': None, 'perm_orgs': {p: None for p in (
    'tickets_view', 'billing_view', 'reports_view_dashboards')}}
tv_ua = ('Mozilla/5.0 (SMART-TV; Linux; Tizen 7.0) AppleWebKit/537.36 (KHTML, like Gecko) '
         'SamsungBrowser/5.0 Chrome/94.0 TV Safari/537.36')
player_ua = 'Mozilla/5.0 (Linux; Android 11; AFTKA) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def make(name, kind, **kw):
    d = WallboardDisplay.objects.create(
        wallboard=board, name=name, kind=kind, scope=scope, created_by=tech,
        credential_hash=D.hash_credential(D.new_credential()), **kw)
    return d


noc = make('NOC TV left', WallboardDisplay.KIND_PAIRED,
           allowed_networks='192.168.10.0/24', pairing_ip='192.168.10.41', pairing_user_agent=tv_ua,
           last_seen_at=now - timedelta(seconds=40), last_seen_ip='192.168.10.41',
           last_seen_user_agent=tv_ua)
lobby = make('Reception signage', WallboardDisplay.KIND_LINK,
             allowed_networks='203.0.113.10', expires_at=now + timedelta(days=90),
             last_seen_at=now - timedelta(minutes=2), last_seen_ip='203.0.113.10',
             last_seen_user_agent=player_ua)
old = make('Old lobby TV', WallboardDisplay.KIND_PAIRED, pairing_ip='192.168.10.77',
           pairing_user_agent=tv_ua, revoked_at=now - timedelta(days=3), revoked_by=tech,
           last_seen_at=now - timedelta(days=3, minutes=5), last_seen_ip='192.168.10.77',
           last_seen_user_agent=tv_ua)
WallboardDisplay.objects.filter(pk=noc.pk).update(created_at=now - timedelta(days=21))
WallboardDisplay.objects.filter(pk=lobby.pk).update(created_at=now - timedelta(days=6))
WallboardDisplay.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=60))
print(f'  displays: {board.name} on {len(NAMES)} screens (1 revoked)')
