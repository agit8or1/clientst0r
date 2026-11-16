"""
Administration → Integrations → Connected Applications.

  index            catalog, connections, pending approvals, kill switch
  connect_app      wizard (outbound): Connect Application → Verify Identity → Pair
  invite           inbound: invitation code + QR for the other app to enter
  request_review   inbound: compare the code, approve permissions, select customers
  detail           status, approve (outbound), customers, test, keys, activity,
                   rotate, suspend / resume, disconnect, revoke

GET needs view_app_connections, POST manage_app_connections (MSP staff
only). Every page 404s while AGIT8OR_CONNECT_ENABLED is off. No page ever
renders a private key; a pairing code is shown once, when it is created.
"""
from __future__ import annotations

import functools

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permission_utils import user_has_perm
from agit8or_connect import pairing as sdk_pairing
from agit8or_connect.errors import ConnectError
from agit8or_connect.scopes import Catalog, RISKS

from . import catalog, identity, lifecycle, pairing

RISK_LABELS = {'read': 'Read', 'write': 'Change', 'high_risk': 'High risk — needs a second administrator',
               'admin': 'Administration — needs a second administrator'}
STEPS = ['Select application', 'Connect application', 'Verify identity', 'Pair', 'Approve permissions',
         'Select customers', 'Test connection', 'Complete']


def page(manage=False):
    def deco(fn):
        @login_required
        @functools.wraps(fn)
        def wrapper(request, *args, **kwargs):
            if not identity.enabled():
                raise Http404
            need = 'manage_app_connections' if (manage or request.method == 'POST') else 'view_app_connections'
            if not user_has_perm(request.user, need):
                raise PermissionDenied
            return fn(request, *args, **kwargs)
        return wrapper
    return deco


def _ctx(request, **extra):
    from .models import InstallationIdentity
    ident = identity.get()
    out = {'identity': ident, 'can_manage': user_has_perm(request.user, 'manage_app_connections'),
           'kill_switch': InstallationIdentity.objects.filter(pk=ident.pk, kill_switch_engaged=True).exists(),
           'steps': STEPS, 'active_page': 'connect'}
    out.update(extra)
    return out


def _grouped(cat: Catalog, names=None):
    return [{'risk': r, 'label': RISK_LABELS[r], 'scopes': cat.grouped(names)[r]} for r in RISKS
            if cat.grouped(names)[r]]


def _orgs(request):
    from core.models import Organization
    return Organization.objects.filter(is_active=True).order_by('name') \
        if hasattr(Organization, 'is_active') else Organization.objects.order_by('name')


@page()
def index(request):
    from .models import Connection, PairingInvitation, PairingRequest
    conns = Connection.objects.exclude(state=Connection.FAILED).order_by('remote_display_name')
    return render(request, 'connect/index.html', _ctx(
        request, applications=catalog.APPLICATIONS, connections=conns,
        failed=Connection.objects.filter(state=Connection.FAILED)[:10],
        pending=PairingRequest.objects.filter(status__in=(PairingRequest.PENDING, PairingRequest.AWAITING_SECOND))
        .select_related('connection'),
        invitations=PairingInvitation.objects.all()[:10]))


def _advanced(request):
    return {'allow_private': request.POST.get('allow_private') == 'on',
            'ca_pem': (request.POST.get('ca_pem') or '').strip()[:20000],
            'rotation_days': max(7, min(365, int(request.POST.get('rotation_days') or 90)))}


@page()
def connect_app(request, app_type):
    app = catalog.APPLICATIONS_BY_TYPE.get(app_type)
    if app is None or app['status'] != 'available':
        raise Http404
    ctx = _ctx(request, app=app, step=1, url=request.POST.get('url', ''))
    if request.method != 'POST':
        return render(request, 'connect/wizard.html', ctx)
    adv = _advanced(request)
    ctx.update(adv)
    op = request.POST.get('op')
    try:
        info = pairing.discover(request.POST.get('url', ''), allow_private=adv['allow_private'],
                                ca_pem=adv['ca_pem'])
        if app_type != 'other' and info.app_type != app_type:
            raise pairing.PairingFailed(f'That address is a "{info.app_type}" application, not {app["name"]}.')
        ctx.update(step=2, info=info, groups=_grouped(info.catalog), defaults=info.catalog.default_set(),
                   organizations=_orgs(request))
        if op == 'pair':
            scopes = request.POST.getlist('scopes')
            orgs = list(_orgs(request).filter(pk__in=[int(x) for x in request.POST.getlist('orgs') if x.isdigit()]))
            conn = pairing.start_outbound(info, request.POST.get('pairing_secret', ''), requested_scopes=scopes,
                                          organizations=orgs, user=request.user,
                                          allow_private=adv['allow_private'], ca_pem=adv['ca_pem'],
                                          rotation_interval_days=adv['rotation_days'])
            messages.success(request, 'Pairing request sent. Compare the code below with the one the other '
                                      'application shows, then ask its administrator to approve.')
            return redirect('connect:detail', pk=conn.pk)
    except pairing.PairingFailed as e:
        ctx['error'] = e.message
    return render(request, 'connect/wizard.html', ctx)


def _qr_svg(text):
    import qrcode
    import qrcode.image.svg
    return qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8).to_string().decode()


@page()
def invite(request):
    ctx = _ctx(request)
    if request.method == 'POST':
        try:
            inv, code = pairing.create_invitation(request.user, label=request.POST.get('label', ''))
        except pairing.PairingFailed as e:
            messages.error(request, e.message)
            return redirect('connect:index')
        base = identity.public_base(request)
        ctx.update(invitation=inv, code=code, discovery_url=base,
                   qr=_qr_svg(sdk_pairing.qr_payload(base, code, identity.installation_id())))
    return render(request, 'connect/invite.html', ctx)


def _parse_grants(request, allowed):
    """Rows of the customer table: org_<i> (our org pk), tenant_<i>, scope_<i>
    (multi). A row's scopes are limited to `allowed` (the connection-level
    selection), so unticking a permission above also removes it per customer."""
    allowed = set(allowed)
    out = []
    for i in range(min(int(request.POST.get('grant_rows') or 0), 500)):
        org = request.POST.get(f'org_{i}', '')
        tenant = (request.POST.get(f'tenant_{i}') or '').strip()
        if org.isdigit() and tenant:
            out.append((int(org), tenant, [x for x in request.POST.getlist(f'scope_{i}') if x in allowed]))
    return out


def _with_org_pk(rows):
    out = []
    for r in rows or []:
        r = dict(r)
        rt = str(r.get('remote_tenant') or '')
        r['org_pk'] = int(rt[4:]) if rt.startswith('org-') and rt[4:].isdigit() else None
        r.setdefault('id', str(r.get('local_tenant') or ''))   # the peer's id for that customer
        r.setdefault('label', '')
        out.append(r)
    return out


@page()
def request_review(request, pk):
    from .models import PairingRequest
    preq = get_object_or_404(PairingRequest.objects.select_related('connection'), pk=pk)
    conn = preq.connection
    asked = [s for s in conn.peer_requested_scopes if catalog.CATALOG.get(s)]
    ctx = _ctx(request, preq=preq, conn=conn, groups=_grouped(catalog.CATALOG, asked),
               unknown=[s for s in conn.peer_requested_scopes if not catalog.CATALOG.get(s)],
               organizations=_orgs(request), proposed=conn.proposed_tenants, step=4)
    if request.method == 'POST':
        try:
            if request.POST.get('op') == 'reject':
                pairing.reject_inbound(preq, request.user)
                messages.info(request, 'Pairing rejected. The other application will be told.')
                return redirect('connect:index')
            change = pairing.approve_inbound(
                preq, scopes=request.POST.getlist('scopes'), grants=_parse_grants(request, request.POST.getlist('scopes')),
                requested_scopes=request.POST.getlist('requested_scopes'), user=request.user, request=request,
                allow_private=request.POST.get('allow_private') == 'on',
                ca_pem=(request.POST.get('ca_pem') or '').strip()[:20000])
            if change is not None:
                messages.warning(request, 'High-risk permissions need a second administrator. Confirm the '
                                          'protected change, then another approver approves it.')
                return redirect('tech_access:change_detail', pk=change.pk)
            messages.success(request, 'Approved. The other application completes the pairing on its next check.')
            return redirect('connect:detail', pk=conn.pk)
        except pairing.PairingFailed as e:
            ctx['error'] = e.message
        conn.refresh_from_db()
    if not conn.remote_catalog and preq.status == PairingRequest.PENDING and request.method == 'GET':
        try:   # an administrator opened the page: look the other app up to offer its permissions
            pairing.refresh_remote_discovery(conn)
            conn.save(update_fields=['remote_endpoints', 'remote_catalog', 'remote_protocol_version',
                                     'remote_app_version', 'updated_at'])
        except ConnectError as e:
            ctx['discovery_problem'] = pairing.friendly(e)
    if conn.remote_catalog:
        ctx['remote_groups'] = _grouped(pairing.catalog_for(conn))
    return render(request, 'connect/request_review.html', ctx)


@page()
def detail(request, pk):
    from .models import Connection, ConnectAuditEvent
    conn = get_object_or_404(Connection, pk=pk)
    if request.method == 'POST':
        return _detail_post(request, conn)
    cat = pairing.catalog_for(conn)
    activity = ConnectAuditEvent.objects.filter(connection_id=str(conn.pk))[:30]
    ctx = _ctx(request, conn=conn, keys=conn.keys.all()[:10], grants=conn.tenant_grants.select_related(
        'organization').order_by('-active', 'organization__name'), activity=activity,
        deliveries=conn.outbound_events.all()[:15], inbound=conn.inbound_events.all()[:15],
        inbound_groups=_grouped(catalog.CATALOG, conn.inbound_scopes),
        outbound_groups=_grouped(cat, conn.outbound_scopes),
        approve_groups=_grouped(catalog.CATALOG, [s for s in conn.peer_requested_scopes if catalog.CATALOG.get(s)]),
        organizations=_orgs(request), remote_grants=_with_org_pk(conn.remote_tenant_grants),
        step={Connection.AWAITING_REMOTE: 3, Connection.AWAITING_LOCAL: 4, Connection.AWAITING_SECOND: 4,
              Connection.ACTIVE: 7}.get(conn.state, 0))
    return render(request, 'connect/detail.html', ctx)


def _detail_post(request, conn):
    from .models import TenantGrant
    op = request.POST.get('op', '')
    back = redirect('connect:detail', pk=conn.pk)
    try:
        if op == 'poll':
            status = pairing.poll(conn)
            {'pending': lambda: messages.info(request, 'Still waiting for the other administrator to approve.'),
             'approved': lambda: messages.success(request, 'Approved by the other application. Now approve '
                                                           'what it asks for here and select customers.'),
             'rejected': lambda: messages.error(request, 'The other application\'s administrator rejected '
                                                         'the pairing.')}.get(status, lambda: None)()
        elif op == 'approve_local':
            change = pairing.approve_local(conn, scopes=request.POST.getlist('scopes'),
                                           grants=_parse_grants(request, request.POST.getlist('scopes')), user=request.user,
                                           request=request)
            if change is not None:
                messages.warning(request, 'High-risk permissions need a second administrator.')
                return redirect('tech_access:change_detail', pk=change.pk)
            messages.success(request, 'Connected. Run Test connection to check every part of the link.')
        elif op == 'test':
            report = lifecycle.test_connection(conn, request.user)
            (messages.success if report['ok'] else messages.warning)(
                request, 'All checks passed.' if report['ok'] else 'Some checks failed — see the report below.')
        elif op == 'rotate':
            ok = lifecycle.rotate(conn, request.user)
            (messages.success if ok else messages.warning)(
                request, 'New key in use; the old key is accepted until the overlap ends.' if ok else
                'The other application did not accept the new key. The current key stays in use.')
        elif op == 'suspend':
            lifecycle.suspend(conn, request.user)
            messages.info(request, 'Suspended. Nothing is exchanged until you resume it.')
        elif op == 'resume':
            lifecycle.resume(conn, request.user)
            messages.success(request, 'Resumed.')
        elif op == 'disconnect':
            notified = lifecycle.disconnect(conn, request.user)
            messages.info(request, 'Disconnected. Customer records and history are kept.' +
                          ('' if notified else ' The other application could not be told; revoke it there too.'))
        elif op == 'revoke':
            lifecycle.revoke(conn, request.user)
            messages.warning(request, 'Revoked immediately. Customer records and history are kept.')
        elif op == 'revoke_grant':
            g = get_object_or_404(TenantGrant, pk=request.POST.get('grant'), connection=conn)
            lifecycle.revoke_grant(g, request.user)
            messages.info(request, f'{g.organization.name} is no longer reachable through this connection.')
        elif op == 'add_grant':
            grants = pairing._validate_grants(conn.inbound_scopes, _parse_grants(request, conn.inbound_scopes))
            if conn.state != conn.ACTIVE:
                raise pairing.PairingFailed('Customers can be added only to an active connection.')
            pairing._apply_grants(conn, grants, request.user)
            messages.success(request, 'Customer granted.')
        else:
            raise Http404
    except pairing.PairingFailed as e:
        messages.error(request, e.message)
    except ConnectError as e:
        messages.error(request, pairing.friendly(e))
    return back


@page(manage=True)
@require_POST
def kill_switch(request):
    if request.POST.get('op') == 'release':
        lifecycle.release_kill_switch(request.user)
        messages.success(request, 'Kill switch released. Resume each connection you want back.')
    else:
        n = lifecycle.engage_kill_switch(request.user)
        messages.warning(request, f'Kill switch engaged: {n} connection(s) suspended, every Connect API call '
                                  'is refused.')
    return redirect('connect:index')
