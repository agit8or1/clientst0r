"""Audit entries for Office actions.

Every entry uses the standard AuditLog actions (create / read / update /
export) with ``object_type`` ``office.<kind>`` and the specific event in
``extra_data['office_event']``:

    create, open, session_start, session_end, session_revoked, save,
    save_failed, quarantine, export, restore, rename, copy, convert,
    settings_change, policy_change, diagnostics_run, round_trip, health_check,
    template_upload, template_delete, quarantine_download, quarantine_restore,
    managed_operation (Managed Local ONLYOFFICE lifecycle, office.managed.jobs)

Never logged: tokens, secrets, document content, document keys, URLs with
query strings. Only ids, names, sizes, revision numbers and SHA-256 digests.
"""
from __future__ import annotations

import logging

from .logging_filters import get_logger

logger = get_logger('office')

_ACTION = {
    'create': 'create', 'copy': 'create', 'convert': 'create', 'template_upload': 'create',
    'open': 'read', 'download': 'read', 'session_start': 'read',
    'quarantine_download': 'read',
    'export': 'export',
}


def _request_bits(request):
    if request is None:
        return {}
    try:
        from core.client_ip import get_client_ip
        ip = get_client_ip(request)
    except Exception:
        ip = None
    return {'ip_address': ip or None,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500],
            'path': request.path[:500]}


def log(event, *, user=None, target=None, organization_id=None, description='',
        request=None, success=True, extra=None, object_type=None, object_id=None,
        object_repr=''):
    from audit.models import AuditLog
    data = {'office_event': event}
    if extra:
        data.update(extra)
    if target is not None:
        organization_id = target.organization_id
        object_type = object_type or f'office.{target.kind}'
        object_id = target.pk
        object_repr = object_repr or target.filename
    acting = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
    try:
        AuditLog.objects.create(
            user=acting, username=acting.username if acting else '',
            action=_ACTION.get(event, 'update'),
            object_type=(object_type or 'office')[:100], object_id=object_id,
            object_repr=(object_repr or '')[:255],
            description=description[:2000], organization_id=organization_id,
            extra_data=data, success=success, **_request_bits(request))
    except Exception:
        logger.exception('Office audit entry failed (%s)', event)


def saved(target, user, revision, *, session=None, request=None):
    log('save', user=user, target=target, request=request,
        description=f'Saved revision {revision.revision_number} of {target.filename} '
                    f'({revision.size} bytes, {revision.get_source_display().lower()})',
        extra={'revision': revision.revision_number, 'sha256': revision.sha256,
               'session': str(session.pk) if session else None, 'source': revision.source})


def save_failed(target, user, *, session=None, reason='', detail='', quarantined=None):
    extra = {'reason': reason, 'session': str(session.pk) if session else None}
    if quarantined is not None:
        extra['quarantine_id'] = quarantined.pk
        extra['sha256'] = quarantined.sha256
    name = target.filename if target is not None else (session.target_label if session else '')
    log('quarantine' if quarantined is not None else 'save_failed', user=user, target=target,
        organization_id=None if target is not None else getattr(session, 'organization_id', None),
        success=False, extra=extra,
        description=(f'Save of {name} not accepted ({reason})'
                     + ('; kept in quarantine' if quarantined is not None else '')
                     + (f': {detail}' if detail else ''))[:2000])
