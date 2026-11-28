"""
Wallboard displays — views. Logic and security notes: reports/displays.py.

Two groups:

* TV side, under /reports/wallboards/display/ (no sign-in). These never read
  request.user or the session; the display cookie (or the pairing cookie) is
  the only thing they trust. Anonymous requests already pass every sign-in
  middleware, so no middleware exemption was added for them.
* Management, under /reports/wallboards/<pk>/displays/ (signed in, staff-only
  section, edit rights on that board checked per request).
"""
import hashlib
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import displays as D
from .models import Wallboard, WallboardDisplay, WallboardPairingRequest

log = logging.getLogger('reports.displays')

CHART_TYPES = ('chart_line', 'chart_bar', 'chart_pie')

# Rate limits (django-ratelimit; key='ip' resolves through core.client_ip).
PAIR_START_RATE = '20/h'      # new pairing codes per TV address
POLL_RATE = '60/m'            # pairing status polls per address (5 s polling)
LINK_RATE = '30/m'            # display-link opens per address
DATA_RATE = '240/m'           # data refreshes per address (many TVs behind one NAT)
CODE_ATTEMPT_RATE = '10/10m'  # code entries per signed-in user
CODE_ATTEMPT_GLOBAL = '60/10m'  # code entries install-wide

GENERIC_CODE_ERROR = ("That code wasn't accepted. Check the code on the TV — "
                      "codes are 8 characters and expire after 10 minutes.")


def _limited(request, group, rate, key='ip'):
    from django_ratelimit.core import is_ratelimited
    return is_ratelimited(request, group=group, key=key, rate=rate, increment=True)


def _harden(response):
    response['Cache-Control'] = 'no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


def _message(request, title, body, status, *, pair_again=False, clear_cookie=False, retry_seconds=0):
    resp = render(request, 'reports/display/message.html', {
        'title': title, 'body': body, 'pair_again': pair_again,
        'retry_seconds': retry_seconds,
        'pair_url': D.DISPLAY_PATH + '?pair=1',
    }, status=status)
    if clear_cookie:
        D.clear_display_cookie(resp)
    return _harden(resp)


def _revoked(request):
    return _message(request, 'Display revoked — pair again',
                    'This screen is no longer allowed to show a wallboard. It was '
                    'revoked, it expired, or its board was removed or switched off.',
                    403, pair_again=True)


def _wrong_network(request):
    return _message(request, 'Not allowed from this network',
                    "This display isn't allowed to show its wallboard from the "
                    'network it is on. Ask whoever manages the board to update '
                    'its IP rule.', 403, retry_seconds=300)


# ---- TV side ---------------------------------------------------------------

def _widget_payloads(display):
    from .widget_sources import default_category, get_categories, get_widget_data
    board = display.wallboard
    viewer = D.display_viewer(display)
    out = []
    for w in board.widgets.order_by('order', 'created_at'):
        if w.data_source not in D.DISPLAY_SAFE_SOURCES:
            data = dict(D.NOT_AVAILABLE)
        else:
            params = dict(w.query_params or {})
            if get_categories(w.data_source):
                params['category'] = params.get('category') or default_category(w.data_source)
            data = get_widget_data(w.data_source, params, viewer)
        out.append({
            'id': w.pk, 'title': w.title, 'type': w.widget_type,
            'width': (w.position or {}).get('width'),
            'height': (w.position or {}).get('height'),
            'data': data,
        })
    return out


def _layout_version(board):
    parts = [str(board.pk), board.updated_at.isoformat() if board.updated_at else '',
             str(board.refresh_seconds)]
    for pk, updated, order, src, wtype in board.widgets.order_by('order', 'created_at').values_list(
            'pk', 'updated_at', 'order', 'data_source', 'widget_type'):
        parts.append(f'{pk}:{updated.isoformat() if updated else ""}:{order}:{src}:{wtype}')
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def _refresh_seconds(board):
    # 0 on a board means "no auto refresh" for a person watching; a display
    # still has to notice revocation, so it checks every 5 minutes.
    if not board.refresh_seconds:
        return 300
    return max(15, board.refresh_seconds)


@require_GET
def display_home(request):
    """The TV's one address: the board when the cookie is valid, otherwise
    a pairing code (or the revoked / wrong-network message)."""
    from core.json_embed import jsonable
    state, display = D.resolve(request)
    if state == D.DisplayState.OK:
        D.touch(display, request)
        board = display.wallboard
        resp = render(request, 'reports/display/board.html', {
            'board': board,
            'display': display,
            'widgets': jsonable(_widget_payloads(display)),
            'layout_version': _layout_version(board),
            'refresh_seconds': _refresh_seconds(board),
            'data_url': reverse('reports:display_data'),
        })
        # Keep the cookie alive for a display that keeps running.
        D.set_display_cookie(resp, request, request.COOKIES[D.COOKIE_NAME], display)
        return _harden(resp)
    if state == D.DisplayState.NETWORK:
        return _wrong_network(request)
    if state == D.DisplayState.INVALID and request.GET.get('pair') != '1':
        return _revoked(request)
    return _start_pairing(request)


def _start_pairing(request):
    if _limited(request, 'wallboard-display-pair-start', PAIR_START_RATE):
        resp = _message(request, 'Too many pairing requests',
                        'This network asked for too many pairing codes. The screen '
                        'will try again in a few minutes.', 429, retry_seconds=300)
        D.clear_display_cookie(resp)
        return resp
    # A reload replaces the TV's previous code (the code is only ever shown,
    # never stored, so it cannot be shown again).
    old = request.COOKIES.get(D.PAIRING_COOKIE_NAME)
    if old and len(old) <= 200:
        WallboardPairingRequest.objects.filter(
            secret_hash=D.hash_secret(old), display__isnull=True).delete()
    pr, code, secret = D.create_pairing_request(request)
    resp = render(request, 'reports/display/pair.html', {
        'code': D.format_code(code),
        'expires_at': pr.expires_at,
        'ttl_seconds': int(D.PAIRING_TTL.total_seconds()),
        'status_url': reverse('reports:display_pair_status'),
        'display_url': D.DISPLAY_PATH,
        'manage_hint': '/reports/wallboards/',
    })
    D.clear_display_cookie(resp)
    D.set_pairing_cookie(resp, request, secret)
    return _harden(resp)


@require_GET
def display_pair_status(request):
    """Polled by the pairing page. When the code was approved, hands the TV
    its credential (generated now, so the raw value is never stored)."""
    if _limited(request, 'wallboard-display-poll', POLL_RATE):
        return _harden(JsonResponse({'state': 'slow_down'}, status=429))
    secret = request.COOKIES.get(D.PAIRING_COOKIE_NAME)
    pr = D.pending_request_for_secret(secret)
    if pr is None:
        resp = JsonResponse({'state': 'expired'})
        D.clear_pairing_cookie(resp)
        return _harden(resp)
    if pr.display_id is None:
        return _harden(JsonResponse({'state': 'pending'}))

    raw = D.new_credential()
    with transaction.atomic():
        claimed = WallboardDisplay.objects.filter(
            pk=pr.display_id, credential_hash__isnull=True, revoked_at__isnull=True,
        ).update(credential_hash=D.hash_credential(raw))
        WallboardPairingRequest.objects.filter(pk=pr.pk).delete()
    resp = JsonResponse({'state': 'paired' if claimed else 'expired'})
    D.clear_pairing_cookie(resp)
    if claimed:
        display = WallboardDisplay.objects.get(pk=pr.display_id)
        D.set_display_cookie(resp, request, raw, display)
    return _harden(resp)


@require_GET
def display_data(request):
    """Widget data for the display's own board — the only data a display can
    ask for. No board id in the URL: the credential decides."""
    if _limited(request, 'wallboard-display-data', DATA_RATE):
        return _harden(JsonResponse({'state': 'slow_down'}, status=429))
    state, display = D.resolve(request)
    if state == D.DisplayState.NETWORK:
        return _harden(JsonResponse({'state': 'network'}, status=403))
    if state != D.DisplayState.OK:
        return _harden(JsonResponse({'state': 'revoked'}, status=403))
    D.touch(display, request)
    board = display.wallboard
    return _harden(JsonResponse({
        'state': 'ok',
        'layout_version': _layout_version(board),
        'refresh_seconds': _refresh_seconds(board),
        'generated_at': timezone.now().isoformat(),
        'widgets': _widget_payloads(display),
    }))


@require_GET
def display_link(request):
    """The page a display link opens. The secret is in the URL fragment
    (#...), which browsers never send to the server, so it never reaches an
    access log, a proxy or a Referer header. This page's script reads it,
    posts it to display_link_open and clears it from the address bar."""
    return _harden(render(request, 'reports/display/link.html', {
        'open_url': reverse('reports:display_link_open'),
        'display_url': D.DISPLAY_PATH,
    }))


@require_POST
def display_link_open(request):
    """Exchange a display link token (POST body, CSRF-checked) for the
    display cookie. The link stays usable until it is revoked or expires, so a
    player that forgets its cookies on restart can open it again."""
    if _limited(request, 'wallboard-display-link', LINK_RATE):
        return _harden(JsonResponse({'state': 'slow_down'}, status=429))
    token = (request.POST.get('token') or '').strip()
    invalid = _harden(JsonResponse({'state': 'invalid'}, status=404))
    if not token or len(token) > 200:
        return invalid
    digest = D.hash_credential(token)
    display = (WallboardDisplay.objects.select_related('wallboard')
               .filter(credential_hash=digest, kind=WallboardDisplay.KIND_LINK).first())
    if display is None or not D._same(display.credential_hash, digest) or not display.is_usable \
            or not display.wallboard.is_active:
        return invalid
    if not D.ip_allowed(display, D.client_ip(request)):
        return _harden(JsonResponse({'state': 'network'}, status=403))
    resp = JsonResponse({'state': 'ok', 'next': D.DISPLAY_PATH})
    D.set_display_cookie(resp, request, token, display)
    D.clear_pairing_cookie(resp)
    return _harden(resp)


# ---- Management ------------------------------------------------------------

def _board_for_manager(request, pk):
    from .views import _user_can_see_wallboards
    board = get_object_or_404(Wallboard.objects.select_related('organization'), pk=pk)
    if not _user_can_see_wallboards(request.user, board.organization):
        raise Http404('Wallboard not found')
    if not D.can_manage_displays(request, board):
        raise PermissionDenied('You need permission to edit this wallboard to manage its displays.')
    return board


def _audit(request, action, display, description, extra=None):
    from audit.models import AuditLog
    try:
        AuditLog.log(
            request.user, action, organization=display.wallboard.organization,
            object_type='wallboard_display', object_id=display.pk,
            object_repr=str(display)[:255], description=description,
            ip_address=D.client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
            path=request.path[:500],
            extra_data=dict({'wallboard_id': display.wallboard_id, 'kind': display.kind}, **(extra or {})),
        )
    except Exception:
        log.exception('wallboard display audit write failed')


def _parse_common(request, board):
    """(name, networks_text, expires_at, errors) from the pair / link forms."""
    errors = []
    name = (request.POST.get('name') or '').strip()[:120]
    if not name:
        errors.append('Give the display a name, e.g. "NOC TV left".')
    networks_text = (request.POST.get('allowed_networks') or '').strip()
    nets, bad = D.parse_networks(networks_text)
    if bad:
        errors.append('Not an IP address or CIDR range: ' + ', '.join(bad[:5]))
    networks_text = '\n'.join(str(n) for n in nets)
    expires_at = None
    days = (request.POST.get('expires_days') or '').strip()
    if days:
        try:
            n = int(days)
            if n < 1 or n > 3650:
                raise ValueError
            expires_at = timezone.now() + timedelta(days=n)
        except ValueError:
            errors.append('Expiry must be a number of days between 1 and 3650, or empty.')
    return name, networks_text, expires_at, errors


def _render_displays(request, board, new_link=None):
    rows = []
    for d in board.displays.select_related('created_by', 'revoked_by').order_by('-created_at'):
        if d.is_revoked:
            status = 'Revoked'
        elif d.is_expired:
            status = 'Expired'
        elif d.kind == WallboardDisplay.KIND_PAIRED and not d.credential_hash:
            status = 'Waiting for the TV'
        else:
            status = 'Active'
        rows.append({'d': d, 'status': status, 'scope': D.scope_label(d.scope),
                     'device': D.ua_summary(d.last_seen_user_agent or d.pairing_user_agent),
                     'networks': d.network_list})
    unsafe = [w for w in board.widgets.all() if w.data_source not in D.DISPLAY_SAFE_SOURCES]
    resp = render(request, 'reports/wallboard_displays.html', {
        'wallboard': board,
        'rows': rows,
        'new_link': new_link,
        'unsafe_widgets': unsafe,
        'display_url': request.build_absolute_uri(D.DISPLAY_PATH),
        'all_customers_ok': D.build_scope(request, board) is not None,
    })
    if new_link:
        resp['Cache-Control'] = 'no-store'
    return resp


@login_required
def wallboard_displays(request, pk):
    return _render_displays(request, _board_for_manager(request, pk))


@login_required
@require_POST
def wallboard_display_pair(request, pk):
    board = _board_for_manager(request, pk)
    back = redirect('reports:wallboard_displays', pk=board.pk)
    # Count every attempt (right or wrong) so the answer never depends on
    # whether a code exists.
    if (_limited(request, 'wallboard-display-code', CODE_ATTEMPT_RATE, key='user')
            or _limited(request, 'wallboard-display-code-all', CODE_ATTEMPT_GLOBAL,
                        key=lambda g, r: 'all')):
        messages.error(request, 'Too many pairing attempts. Wait ten minutes and try again.')
        return back

    name, networks_text, expires_at, errors = _parse_common(request, board)
    if errors:
        for e in errors:
            messages.error(request, e)
        return back
    scope = D.build_scope(request, board)
    if scope is None:
        messages.error(request, 'Only someone who can see every customer can put a global '
                                'board on a display.')
        return back

    D.cleanup_pairing_requests()
    pr = D.find_pending_code(request.POST.get('code'))
    if pr is None:
        messages.error(request, GENERIC_CODE_ERROR)
        return back

    probe = WallboardDisplay(allowed_networks=networks_text)
    if not D.ip_allowed(probe, pr.requested_ip):
        messages.error(request, f'The TV is on {pr.requested_ip or "an unknown address"}, which is '
                                'outside the IP rule you entered. Widen the rule or leave it empty.')
        return back

    now = timezone.now()
    with transaction.atomic():
        display = WallboardDisplay.objects.create(
            wallboard=board, name=name, kind=WallboardDisplay.KIND_PAIRED,
            scope=scope, allowed_networks=networks_text, expires_at=expires_at,
            created_by=request.user, pairing_ip=pr.requested_ip,
            pairing_user_agent=pr.user_agent,
        )
        claimed = WallboardPairingRequest.objects.filter(
            pk=pr.pk, display__isnull=True, expires_at__gt=now,
        ).update(display=display, approved_at=now, expires_at=now + D.COLLECT_TTL)
        if not claimed:
            transaction.set_rollback(True)
    if not claimed:
        messages.error(request, GENERIC_CODE_ERROR)
        return back
    _audit(request, 'create', display,
           f'Paired display "{name}" with wallboard "{board.name}"',
           {'action': 'wallboard_display_paired', 'scope': D.scope_label(scope),
            'pairing_ip': pr.requested_ip, 'allowed_networks': display.network_list,
            'expires_at': expires_at.isoformat() if expires_at else None})
    messages.success(request, f'Paired "{name}". The TV will show the board within a few seconds.')
    return back


@login_required
@require_POST
def wallboard_display_link_create(request, pk):
    board = _board_for_manager(request, pk)
    back = redirect('reports:wallboard_displays', pk=board.pk)
    name, networks_text, expires_at, errors = _parse_common(request, board)
    if errors:
        for e in errors:
            messages.error(request, e)
        return back
    scope = D.build_scope(request, board)
    if scope is None:
        messages.error(request, 'Only someone who can see every customer can put a global '
                                'board on a display.')
        return back
    raw = D.new_credential()
    display = WallboardDisplay.objects.create(
        wallboard=board, name=name, kind=WallboardDisplay.KIND_LINK,
        credential_hash=D.hash_credential(raw), scope=scope,
        allowed_networks=networks_text, expires_at=expires_at, created_by=request.user,
    )
    _audit(request, 'create', display,
           f'Created display link "{name}" for wallboard "{board.name}"',
           {'action': 'wallboard_display_link_created', 'scope': D.scope_label(scope),
            'allowed_networks': display.network_list,
            'expires_at': expires_at.isoformat() if expires_at else None})
    # Shown once, in this response only: the raw token is not kept anywhere
    # (not in the session either), only its HMAC.
    return _render_displays(request, board, new_link={
        'name': name,
        # The secret goes in the fragment, which never reaches the server.
        'url': request.build_absolute_uri(reverse('reports:display_link')) + '#' + raw,
    })


def _display_for_manager(request, pk, display_pk):
    board = _board_for_manager(request, pk)
    return get_object_or_404(WallboardDisplay, pk=display_pk, wallboard=board)


@login_required
@require_POST
def wallboard_display_revoke(request, pk, display_pk):
    display = _display_for_manager(request, pk, display_pk)
    if display.revoked_at is None:
        display.revoked_at = timezone.now()
        display.revoked_by = request.user
        display.save(update_fields=['revoked_at', 'revoked_by'])
        WallboardPairingRequest.objects.filter(display=display).delete()
        _audit(request, 'update', display, f'Revoked display "{display.name}"',
               {'action': 'wallboard_display_revoked'})
        messages.success(request, f'Revoked "{display.name}". It stops showing the board at its next refresh.')
    return redirect('reports:wallboard_displays', pk=display.wallboard_id)


@login_required
@require_POST
def wallboard_display_rename(request, pk, display_pk):
    display = _display_for_manager(request, pk, display_pk)
    name = (request.POST.get('name') or '').strip()[:120]
    if not name:
        messages.error(request, 'The name cannot be empty.')
    elif name != display.name:
        old = display.name
        display.name = name
        display.save(update_fields=['name'])
        _audit(request, 'update', display, f'Renamed display "{old}" to "{name}"',
               {'action': 'wallboard_display_renamed'})
        messages.success(request, f'Renamed to "{name}".')
    return redirect('reports:wallboard_displays', pk=display.wallboard_id)
