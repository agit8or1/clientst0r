"""Access removal verification for offboarding runbooks (Phase 38).

Read-only checks that a departing person's access is really gone, run from
an offboarding execution for the person named on it (subject_email, and/or
subject_user):

    clientst0r  memberships of this customer, portal sign-in, vault items
                shared to them, user-scoped vault allow rules, API keys,
                browser-extension tokens pinned to the customer, and app
                sign-ins that could still reach the customer
    m365        each active Microsoft 365 connection of the customer (Graph,
                GET only): does the user still exist, is sign-in enabled,
                are licenses still assigned
    rmm         each RMM connection of the customer. The ticket-rmm-v1
                contract defines no account-read capability, so nothing can
                be read there yet: recorded as "not verifiable" and left to
                the runbook's manual stages.

Nothing here changes anything in ClientSt0r or in a connected system. Every
run writes one AccessRemovalCheck per system checked and an execution audit
entry (which also lands in the main audit log).
"""
from __future__ import annotations

import logging

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger('processes')


def _f(item, state, detail=''):
    return {'item': item, 'state': state, 'detail': detail}


def _status(findings):
    return 'orphaned' if any(f['state'] == 'active' for f in findings) else 'removed'


def subject_users(execution):
    """ClientSt0r accounts that belong to the departing person."""
    users = {}
    if execution.subject_user_id:
        users[execution.subject_user_id] = execution.subject_user
    email = (execution.subject_email or '').strip()
    if email:
        for u in User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)):
            users.setdefault(u.pk, u)
    return list(users.values())


def check_clientst0r(execution):
    from accounts.models import Membership, UserType
    from api.models import APIKey
    from api_mobile.models import MobileAuthToken
    from core.utils import descendant_org_ids
    from vault.models import Password, VaultAccessRule, WebExtensionAuthToken

    org_ids = descendant_org_ids(execution.organization)
    users = subject_users(execution)
    subject = execution.subject_email or (execution.subject_user.username if execution.subject_user else '')
    if not users:
        if not subject:
            return [dict(system='clientst0r', target='ClientSt0r', subject='', status='not_verifiable',
                         summary='Name the departing person (email or account) to check.', findings=[])]
        return [dict(system='clientst0r', target='ClientSt0r', subject=subject, status='removed',
                     summary='No ClientSt0r account with this email or user name.',
                     findings=[_f('ClientSt0r account', 'removed', 'none found')])]
    now = timezone.now()
    results = []
    for u in users:
        findings = []
        memberships = list(Membership.objects.filter(user=u, organization_id__in=org_ids)
                           .select_related('organization'))
        active = [m for m in memberships if m.is_active]
        user_type = getattr(getattr(u, 'profile', None), 'user_type', '')
        label = 'Portal sign-in' if user_type == UserType.ORG_USER else 'Membership'
        for m in active:
            findings.append(_f(f'{label}: {m.organization.name}', 'active', m.get_role_display()))
        if memberships and not active:
            findings.append(_f(f'{label} of this customer', 'removed', 'deactivated'))
        if not memberships:
            findings.append(_f(f'{label} of this customer', 'removed', 'none'))

        shared = Password.objects.filter(organization_id__in=org_ids, client_allowed_users=u).count()
        findings.append(_f('Vault items shared to them', 'active' if shared else 'removed',
                           f'{shared} item(s)' if shared else 'none'))
        rules = VaultAccessRule.objects.filter(organization_id__in=org_ids, scope='user', target_user=u,
                                               effect='allow', is_active=True).count()
        if rules:
            findings.append(_f('Vault allow rules for them', 'active', f'{rules} rule(s)'))

        keys = list(APIKey.objects.filter(organization_id__in=org_ids, user=u, is_active=True)
                    .values_list('key_prefix', flat=True))
        findings.append(_f('API keys', 'active' if keys else 'removed',
                           ', '.join(f'{p}…' for p in keys) if keys else 'none active'))

        live_ext = WebExtensionAuthToken.objects.filter(user=u, revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        pinned = live_ext.filter(organization_id__in=org_ids).count()
        if pinned:
            findings.append(_f('Browser extension tokens for this customer', 'active', f'{pinned} token(s)'))
        mobile = MobileAuthToken.objects.filter(user=u, revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)).count()
        unpinned = live_ext.filter(organization__isnull=True).count()
        if mobile or unpinned:
            # These reach a customer only through an active membership.
            findings.append(_f('Signed-in apps and extensions', 'active' if active and u.is_active else 'info',
                               f'{mobile} app / {unpinned} extension sign-in(s)'
                               + ('' if active and u.is_active else ' - no longer reach this customer')))
        other = Membership.objects.filter(user=u, is_active=True).exclude(organization_id__in=org_ids).exists()
        findings.append(_f('Account', 'info', ('enabled' if u.is_active else 'disabled')
                           + ('; has access to other customers' if other else '')))
        status = _status(findings)
        n = sum(1 for f in findings if f['state'] == 'active')
        results.append(dict(system='clientst0r', target=f'ClientSt0r account {u.username}',
                            subject=u.email or u.username, status=status, findings=findings,
                            summary=(f'{n} kind(s) of access remain' if n else 'No access to this customer remains')))
    return results


def _provider(conn):
    from integrations.providers.m365 import M365Provider
    creds = conn.get_credentials() or {}
    return M365Provider(conn.tenant_id, creds.get('client_id', ''), creds.get('client_secret', ''))


def check_m365(execution, provider_factory=None):
    from integrations.models import M365Connection
    provider_factory = provider_factory or _provider
    sign_in = (execution.subject_email or '').strip() or (
        execution.subject_user.email if execution.subject_user else '')
    conns = list(M365Connection.objects.filter(organization=execution.organization, is_active=True))
    if not conns:
        return [dict(system='m365', target='Microsoft 365', subject=sign_in, status='not_verifiable',
                     summary='No Microsoft 365 connection for this customer.', findings=[])]
    if not sign_in:
        return [dict(system='m365', target=c.name, subject='', status='not_verifiable',
                     summary="Add the departing person's email / sign-in name to check.", findings=[])
                for c in conns]
    results = []
    for conn in conns:
        try:
            user = provider_factory(conn).get_user_access(sign_in)
        except Exception as exc:  # noqa: BLE001 - recorded on the check
            logger.warning('M365 access check for execution %s on %s failed: %s',
                           execution.pk, conn.pk, type(exc).__name__)
            results.append(dict(system='m365', target=conn.name, subject=sign_in, status='error',
                                summary=f'Microsoft Graph lookup failed ({type(exc).__name__}).', findings=[]))
            continue
        if user is None:
            results.append(dict(system='m365', target=conn.name, subject=sign_in, status='removed',
                                summary='No user with this sign-in in the tenant (deleted).',
                                findings=[_f('User', 'removed', 'not found')]))
            continue
        lic = user.get('assignedLicenses') or []
        enabled = bool(user.get('accountEnabled'))
        findings = [
            _f('Sign-in', 'active' if enabled else 'removed', 'enabled' if enabled else 'blocked'),
            _f('Licenses', 'active' if lic else 'removed',
               f'{len(lic)} assigned' if lic else 'none assigned'),
        ]
        status = _status(findings)
        results.append(dict(system='m365', target=conn.name, subject=user.get('userPrincipalName') or sign_in,
                            status=status, findings=findings,
                            summary=('Still has access: ' + ', '.join(
                                f['item'].lower() for f in findings if f['state'] == 'active'))
                            if status == 'orphaned' else 'Sign-in blocked and no licenses assigned.'))
    return results


def check_rmm(execution):
    from integrations import ticket_rmm
    from integrations.models import RMMConnection
    conns = list(RMMConnection.objects.filter(organization=execution.organization, is_active=True))
    if not conns:
        return []
    out = []
    for conn in conns:
        paired = ticket_rmm.is_processor(conn)
        caps = sorted(ticket_rmm.advertised(conn)) if paired else []
        out.append(dict(
            system='rmm', target=conn.name, subject=execution.subject_email, status='not_verifiable',
            summary=('Paired RMM' if paired else 'RMM connection')
            + ' offers no way to read user accounts (ticket-rmm-v1 has no account-read capability). '
              'Confirm removal in the RMM by hand.',
            findings=[_f('Advertised capabilities', 'info', ', '.join(caps) or 'none')] if paired else []))
    return out


def verify(execution, user, *, request=None, m365_provider_factory=None):
    """Run every check, store the results, audit the run. Returns the new
    AccessRemovalCheck rows."""
    from .models import AccessRemovalCheck, ProcessExecutionAuditLog
    results = []
    for fn in (check_clientst0r, lambda e: check_m365(e, m365_provider_factory), check_rmm):
        try:
            results.extend(fn(execution))
        except Exception as exc:  # noqa: BLE001 - one system failing must not hide the others
            logger.exception('Access removal check failed for execution %s', execution.pk)
            results.append(dict(system='clientst0r' if fn is check_clientst0r else 'rmm',
                                target='', subject=execution.subject_email, status='error',
                                summary=f'Check failed ({type(exc).__name__}).', findings=[]))
    rows = [AccessRemovalCheck.objects.create(execution=execution, checked_by=user, **r) for r in results]
    orphaned = [r for r in rows if r.status == 'orphaned']
    desc = (f'Verified access removal for {execution.subject_email or "the departing person"}: '
            + ', '.join(f'{r.get_system_display()} {r.target}: {r.get_status_display()}' for r in rows))
    ProcessExecutionAuditLog.log_action(
        execution=execution, action_type='access_verified', user=user, description=desc[:2000],
        new_value={'orphaned': len(orphaned), 'checks': [r.pk for r in rows]}, request=request)
    return rows


def latest(execution):
    """The newest check per (system, target)."""
    seen, out = set(), []
    for c in execution.access_checks.select_related('checked_by').order_by('-created_at', '-id'):
        key = (c.system, c.target)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    order = {'clientst0r': 0, 'm365': 1, 'rmm': 2}
    return sorted(out, key=lambda c: (order.get(c.system, 9), c.target))
