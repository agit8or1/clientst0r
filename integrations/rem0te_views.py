"""
Settings → RMM → Rem0te: the setup wizard.

One page for ClientSt0r's instance-wide Rem0te identity (peer id, audiences,
keys, the peers-file entry) and, for each Rem0te connection the viewer may
manage, its status (Connected / Degraded / Disconnected / Authentication
Problem / Configuration Required), a checklist of what is in place and what
is missing, and a Test connection button. Superusers only: the identity
serves every organization.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.middleware import get_request_organization

from .models import RMMConnection


def _superuser(u):
    return u.is_active and u.is_superuser


def _connections(request):
    org = get_request_organization(request)
    qs = RMMConnection.objects.filter(provider_type='rem0te').select_related('organization').order_by(
        'organization__name', 'name')
    return qs.filter(organization=org) if org is not None else qs


@login_required
@user_passes_test(_superuser)
def rem0te_setup(request):
    from .rem0te import health, identity, pairing, setup
    ident = identity.get(create=False)
    rows = []
    for conn in _connections(request):
        rows.append({'connection': conn, 'status': health.evaluate(conn), 'checklist': setup.checklist(conn),
                     'organization_id': pairing.organization_id(conn),
                     'check': pairing.last_check(conn)})
    return render(request, 'integrations/rem0te_setup.html', {
        'identity': identity.public_view(ident), 'peer_entry': identity.peer_entry_json(None, []),
        'rows': rows, 'pin': pairing.pin(), 'implemented_revision': pairing.IMPLEMENTED_REVISION,
        'active_page': 'rmm_rem0te',
    })


@login_required
@user_passes_test(_superuser)
@require_POST
def rem0te_setup_test(request, pk):
    from audit.models import AuditLog
    from .rem0te import health, setup
    conn = _connections(request).filter(pk=pk).first()
    if conn is None:
        raise Http404
    result = setup.test_connection(conn, request.user)
    st = health.evaluate(conn)
    AuditLog.log(user=request.user, action='api_call', organization=conn.organization, object_type='rmm_connection',
                 object_id=conn.pk, object_repr=conn.name[:255], path=request.path,
                 description=f'Rem0te Test connection: {st["label"]}',
                 extra_data={'state': st['state'], 'code': result['check'].get('code', '')})
    first = st['reasons'][0] if st['reasons'] else None
    text = f'{conn.name}: {st["label"]}.' + (f' {first["message"]}' if first else '')
    if result.get('technician'):
        text += f' {result["technician"]["message"]}'
    (messages.success if st['state'] == health.CONNECTED else messages.warning)(request, text[:900])
    return redirect('integrations:rem0te_setup')


@login_required
@user_passes_test(_superuser)
@require_POST
def rem0te_setup_identity(request):
    from .rem0te import identity
    op = request.POST.get('op', '')
    try:
        if op == 'generate':
            if identity.has_keys():
                messages.info(request, 'ClientSt0r already has Rem0te keys.')
            else:
                identity.generate_keys(by=request.user)
                messages.success(request, "ClientSt0r's Rem0te keys were generated.")
        elif op == 'update':
            identity.update(identity.get(), peer_id=request.POST.get('peer_id', ''),
                            audience=request.POST.get('audience', ''),
                            public_base_url=request.POST.get('public_base_url', ''), by=request.user)
            messages.success(request, "ClientSt0r's Rem0te identity was saved.")
        elif op == 'stage':
            identity.stage_next_keys(by=request.user)
            messages.success(request, 'Next keys staged. Add them to the peers file (the entry below lists both), '
                                      'restart Rem0te, then press "Switch to the next keys".')
        elif op == 'promote':
            identity.promote_next_keys(by=request.user)
            messages.success(request, 'ClientSt0r now signs with the new keys. Remove the old ones from the peers '
                                      'file at the next Rem0te restart.')
        elif op == 'discard':
            identity.discard_next_keys(by=request.user)
            messages.info(request, 'The staged keys were discarded.')
        else:
            messages.error(request, 'Unknown action.')
    except identity.IdentityError as e:
        messages.error(request, str(e))
    return redirect('integrations:rem0te_setup')
