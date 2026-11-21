"""
Quick Connect pages (protocol 1.1, increment C2). DESIGN.md §13.1, §14.

  qc_start      initiator screens 1-2: address, network check (destination
                preview, this installation's egress confirmed, permissions
                and customers to offer)
  qc_attempt    initiator screens 3-5: authorise on the other application
                (link to ITS admin UI), approve its egress after the answer
                came back, compare codes
  qc_callback   initiator: where the other application sends the browser
                back (redirect_uri); the administrator's own session
  qc_authorize  responder: /agit8or-connect/qc-authorize, the invitation
                review for the administrator signed in HERE (approve needs a
                fresh re-authentication)
  reauth        "confirm it's you" for this installation's own account

No Quick Connect page has a password field and nothing here ever asks for,
receives or forwards a password of the other application: each
administrator signs in only to their own application. Every page 404s
unless AGIT8OR_CONNECT_ENABLED and Quick Connect (Network page) are on.
"""
from __future__ import annotations

import functools
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.permission_utils import user_has_perm

from . import catalog, identity, quick_connect as qcm
from .views_ui import _ctx, _orgs, page

QC_STEPS = ['Address', 'Network check', 'Authorise on the other application', 'Approve the other application',
            'Compare codes']


def _qc_ctx(request, **extra):
    return _ctx(request, steps=QC_STEPS, **extra)


def qc_page(fn):
    """Manage permission for every method; 404 while Quick Connect is off."""
    @page(manage=True)
    @functools.wraps(fn)
    def wrapper(request, *args, **kwargs):
        if not qcm.enabled_here():
            raise Http404
        return fn(request, *args, **kwargs)
    return wrapper


@qc_page
def qc_start(request):
    ctx = _qc_ctx(request, step=0, url=request.POST.get('url', ''), scopes_text=request.POST.get(
        'requested_scopes', 'connection:read customers:read events:publish'))
    problem = qcm.public_base_problem()
    if problem:
        ctx.update(error=problem, not_configured=True)
        return render(request, 'connect/quick_connect.html', ctx)
    ident = identity.get()
    ctx['own_egress'] = ', '.join(e['net'] for e in ident.egress_addresses or [])
    if request.method != 'POST':
        return render(request, 'connect/quick_connect.html', ctx)
    op = request.POST.get('op')
    allow_private = request.POST.get('allow_private') == 'on'
    ca_pem = (request.POST.get('ca_pem') or '').strip()[:20000]
    ctx.update(allow_private=allow_private, ca_pem=ca_pem)
    try:
        origin = qcm.normalize_destination(request.POST.get('url', ''))
        check = qcm.check_peer(origin, allow_private=allow_private, ca_pem=ca_pem)
        ctx.update(step=1, origin=origin, check=check, destination=check.preview,
                   destination_addresses=request.POST.get('destination_addresses', '')[:600]
                   or ', '.join(check.preview.addresses), organizations=_orgs(request),
                   dest_name=origin)
        if check.flow != qcm.qc.BOOTSTRAP_ID:
            ctx['fallback'] = True     # v1-only peer: offer the code flow
            return render(request, 'connect/quick_connect.html', ctx)
        if op == 'authorize':
            egress_text = request.POST.get('own_egress', '')
            if egress_text.strip() != ctx['own_egress']:
                try:
                    entries = qcm.parse_egress_text(egress_text)
                except ValidationError as e:
                    raise qcm.QuickConnectError('invalid_egress', ' '.join(e.messages))
                qcm.set_own_egress(entries, request.user)
                ctx['own_egress'] = ', '.join(e['net'] for e in entries)
            orgs = list(_orgs(request).filter(pk__in=[int(x) for x in request.POST.getlist('orgs') if x.isdigit()]))
            conn = qcm.start_attempt(
                check, user=request.user, request=request, requested_scopes=request.POST.get('requested_scopes', ''),
                organizations=orgs, destination_addresses=request.POST.get('destination_addresses', ''),
                allow_private=allow_private, ca_pem=ca_pem,
                spki_pin=(request.POST.get('spki_pin') or '').strip()[:60],
                egress_confirmed=request.POST.get('egress_confirmed') == 'on')
            return redirect('connect:qc_attempt', pk=conn.pk)
    except qcm.QuickConnectError as e:
        ctx['error'] = e.message
    return render(request, 'connect/quick_connect.html', ctx)


def _attempt(pk):
    from .models import Connection
    return get_object_or_404(Connection, pk=pk, qc_revision=qcm.qc.REVISION, direction=Connection.OUTBOUND)


@qc_page
def qc_attempt(request, pk):
    from .models import Connection
    conn = _attempt(pk)
    if request.method == 'POST':
        op = request.POST.get('op')
        try:
            if op == 'confirm':
                if request.POST.get('approve_peer') != 'on':
                    raise qcm.QuickConnectError('peer_unconfirmed', 'Tick the box to approve the other '
                                                                    'application\'s address first.')
                qcm.confirm_peer(conn, request.user, private_ok=request.POST.get('private_peer') == 'on')
                messages.success(request, 'Exchanged. Compare the code below with the one the other administrator '
                                          'sees before either of you approves.')
            elif op == 'cancel':
                qcm.cancel(conn, request.user)
                messages.info(request, 'Cancelled. Everything this attempt allowed was removed.')
            else:
                raise Http404
        except qcm.QuickConnectError as e:
            messages.error(request, e.message)
        return redirect('connect:qc_attempt', pk=conn.pk)
    inv = getattr(conn, 'qc_invitation', None)
    if conn.state == Connection.PENDING_PAIRING and inv and not inv.callback_at:
        step = 2
    elif conn.state == Connection.PENDING_PAIRING:
        step = 3
    else:
        step = 4
    ctx = _qc_ctx(request, step=step, conn=conn, inv=inv, screen=step,
                  authorize_link=qcm.authorization_url(request, conn) if step == 2 else '',
                  peer_egress=qcm.peer_egress_rows(conn) if step == 3 else [])
    return render(request, 'connect/quick_connect.html', ctx)


@qc_page
def qc_callback(request):
    try:
        conn = qcm.handle_callback(request)
    except qcm.QuickConnectError as e:
        return render(request, 'connect/quick_connect.html',
                      _qc_ctx(request, step=3, error=e.message, error_code=e.code, callback_error=True), status=400)
    return redirect('connect:qc_attempt', pk=conn.pk)


@login_required
def qc_authorize(request):
    """Responder entry point (PROTOCOL-1.1.md §5.2): a web page of THIS
    installation's admin UI, under the site firewall, login and 2FA. Not a
    Connect API route, so the Connect source policy does not apply to it.
    It never approves anything by itself."""
    if not qcm.enabled_here():
        raise Http404
    if not user_has_perm(request.user, 'manage_app_connections'):
        raise PermissionDenied
    data = request.POST if request.method == 'POST' else request.GET
    invitation, state = str(data.get('invitation', ''))[:8192], str(data.get('state', ''))[:200]
    ctx = _ctx(request, steps=['Review the request', 'Approve temporary access', 'Compare codes'], step=0,
               invitation=invitation, state=state)
    try:
        if request.method == 'POST':
            op = request.POST.get('op')
            if op not in ('approve', 'deny'):
                raise Http404
            url = qcm.decide(request, invitation, state, approve=op == 'approve',
                             private_ok=request.POST.get('private_ok') == 'on')
            return HttpResponseRedirect(url, status=303)
        review = qcm.review_invitation(request, invitation, state)
    except qcm.QuickConnectError as e:
        ctx.update(error=e.message, error_code=e.code)
        if e.code in ('reauth_required', 'invalid_egress'):
            try:
                review = qcm.review_invitation(request, invitation, state)
            except qcm.QuickConnectError:
                return render(request, 'connect/qc_authorize.html', ctx, status=400)
        else:
            return render(request, 'connect/qc_authorize.html', ctx, status=400)
    from tech_access.protected import has_fresh_auth
    ctx.update(review=review, claims=review.claims, fresh=has_fresh_auth(request),
               own_egress=[e.get('net') for e in identity.get().egress_addresses or []],
               reauth_url=reverse('connect:reauth') + '?' + urlencode({'next': request.get_full_path()}),
               scope_rows=[{'name': s, 'scope': catalog.CATALOG.get(s)} for s in review.known_scopes])
    return render(request, 'connect/qc_authorize.html', ctx)


@login_required
def reauth(request):
    """Confirm this installation's own password (and authenticator code) for
    the next few minutes (tech_access fresh re-authentication). Only a local
    path is accepted as the place to go back to."""
    if not identity.enabled():
        raise Http404
    nxt = request.POST.get('next') or request.GET.get('next') or reverse('connect:index')
    if not nxt.startswith('/') or not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                                                     require_https=request.is_secure()):
        nxt = reverse('connect:index')
    error = ''
    if request.method == 'POST':
        from tech_access.protected import reauthenticate
        error = reauthenticate(request, request.POST.get('password', ''), request.POST.get('otp', ''))
        if not error:
            return redirect(nxt)
    return render(request, 'connect/reauth.html', _ctx(request, next=nxt, error=error))
