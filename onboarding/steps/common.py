"""Helpers shared by the built-in steps."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q

from onboarding import access


def has_org_perm(user, org, perm) -> bool:
    from accounts.permission_utils import user_has_org_perm
    return bool(org is not None and user_has_org_perm(user, org, perm))


def need(user, org, perm, what) -> str:
    """'' when allowed, else a sentence for the denial."""
    return '' if has_org_perm(user, org, perm) else f'You need the "{perm}" permission for {what}.'


def contract_denial(user, client, action) -> str:
    from contracts import permissions as perms
    return perms.denial(user, action, client.pk if client is not None else None)


def can_configure_integrations(user, session) -> bool:
    """Integration mappings: platform administrators, or the integration
    configure permission at the customer."""
    from integrations.ownership import can_manage_platform
    return bool(can_manage_platform(user) or has_org_perm(user, session.client, 'integrations_configure')
                or has_org_perm(user, session.organization, 'integrations_configure'))


def owned_by_scope(session):
    """Q for connections the session may use: platform-owned, or owned by the
    tenant or the customer."""
    ids = [i for i in (session.organization_id, session.client_id) if i]
    return Q(organization__isnull=True) | Q(organization_id__in=ids)


def money(value, default=Decimal('0')):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def lines_from_session(session):
    """Draft line items built from what the session recorded: quantities and
    manual unit prices, the chosen plan and add-ons (pricing), and the
    customer-specific discount. Returns a list of dicts in the contract
    document's line-item format (recurring monthly)."""
    q = session.step_data('quantities')
    lines = []
    for key, label in (('users', 'Managed users'), ('devices', 'Managed devices'),
                       ('servers', 'Managed servers'), ('locations', 'Locations')):
        qty = int(q.get(key) or 0)
        price = money(q.get(f'price_{key}'))
        if qty and price:
            lines.append({'description': f'{label} (per month)', 'kind': 'recurring', 'quantity': str(qty),
                          'unit_price': str(price), 'discount_percent': '0', 'taxable': False})
    plan = session.step_data('service_plan')
    if plan.get('plan_name') and money(plan.get('monthly_price')):
        lines.append({'description': f'Service plan: {plan["plan_name"]}', 'kind': 'recurring', 'quantity': '1',
                      'unit_price': str(money(plan.get('monthly_price'))), 'discount_percent': '0',
                      'taxable': False})
    addons = session.step_data('add_ons')
    for item in addons.get('items') or []:
        if money(item.get('price')):
            lines.append({'description': f'Add-on: {item.get("name", "")}', 'kind': 'recurring',
                          'quantity': str(item.get('quantity') or 1), 'unit_price': str(money(item.get('price'))),
                          'discount_percent': '0', 'taxable': False})
    disc = money(session.step_data('customer_pricing').get('discount_percent'))
    if disc:
        for ln in lines:
            ln['discount_percent'] = str(disc)
    return lines


def sync_agreement_settings(session, user):
    """Push the recorded account manager, billing frequency and payment terms
    onto the session's agreement draft (a no-op when there is no draft)."""
    from contracts import services
    from contracts.models import ContractDocument as D
    ag = session.agreement
    if ag is None or ag.status != D.DRAFT:
        return
    data = {}
    bf = session.step_data('billing_frequency').get('frequency')
    if bf:
        data['billing_frequency'] = bf
    terms = session.step_data('payment').get('terms')
    if terms:
        data['payment_terms'] = terms
    am = session.step_data('account_manager').get('user')
    if am:
        from django.contrib.auth import get_user_model
        data['account_manager'] = get_user_model().objects.filter(pk=am).first()
    if data:
        services.save_draft(ag, data, user)
        session.agreement.refresh_from_db()
