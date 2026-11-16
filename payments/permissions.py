"""Who may configure gateways, see collected payments and refund them.

  manage_payment_providers  configure the MSP's gateway connections (keys,
                            webhook secret, autopay). Connections are
                            install-global (one MSP per install), so this is
                            read from the technician's global role.
  process_refunds           refund a payment, at the paying customer.
  billing_view_invoices     see payment attempts, at the paying customer.

All three are staff-only (permission_registry staff_only); superusers hold
everything. Customer users never reach /payments/ (staff-only prefix).
"""
from __future__ import annotations

from accounts.permission_utils import orgs_with_perm, user_has_org_perm
from psa.visibility import is_msp_staff


def _active(user):
    return bool(user is not None and user.is_authenticated and user.is_active)


def _global_flag(user, flag):
    profile = getattr(user, 'profile', None)
    if profile is None or not getattr(profile, 'is_staff_user', lambda: False)():
        return False
    role = profile.get_global_permissions()
    return bool(role is not None and getattr(role, flag, False))


def can_manage_connection(user, connection=None) -> bool:
    """Gateway connections are MSP-wide; a customer-owned row is never managed here."""
    if not _active(user):
        return False
    if connection is not None and connection.organization_id is not None:
        return False
    if user.is_superuser:
        return True
    return is_msp_staff(user) and _global_flag(user, 'manage_payment_providers')


def manageable_connections(user):
    from integrations.models import PaymentConnection
    qs = PaymentConnection.objects.filter(organization__isnull=True).order_by('name')
    return qs if can_manage_connection(user) else qs.none()


def can_refund(user, attempt) -> bool:
    if not _active(user):
        return False
    if user.is_superuser:
        return True
    return is_msp_staff(user) and user_has_org_perm(user, attempt.client_org_id, 'process_refunds')


def can_view_attempt(user, attempt) -> bool:
    if not _active(user) or not is_msp_staff(user):
        return False
    return (user.is_superuser or user_has_org_perm(user, attempt.client_org_id, 'billing_view_invoices')
            or can_refund(user, attempt))


def visible_attempts(user):
    from .models import PaymentAttempt
    qs = PaymentAttempt.objects.select_related('invoice', 'client_org', 'connection')
    if not _active(user) or not is_msp_staff(user):
        return qs.none()
    allowed = orgs_with_perm(user, 'billing_view_invoices')
    if allowed is None:
        return qs
    return qs.filter(client_org_id__in=allowed)
