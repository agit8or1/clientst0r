"""Audit entries for Microsoft 365 document actions.

Standard AuditLog actions with the specific event in
``extra_data['office_event']`` (the same key the Office core uses):

    m365_settings (update)   m365_location_add / m365_location_remove (update)
    m365_connect (update)    m365_disconnect (update)
    m365_link (create)       m365_unlink (delete)      m365_open (read)
    m365_create (create)     m365_import (import)      m365_export (export)
    Edit in Microsoft 365 (m365docs.editing): m365_edit_start (export),
    m365_edit_open (read), m365_edit_save (import), m365_edit_finish /
    m365_edit_discard / m365_edit_revoked / m365_edit_ended /
    m365_edit_reminder / m365_edit_settings (update)

Never logged: tokens, codes, PKCE verifiers, download URLs, file content.
"""
from __future__ import annotations

from office.audit import _request_bits
from office.logging_filters import get_logger

logger = get_logger('office.m365')

ACTIONS = {
    'm365_link': 'create', 'm365_create': 'create', 'm365_unlink': 'delete',
    'm365_open': 'read', 'm365_import': 'import', 'm365_export': 'export',
    'm365_edit_start': 'export', 'm365_edit_open': 'read', 'm365_edit_save': 'import',
}


def log(event, *, user, organization_id, object_type, object_id=None, object_repr='',
        description='', request=None, success=True, extra=None):
    from audit.models import AuditLog
    acting = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
    data = {'office_event': event, **(extra or {})}
    try:
        AuditLog.objects.create(
            user=acting, username=acting.username if acting else '',
            action=ACTIONS.get(event, 'update'), object_type=object_type[:100],
            object_id=object_id, object_repr=(object_repr or '')[:255],
            description=(description or '')[:2000], organization_id=organization_id,
            extra_data=data, success=success, **_request_bits(request))
    except Exception:
        logger.exception('M365 documents audit entry failed (%s)', event)
