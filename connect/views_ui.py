"""
Administration → Integrations → Connected Applications.

  index            catalog, connections, pending approvals, kill switch
  connect_app      wizard (outbound): Connect Application → Verify Identity → Pair
  invite           inbound: invitation code + QR for the other app to enter
  request_review   inbound: compare the code, approve permissions, select customers
  detail           status, approve (outbound), customers, test, keys, activity,
                   rotate, suspend / resume, disconnect, revoke, Network section
                   (this connection's source rules, observed sources, refusals)
  network          installation-level source allowlist, staged changes, test
                   an address, observe period (Quick Connect B1)
  change           approve / reject / roll back one staged network change

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
        invitations=PairingInvitation.objects.all()[:10], qc_enabled=_qc_on()))


def _qc_on():
    from . import quick_connect
    return quick_connect.enabled_here()


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
    problem = identity.public_url_problem()
    if problem:   # pairing would send this installation's address; refuse without it
        ctx.update(error=problem, not_configured=True)
        return render(request, 'connect/wizard.html', ctx)
    if request.method != 'POST':
        return render(request, 'connect/wizard.html', ctx)
    adv = _advanced(request)
    ctx.update(adv, peer_sources=request.POST.get('peer_sources', '')[:300])
    op = request.POST.get('op')
    try:
        pv = pairing.preview_destination(request.POST.get('url', ''), allow_private=adv['allow_private'],
                                         ca_pem=adv['ca_pem'])
        ctx.update(destination=pv, dest_name=app['name'],
                   destination_addresses=request.POST.get('destination_addresses', '')[:600]
                   or ', '.join(pv.addresses))
        info = pairing.discover(request.POST.get('url', ''), allow_private=adv['allow_private'],
                                ca_pem=adv['ca_pem'], addresses=pv.addresses)
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
                                          rotation_interval_days=adv['rotation_days'],
                                          peer_sources=request.POST.get('peer_sources', ''),
                                          private_sources=request.POST.get('private_sources') == 'on',
                                          destination_addresses=request.POST.get('destination_addresses', ''),
                                          spki_pin=(request.POST.get('spki_pin') or '').strip()[:60])
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
    problem = identity.public_url_problem()
    if problem:
        ctx['error'] = problem
        return render(request, 'connect/invite.html', ctx)
    if request.method == 'POST':
        try:
            inv, code = pairing.create_invitation(request.user, label=request.POST.get('label', ''),
                                                  peer_sources=request.POST.get('peer_sources', ''),
                                                  private_sources=request.POST.get('private_sources') == 'on')
        except pairing.PairingFailed as e:
            messages.error(request, e.message)
            return redirect('connect:index')
        ctx['sources'] = [{'network': r.network, 'installation_ok': _installation_allows(r.network)}
                          for r in inv.source_rules.all()]
        base = identity.configured_public_url()
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
               organizations=_orgs(request), proposed=conn.proposed_tenants, step=4,
               duplicates=list(pairing.duplicate_connections(conn)) if preq.status == PairingRequest.PENDING else [],
               public_url_problem=identity.public_url_problem(),
               qc_grant=getattr(conn, 'qc_grant', None) if conn.qc_revision else None)
    if request.method == 'POST':
        try:
            if request.POST.get('op') == 'lookup':
                # An explicit administrator action (never on GET): contact the
                # address the code holder supplied and offer its permissions.
                if preq.status != PairingRequest.PENDING:
                    raise pairing.PairingFailed('This pairing request is no longer waiting for a decision.')
                if identity.kill_switch_engaged():
                    raise pairing.PairingFailed(pairing.FRIENDLY['kill_switch'], 'kill_switch')
                conn.allow_private_network = request.POST.get('allow_private') == 'on'
                conn.tls_ca_bundle = (request.POST.get('ca_pem') or '').strip()[:20000]
                pv = pairing.preview_destination(conn.base_url, allow_private=conn.allow_private_network,
                                                 ca_pem=conn.tls_ca_bundle)
                request.session[f'connect_dest_preview_{preq.pk}'] = {
                    'host': pv.host, 'port': pv.port, 'addresses': pv.addresses, 'cert_names': pv.cert_names,
                    'spki': pv.spki, 'error': pv.error}
                try:
                    pairing.refresh_remote_discovery(conn, addresses=pv.addresses)
                except ConnectError as e:
                    raise pairing.PairingFailed('Clientst0r could not look up the other application: '
                                                + pairing.friendly(e), e.code) from e
                conn.save(update_fields=['remote_endpoints', 'remote_catalog', 'remote_protocol_version',
                                         'remote_app_version', 'allow_private_network', 'tls_ca_bundle',
                                         'updated_at'])
                messages.success(request, 'Looked up the other application. Choose what Clientst0r asks in '
                                          'return, if anything.')
                return redirect('connect:request_review', pk=preq.pk)
            if request.POST.get('op') == 'reject':
                pairing.reject_inbound(preq, request.user)
                messages.info(request, 'Pairing rejected. The other application will be told.')
                return redirect('connect:index')
            change = pairing.approve_inbound(
                preq, scopes=request.POST.getlist('scopes'), grants=_parse_grants(request, request.POST.getlist('scopes')),
                requested_scopes=request.POST.getlist('requested_scopes'), user=request.user, request=request,
                allow_private=request.POST.get('allow_private') == 'on',
                ca_pem=(request.POST.get('ca_pem') or '').strip()[:20000],
                destination_addresses=request.POST.get('destination_addresses', ''),
                spki_pin=(request.POST.get('spki_pin') or '').strip()[:60])
            if change is not None:
                messages.warning(request, 'This approval needs a second administrator (high-risk permissions, '
                                          'or an installation id that is already connected here). Confirm the '
                                          'protected change, then another approver approves it.')
                return redirect('tech_access:change_detail', pk=change.pk)
            messages.success(request, 'Approved. The other application completes the pairing on its next check.')
            return redirect('connect:detail', pk=conn.pk)
        except pairing.PairingFailed as e:
            ctx['error'] = e.message
        conn.refresh_from_db()
    # GET never contacts the other application (QC-11): the "Look up the other
    # application" button posts op=lookup.
    if conn.remote_catalog:
        ctx['remote_groups'] = _grouped(pairing.catalog_for(conn))
    pv = request.session.get(f'connect_dest_preview_{preq.pk}')
    if pv:
        ctx.update(destination=pv, destination_addresses=request.POST.get('destination_addresses', '')[:600]
                   or ', '.join(pv.get('addresses', [])))
    ctx['dest_name'] = conn.remote_display_name or conn.remote_app_type
    return render(request, 'connect/request_review.html', ctx)


@page()
def detail(request, pk):
    from .models import Connection, ConnectAuditEvent
    conn = get_object_or_404(Connection, pk=pk)
    if request.method == 'POST':
        if request.POST.get('op', '') in ('propose_rule', 'propose_remove', 'approve_observed',
                                          'propose_destination'):
            _network_post(request, conn)
            return redirect('connect:detail', pk=conn.pk)
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
        qc_grant=getattr(conn, 'qc_grant', None) if conn.qc_revision else None,
        qc_invitation=getattr(conn, 'qc_invitation', None) if conn.qc_revision else None,
        step={Connection.AWAITING_REMOTE: 3, Connection.AWAITING_LOCAL: 4, Connection.AWAITING_SECOND: 4,
              Connection.ACTIVE: 7}.get(conn.state, 0), **_network_ctx(conn), **_destination_ctx(conn))
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
        elif op == 'retest':
            from . import destinations
            ok = destinations.retest(conn, request.user)
            (messages.success if ok else messages.warning)(
                request, 'Retest passed; the connection is active again.' if ok else
                'Still blocked: approve the new address first, and every check must pass.')
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


# --- Network: source rules (Quick Connect B1) ------------------------------------------

def _installation_allows(network) -> bool:
    from . import source_policy
    return source_policy.installation_allows(network)


def _reauth(request):
    """Inline re-authentication for approving network changes."""
    password = request.POST.get('password', '')
    if password:
        from tech_access.protected import reauthenticate
        error = reauthenticate(request, password, request.POST.get('otp', ''))
        if error:
            raise _Refused(error)


class _Refused(Exception):
    pass


def _entry_from_post(request, layer, connection=None):
    from datetime import timedelta
    from django.utils import timezone
    hours = request.POST.get('expires_hours', '').strip()
    expires = None
    if hours:
        try:
            expires = timezone.now() + timedelta(hours=max(1, min(24 * 90, int(hours))))
        except ValueError:
            raise _Refused('Expiry must be a number of hours.')
    return {'layer': layer, 'connection': str(connection.pk) if connection else '',
            'network': request.POST.get('network', ''), 'action': request.POST.get('action', 'allow'),
            'private': request.POST.get('private') == 'on', 'purpose': 'all', 'expires_at': expires,
            'description': request.POST.get('description', '')}


def _network_post(request, connection=None):
    """Shared POST handling for the Network page and a connection's Network
    section. Returns None (caller redirects)."""
    from django.core.exceptions import ValidationError
    from .models import SourceRule
    from . import source_policy
    op = request.POST.get('op', '')
    layer = SourceRule.CONNECTION if connection is not None else SourceRule.INSTALLATION
    try:
        if op == 'propose_rule':
            change = source_policy.propose(add=[_entry_from_post(request, layer, connection)], user=request.user,
                                           connection=connection, note=request.POST.get('description', ''))
            messages.info(request, f'Change #{change.pk} staged. Review the preview below and approve it.')
        elif op == 'propose_remove':
            rule = get_object_or_404(SourceRule, pk=request.POST.get('rule'), layer=layer,
                                     connection=connection, status__in=(SourceRule.ACTIVE, SourceRule.TEMPORARY))
            change = source_policy.propose(remove=[rule.pk], user=request.user, connection=connection)
            messages.info(request, f'Change #{change.pk} staged (removes {rule.network}).')
        elif op == 'approve_observed' and connection is not None:
            obs = get_object_or_404(SourceRule, pk=request.POST.get('rule'), connection=connection,
                                    status=SourceRule.OBSERVED)
            add = [{'layer': SourceRule.CONNECTION, 'connection': str(connection.pk), 'network': obs.network,
                    'private': request.POST.get('private') == 'on', 'description': 'Approved observed address'}]
            if not _installation_allows(obs.network):
                add.append({'layer': SourceRule.INSTALLATION, 'network': obs.network,
                            'private': request.POST.get('private') == 'on',
                            'description': f'Observed for {connection.remote_display_name or connection.pk}'})
            change = source_policy.propose(add=add, user=request.user, connection=connection,
                                           note='Approve observed address')
            messages.info(request, f'Change #{change.pk} staged. It widens access, so a second administrator '
                                   'approves it.')
        elif op == 'propose_destination' and connection is not None:
            from . import destinations
            change = destinations.propose_change(connection, request.POST.get('destination_addresses', ''),
                                                 request.user,
                                                 private=request.POST.get('private_destination') == 'on')
            messages.info(request, f'Destination change #{change.pk} staged. Review it below and approve it'
                                   + (' (a second administrator approves a private address or a range).'
                                      if change.widening else '.'))
        elif op == 'set_egress' and connection is None:
            from . import quick_connect
            quick_connect.set_own_egress(quick_connect.parse_egress_text(request.POST.get('egress', '')),
                                         request.user)
            messages.success(request, 'Egress address saved.')
        elif op in ('qc_on', 'qc_off') and connection is None:
            from . import quick_connect
            if op == 'qc_on':
                _reauth(request)
                from tech_access.protected import has_fresh_auth
                if not has_fresh_auth(request):
                    raise _Refused('Re-enter your password to turn Quick Connect on.')
            quick_connect.set_enabled(op == 'qc_on', request.user)
            messages.success(request, 'Quick Connect is ' + ('on.' if op == 'qc_on' else 'off.'))
        elif op == 'enforce' and connection is None:
            _reauth(request)
            from tech_access.protected import has_fresh_auth
            if not has_fresh_auth(request):
                raise _Refused('Re-enter your password to end the observe period.')
            source_policy.enforce_now(request.user)
            messages.warning(request, 'Source rules are enforced now for every connection.')
        else:
            raise Http404
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))
    except (_Refused, source_policy.ChangeRefused) as e:
        messages.error(request, str(e) if isinstance(e, _Refused) else e.message)
    return None


def _destination_ctx(conn):
    from . import destinations
    d = destinations.get(conn)
    ev = conn.security_block_detail or {}
    return {'dest': d, 'block_message': destinations.message(conn.security_block_code, conn, ev)
            if conn.security_block_code else '',
            'suggested_addresses': ', '.join(ev.get('addresses', [])) if conn.state == conn.SECURITY_BLOCKED
            else ', '.join(d.nets if d else [])}


def _network_ctx(connection=None):
    from .models import ConnectChange, SourceRule
    from . import source_policy
    rules = SourceRule.objects.filter(connection=connection) if connection is not None else \
        SourceRule.objects.filter(layer=SourceRule.INSTALLATION)
    changes = ConnectChange.objects.filter(connection=connection) if connection is not None else \
        ConnectChange.objects.filter(connection__isnull=True)
    return {'source_rules': rules.filter(status__in=(SourceRule.ACTIVE, SourceRule.TEMPORARY)).order_by(
                'action', 'network'),
            'observed': rules.filter(status=SourceRule.OBSERVED).order_by('-last_matched_at'),
            'staged_changes': changes.filter(status__in=(ConnectChange.STAGED, ConnectChange.AWAITING_SECOND)),
            'applied_changes': changes.filter(status__in=(ConnectChange.APPLIED, ConnectChange.ROLLED_BACK))[:10],
            'refusals': source_policy.recent_refusals(connection),
            'observe': source_policy.observe_status()}


@page()
def network(request):
    from . import source_policy
    if request.method == 'POST':
        _network_post(request)
        return redirect('connect:network')
    ctx = _ctx(request, **_network_ctx())
    ip = request.GET.get('test_ip', '').strip()
    if ip:
        from django.core.exceptions import ValidationError
        try:
            ctx['test_result'] = source_policy.test_address(ip, request.GET.get('test_connection', ''))
        except ValidationError as e:
            ctx['test_error'] = ' '.join(e.messages)
        except source_policy.PolicyUnavailable:
            ctx['test_error'] = 'The policy could not be loaded.'
    from .models import Connection
    ctx['connections'] = Connection.objects.exclude(state__in=(Connection.REVOKED, Connection.FAILED))
    return render(request, 'connect/network.html', ctx)


@page(manage=True)
@require_POST
def change(request, pk):
    from .models import ConnectChange
    from . import source_policy
    ch = get_object_or_404(ConnectChange, pk=pk)
    back = redirect('connect:detail', pk=ch.connection_id) if ch.connection_id else redirect('connect:network')
    op = request.POST.get('op')
    try:
        _reauth(request)
        if ch.kind == ConnectChange.DESTINATION:
            from . import destinations
            mod = destinations
        else:
            mod = source_policy
        if op == 'approve':
            pc = mod.approve(ch, request)
            if pc is not None:
                messages.warning(request, 'This change widens access: confirm the protected change, then a second '
                                          'administrator approves it.')
                return redirect('tech_access:change_detail', pk=pc.pk)
            messages.success(request, f'Change #{ch.pk} applied.')
            if ch.kind == ConnectChange.DESTINATION and ch.connection_id:
                from . import destinations
                if destinations.retest(ch.connection, request.user):
                    messages.success(request, 'Retest passed: the connection is active again.')
        elif op == 'reject':
            mod.reject(ch, request.user)
            messages.info(request, f'Change #{ch.pk} rejected.')
        elif op == 'rollback' and mod is source_policy:
            rb = source_policy.rollback(ch, request)
            messages.info(request, f'Rolled back (change #{rb.pk}). Rollback only ever narrows access.')
        else:
            raise Http404
    except (_Refused, source_policy.ChangeRefused) as e:
        messages.error(request, str(e) if isinstance(e, _Refused) else e.message)
    return back
