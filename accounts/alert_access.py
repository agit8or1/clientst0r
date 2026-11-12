"""
"Is this user allowed to be told about this record, right now?"

Notification code calls this twice: when it decides who gets an alert, and
again immediately before delivering it (e-mail, SMS, push, digest), because
a role, membership, scope or account may change while the alert waits in a
queue. A recipient who fails the second check is dropped silently; the
alert is never sent to someone who can no longer open the record.

    may_receive_alert(user, perm, organization=None, obj=None, ...)
    filter_alert_recipients(users, perm, organization=None, obj=None, ...)

`perm` is the permission needed to view the record (e.g. 'tickets_view',
'monitoring_view', 'security_alerts_view'). With `obj` the record scope is
checked as well (accounts.scope.can_access_object): an "assigned records
only" technician is told about their own tickets, not the whole queue.
Contract alerts use accounts.contract_access.contract_alert_recipients.
"""
from __future__ import annotations

from .permission_utils import user_has_org_perm


def may_receive_alert(user, perm, organization=None, obj=None, org_attr='organization',
                      owner_fields=('created_by',), assignee_fields=('assigned_to',)) -> bool:
    if user is None or not getattr(user, 'is_active', False):
        return False
    profile = getattr(user, 'profile', None)
    if profile is not None and getattr(profile, 'is_locked', False):
        return False
    if obj is not None:
        from .scope import can_access_object
        return can_access_object(user, perm, obj, org_attr=org_attr, owner_fields=owner_fields,
                                 assignee_fields=assignee_fields)
    if organization is None:
        return bool(user.is_superuser)
    return user_has_org_perm(user, organization, perm)


def filter_alert_recipients(users, perm, organization=None, obj=None, **kw):
    return [u for u in users if may_receive_alert(u, perm, organization=organization, obj=obj, **kw)]
