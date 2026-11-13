"""The contract timeline (append-only) and its mirror in the audit log."""
from __future__ import annotations

import logging

from django.utils import timezone

from .models import ContractEvent

logger = logging.getLogger('contracts')

# Staff actions also go to the system audit log.
AUDITED = {'created', 'submitted', 'approved', 'rejected', 'issued', 'sent', 'invitation_resent',
           'invitation_revoked', 'invitation_replaced', 'link_generated', 'signed', 'declined', 'completed',
           'superseded', 'voided', 'billing_linked', 'expired'}


def request_meta(request):
    if request is None:
        return None, ''
    from core.client_ip import get_client_ip
    return (get_client_ip(request) or None), (request.META.get('HTTP_USER_AGENT') or '')[:400]


def record(contract, kind, *, version=None, invitation=None, actor=None, actor_label='', message='',
           request=None, data=None, at=None):
    ip, ua = request_meta(request)
    user = actor if actor is not None and getattr(actor, 'is_authenticated', False) else None
    if not actor_label and user is not None:
        actor_label = user.get_full_name() or user.username
    ev = ContractEvent.objects.create(
        contract=contract, version=version, invitation=invitation, kind=kind, at=at or timezone.now(),
        actor=user, actor_label=actor_label[:255], message=(message or '')[:500], ip_address=ip,
        user_agent=ua, data=data or {})
    if kind in AUDITED:
        try:
            from audit.models import AuditLog
            AuditLog.log(user=user, action='update' if kind != 'created' else 'create',
                         organization=contract.organization, object_type='contracts.ContractDocument',
                         object_id=contract.pk, object_repr=f'{contract.reference} {contract.title}'[:255],
                         description=f'Contract {contract.reference}: {ev.get_kind_display()}'
                                     + (f' — {message}' if message else ''),
                         ip_address=ip, user_agent=ua, path='', extra_data={'contract_event': ev.pk, 'kind': kind})
        except Exception:  # noqa: BLE001 — the timeline row is the record; the audit mirror is best effort
            logger.exception('audit mirror failed for contract event %s', ev.pk)
    return ev
