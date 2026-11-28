"""
Wallboard displays: show one board on a TV without anyone signing in.

Two ways to authorise a TV, both ending in the same cookie:

* Pairing. The TV opens /reports/wallboards/display/ and shows a short code.
  Someone who may edit the board types the code on the board's Displays page
  and approves it. The TV's next poll (it holds a random pairing secret in a
  cookie) collects a long random display credential.
* Display link. Someone who may edit the board creates a secret link (shown
  once). Opening it stores the link token as the display credential and
  redirects to the clean display URL.

Security properties (see docs/WALLBOARD_DISPLAYS.md):

* Credentials, link tokens, pairing codes and pairing secrets are stored only
  as HMACs (vault.secret_fields.hash_token, one purpose each) and looked up by
  that HMAC, then compared again with hmac.compare_digest.
* The cookie is HttpOnly, SameSite=Strict, Secure on HTTPS, and scoped to
  DISPLAY_PATH, so the browser never sends it anywhere else. Nothing here
  touches the session or request.user: a display is not a user and gets no
  session.
* What a display sees is fixed when it is authorised (`build_scope`): the
  board's customer, or every customer only if the authorising person could see
  every customer. At view time only the recorded scope is used, and the board
  must still exist, be active and still match that scope.
* Only sources in DISPLAY_SAFE_SOURCES render on a display.
* Optional IP / CIDR allowlist per display, checked against the client address
  from core.client_ip (trusted-proxy aware).
"""
import hashlib
import hmac
import ipaddress
import secrets
from datetime import timedelta

from django.utils import timezone

DISPLAY_PATH = '/reports/wallboards/display/'
COOKIE_NAME = 'wb_display'
PAIRING_COOKIE_NAME = 'wb_display_pairing'

CREDENTIAL_PURPOSE = 'reports.wallboard_display.credential'
CODE_PURPOSE = 'reports.wallboard_display.pairing_code'
SECRET_PURPOSE = 'reports.wallboard_display.pairing_secret'

PAIRING_TTL = timedelta(minutes=10)
# After approval the TV has this long to collect its credential.
COLLECT_TTL = timedelta(minutes=10)
# Browsers cap cookie lifetime at 400 days; the cookie is re-set on each page
# load so a display that keeps running keeps its credential.
COOKIE_MAX_AGE = 400 * 24 * 3600
# last_seen_* is written at most this often per display (SQLite write load).
LAST_SEEN_INTERVAL = timedelta(seconds=60)

# Unambiguous for reading across a room: no 0/O, 1/I/L.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 8

# Sources a display may render. Anything not listed (now or added to the
# registry later) shows "Not available on displays". Left out on purpose:
#   vault_activity_24h   — vault access activity (audit trail of secrets)
#   recent_failed_logins — sign-in attack telemetry
#   my_assigned_tickets  — "my" needs a signed-in user; a display has none
DISPLAY_SAFE_SOURCES = frozenset({
    'revenue_this_period', 'open_tickets_count', 'overdue_tickets_count',
    'unbilled_hours', 'active_techs', 'avg_resolution_hours',
    'top_clients_by_revenue', 'tickets_by_priority', 'at_risk_clients',
    'revenue_trend_30d', 'tickets_opened_30d', 'hours_split_pie',
    'sla_breach_trend', 'client_health_breakdown', 'low_stock_items',
    'recent_sales_activity', 'security_alerts_24h',
    'security_alerts_open_critical', 'techs_logged_in', 'monitors_down',
    'ssl_expiring_soon', 'domain_expiring_soon', 'warranties_expiring_soon',
    'alerts_by_severity', 'monitors_status_breakdown',
})

NOT_AVAILABLE = {'error': 'Not available on displays', 'restricted': True}


# ---- Tokens ----------------------------------------------------------------

def _hash(raw, purpose):
    from vault.secret_fields import hash_token
    return hash_token(raw, purpose)


def hash_credential(raw):
    return _hash(raw, CREDENTIAL_PURPOSE)


def new_credential():
    return secrets.token_urlsafe(48)


def normalize_code(code):
    return ''.join(ch for ch in (code or '').upper() if ch.isalnum())


def new_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code):
    return f'{code[:4]}-{code[4:]}'


def hash_code(code):
    return _hash(normalize_code(code), CODE_PURPOSE)


def hash_secret(secret):
    return _hash(secret, SECRET_PURPOSE)


def _same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


# ---- Networks --------------------------------------------------------------

def parse_networks(text):
    """(networks, errors) for an allowlist typed one per line or comma-separated."""
    nets, errors = [], []
    for part in (text or '').replace(',', '\n').splitlines():
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            errors.append(part)
    return nets, errors


def ip_allowed(display, ip):
    nets, _errors = parse_networks(display.allowed_networks)
    if not nets:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == n.version and addr in n for n in nets)


def client_ip(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request)


# ---- Who may manage displays ----------------------------------------------

MANAGE_PERM = 'reports_manage_dashboards'


def can_manage_displays(request, board):
    """May this signed-in user pair, create, rename or revoke displays for
    `board`? The same people who may edit it, checked against the board's own
    customer (not just "holds the flag somewhere"): for a customer's board the
    manage permission at that customer, inside the technician's client scope;
    for a global board the permission across every customer and an
    all-customers client scope."""
    from accounts.permission_utils import user_has_org_perm
    from psa.visibility import is_msp_staff
    from reports.access import has_msp_wide_perm, viewer_client_scope
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return False
    if not (user.is_superuser or is_msp_staff(user)):
        return False
    if board.organization_id is None:
        return (has_msp_wide_perm(user, MANAGE_PERM)
                and viewer_client_scope(user) is None)
    return user_has_org_perm(user, board.organization_id, MANAGE_PERM)


def build_scope(request, board):
    """The data scope a display of `board` authorised by request.user gets,
    or None when that person may not authorise one.

    Customer board: that customer only, with each widget permission the
    person holds there. Global board: every customer, only if the person
    sees every customer (viewer_for gives org_ids None and their client scope
    is all), with the permissions they hold across every customer."""
    from reports.access import viewer_client_scope
    from reports.widget_sources import viewer_for
    viewer = viewer_for(request.user, getattr(request, 'is_staff_user', False))
    perm_orgs = viewer.get('perm_orgs') or {}
    if board.organization_id is None:
        if viewer.get('org_ids') is not None or viewer_client_scope(request.user) is not None:
            return None
        return {
            'org_ids': None,
            'perm_orgs': {p: (None if ids is None else sorted(ids)) for p, ids in perm_orgs.items()},
        }
    org_id = board.organization_id
    if viewer.get('org_ids') is not None and org_id not in viewer['org_ids']:
        return None
    scoped = {}
    for p, ids in perm_orgs.items():
        scoped[p] = [org_id] if (ids is None or org_id in ids) else []
    return {'org_ids': [org_id], 'perm_orgs': scoped}


def scope_matches_board(scope, board):
    org_ids = (scope or {}).get('org_ids', 'missing')
    if board.organization_id is None:
        return org_ids is None
    return org_ids == [board.organization_id]


def display_viewer(display):
    """The widget viewer for a display: only what was recorded."""
    scope = display.scope or {}
    perm_orgs = {p: (None if ids is None else list(ids))
                 for p, ids in (scope.get('perm_orgs') or {}).items()}
    return {
        'user_id': None,
        'org_ids': scope.get('org_ids') if 'org_ids' in scope else [],
        'perm_orgs': perm_orgs,
        'perms': {p for p, ids in perm_orgs.items() if ids is None or ids},
    }


def scope_label(scope):
    if (scope or {}).get('org_ids', []) is None:
        return 'All customers'
    return 'This board\'s customer'


# ---- Resolving a display from a request -----------------------------------

class DisplayState:
    OK = 'ok'
    NONE = 'none'          # no cookie at all
    INVALID = 'invalid'    # unknown, revoked, expired, or board gone/inactive
    NETWORK = 'network'    # IP outside the display's allowlist


def resolve(request):
    """(state, display) for the display cookie on this request."""
    from reports.models import WallboardDisplay
    raw = request.COOKIES.get(COOKIE_NAME)
    if not raw:
        return DisplayState.NONE, None
    if len(raw) > 200:
        return DisplayState.INVALID, None
    digest = hash_credential(raw)
    display = (WallboardDisplay.objects.select_related('wallboard')
               .filter(credential_hash=digest).first())
    if display is None or not _same(display.credential_hash, digest):
        return DisplayState.INVALID, None
    if not display.is_usable:
        return DisplayState.INVALID, display
    board = display.wallboard
    if not board.is_active or not scope_matches_board(display.scope, board):
        return DisplayState.INVALID, display
    if not ip_allowed(display, client_ip(request)):
        return DisplayState.NETWORK, display
    return DisplayState.OK, display


def touch(display, request):
    now = timezone.now()
    if display.last_seen_at and now - display.last_seen_at < LAST_SEEN_INTERVAL:
        return
    from reports.models import WallboardDisplay
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:255]
    WallboardDisplay.objects.filter(pk=display.pk).update(
        last_seen_at=now, last_seen_ip=client_ip(request), last_seen_user_agent=ua)


def set_display_cookie(response, request, raw, display=None):
    max_age = COOKIE_MAX_AGE
    if display is not None and display.expires_at:
        max_age = max(0, min(max_age, int((display.expires_at - timezone.now()).total_seconds())))
    response.set_cookie(
        COOKIE_NAME, raw, max_age=max_age, path=DISPLAY_PATH,
        secure=request.is_secure(), httponly=True, samesite='Strict')


def clear_display_cookie(response):
    response.delete_cookie(COOKIE_NAME, path=DISPLAY_PATH, samesite='Strict')


def set_pairing_cookie(response, request, secret):
    response.set_cookie(
        PAIRING_COOKIE_NAME, secret, max_age=int((PAIRING_TTL + COLLECT_TTL).total_seconds()),
        path=DISPLAY_PATH, secure=request.is_secure(), httponly=True, samesite='Strict')


def clear_pairing_cookie(response):
    response.delete_cookie(PAIRING_COOKIE_NAME, path=DISPLAY_PATH, samesite='Strict')


# ---- Pairing ---------------------------------------------------------------

def cleanup_pairing_requests():
    """Delete pairing requests nobody approved in time (lazy cleanup, run on
    every new request and approval)."""
    from reports.models import WallboardPairingRequest
    WallboardPairingRequest.objects.filter(expires_at__lt=timezone.now()).delete()


def create_pairing_request(request):
    """(pairing_request, code, secret). Retries on the (vanishingly rare)
    hash collision."""
    from django.db import IntegrityError, transaction
    from reports.models import WallboardPairingRequest
    cleanup_pairing_requests()
    for _ in range(5):
        code, secret = new_code(), secrets.token_urlsafe(32)
        try:
            with transaction.atomic():
                pr = WallboardPairingRequest.objects.create(
                    code_hash=hash_code(code), secret_hash=hash_secret(secret),
                    requested_ip=client_ip(request),
                    user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
                    expires_at=timezone.now() + PAIRING_TTL,
                )
            return pr, code, secret
        except IntegrityError:
            continue
    raise RuntimeError('could not allocate a pairing code')


def pending_request_for_secret(secret):
    from reports.models import WallboardPairingRequest
    if not secret or len(secret) > 200:
        return None
    digest = hash_secret(secret)
    pr = WallboardPairingRequest.objects.filter(secret_hash=digest).first()
    if pr is None or not _same(pr.secret_hash, digest) or pr.is_expired:
        return None
    return pr


def find_pending_code(code):
    """The unapproved, unexpired pairing request for a typed code, or None.
    Callers must give one answer for every None (wrong, expired, used)."""
    from reports.models import WallboardPairingRequest
    norm = normalize_code(code)
    if len(norm) != CODE_LENGTH:
        return None
    digest = hash_code(norm)
    pr = WallboardPairingRequest.objects.filter(code_hash=digest, display__isnull=True).first()
    if pr is None or not _same(pr.code_hash, digest) or pr.is_expired:
        return None
    return pr


def ua_summary(ua):
    """Short, human label for a user-agent string."""
    ua = ua or ''
    for needle, label in (('SMART-TV', 'Smart TV'), ('SmartTV', 'Smart TV'), ('Tizen', 'Samsung TV'),
                          ('Web0S', 'LG TV'), ('webOS', 'LG TV'), ('CrKey', 'Chromecast'),
                          ('AFT', 'Fire TV'), ('Android', 'Android'), ('iPad', 'iPad'),
                          ('Macintosh', 'Mac'), ('Windows', 'Windows'), ('Linux', 'Linux')):
        if needle in ua:
            return label
    return (ua[:40] + '…') if len(ua) > 40 else (ua or 'Unknown')


def short_hash(value):
    return hashlib.sha256((value or '').encode()).hexdigest()[:8]
