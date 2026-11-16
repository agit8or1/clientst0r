"""
What people do with recommendations: accept (creates a draft), dismiss
(with a reason), and the automatic step to "implemented".

Accepting never changes an active contract or a price:

  * a recurring-amount or hourly-rate change on a contract becomes a DRAFT
    contract amendment: a new psa.Contract in status "draft" copying the
    contract's terms with the proposed figure applied. It is not linked as
    the contract's renewal (`parent_contract` would stop auto-renewal of the
    active contract); the link is kept on the recommendation and in the
    draft's notes;
  * everything else (per-device price, after-hours rate, upsell without a
    contract figure, plan change, item price) becomes a DRAFT psa.Quote.

A recommendation becomes "implemented" when its draft goes through the
existing flow: the draft contract is made active, or the quote is accepted
(its approval chain completed). Every action is written to the audit log.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog

CONTRACT_FIELDS = {'recurring_amount', 'hourly_rate'}
COPY_FIELDS = ('organization_id', 'client_org_id', 'contract_type', 'total_hours', 'hourly_rate', 'overage_rate',
               'rollover_percent', 'rollover_expiry_days', 'auto_renew', 'auto_renew_period_months',
               'billing_frequency', 'recurring_amount', 'proration_enabled', 'billable_role_codes',
               'excluded_role_codes', 'sla_matrix')


class ActionRefused(Exception):
    pass


def audit(user, action, rec_or_finding, description, request=None, **extra):
    from core.client_ip import get_client_ip
    from .models import Finding
    finding = rec_or_finding if isinstance(rec_or_finding, Finding) else rec_or_finding.finding
    AuditLog.log(
        user=user, action=action, organization=finding.client_org,
        object_type=f'advisor.{type(rec_or_finding).__name__}', object_id=rec_or_finding.pk,
        object_repr=str(getattr(rec_or_finding, 'title', ''))[:255], description=description,
        ip_address=get_client_ip(request) if request is not None else None,
        path=request.path if request is not None else '',
        extra_data={'event': extra.pop('event', 'advisor'), **extra},
    )


def _dec(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _work_text(rec):
    w = rec.work or {}
    lines = [f'Pricing Advisor recommendation #{rec.pk}: {rec.title}', '', rec.rationale or '', '',
             f"Formula: {w.get('formula', '')}"]
    lines += [f'  {s}' for s in w.get('steps', [])]
    if w.get('assumptions'):
        lines += ['Assumptions:'] + [f'  - {a}' for a in w['assumptions']]
    if w.get('unknown'):
        lines += ['Unknown:'] + [f'  - {u}' for u in w['unknown']]
    lines += ['', 'Operational estimate, not an accounting P&L. Review before sending or activating.']
    return '\n'.join(lines)


def _draft_contract(rec, user):
    from psa.models import Contract
    src = rec.contract
    proposed = rec.proposed or {}
    value = _dec(proposed.get('proposed'))
    today = timezone.localdate()
    start = src.end_date + timedelta(days=1) if (src.end_date and src.end_date >= today) else today
    draft = Contract(status='draft', start_date=start, created_by=user,
                     name=f'{src.name} (proposed amendment)'[:200])
    for f in COPY_FIELDS:
        setattr(draft, f, getattr(src, f))
    draft.billable_role_codes = list(src.billable_role_codes or [])
    draft.excluded_role_codes = list(src.excluded_role_codes or [])
    draft.sla_matrix = dict(src.sla_matrix or {})
    setattr(draft, proposed.get('field'), value)
    included = _dec(proposed.get('included_hours'))
    if included is not None:
        months = {'monthly': 1, 'quarterly': 3, 'yearly': 12}.get(src.billing_frequency, 1)
        draft.total_hours = included * months
    draft.notes = (f'Draft amendment of contract #{src.pk} "{src.name}". The active contract is unchanged.\n\n'
                   + _work_text(rec))
    draft.save()
    for meter in src.meters.all():
        meter.pk = None
        meter.contract = draft
        meter.last_billed_at = None
        meter.save()
    for item in src.bundle_items.all():
        item.pk = None
        item.contract = draft
        item.save()
    return draft


def _draft_quote(rec, user):
    from psa.models import Quote, QuoteLineItem
    finding = rec.finding
    proposed = rec.proposed or {}
    owner = rec.contract.organization if rec.contract is not None else finding.client_org
    quote = Quote.objects.create(
        organization=owner, client_org=finding.client_org, title=rec.title[:300],
        description=_work_text(rec), status='draft', created_by=user,
        valid_until=timezone.localdate() + timedelta(days=30))
    price = _dec(proposed.get('proposed'))
    QuoteLineItem.objects.create(
        quote=quote, description=f"{rec.title} ({proposed.get('unit') or 'proposed'})"[:300], quantity=1,
        unit_price=price if price is not None else Decimal('0'), sort_order=0)
    quote.recompute_totals()
    return quote


def accept(rec, user, request=None):
    from .permissions import can_act
    if not can_act(user, rec.finding.client_org):
        raise ActionRefused("You don't have the 'act_on_pricing_recommendations' permission for this customer.")
    with transaction.atomic():
        rec = type(rec).objects.select_for_update().get(pk=rec.pk)
        if rec.status != 'open':
            raise ActionRefused('This recommendation was already decided.')
        field = (rec.proposed or {}).get('field')
        if (rec.contract is not None and field in CONTRACT_FIELDS
                and _dec((rec.proposed or {}).get('proposed')) is not None):
            rec.draft_contract = _draft_contract(rec, user)
            what = f'draft contract #{rec.draft_contract.pk}'
        else:
            rec.draft_quote = _draft_quote(rec, user)
            what = f'draft quote {rec.draft_quote.quote_number}'
        rec.status = 'accepted'
        rec.decided_by = user
        rec.decided_at = timezone.now()
        rec.save()
        audit(user, 'create', rec, f'Accepted pricing recommendation; created {what}.', request,
              event='advisor_recommendation_accepted',
              draft_contract_id=rec.draft_contract_id, draft_quote_id=rec.draft_quote_id)
    return rec


def dismiss(rec, user, reason, request=None):
    from .permissions import can_act
    if not can_act(user, rec.finding.client_org):
        raise ActionRefused("You don't have the 'act_on_pricing_recommendations' permission for this customer.")
    reason = (reason or '').strip()
    if not reason:
        raise ActionRefused('Give a reason for dismissing the recommendation.')
    with transaction.atomic():
        rec = type(rec).objects.select_for_update().get(pk=rec.pk)
        if rec.status != 'open':
            raise ActionRefused('This recommendation was already decided.')
        rec.status = 'dismissed'
        rec.dismiss_reason = reason[:2000]
        rec.decided_by = user
        rec.decided_at = timezone.now()
        rec.save()
        audit(user, 'update', rec, f'Dismissed pricing recommendation: {reason[:200]}', request,
              event='advisor_recommendation_dismissed', reason=reason[:2000])
    return rec


def _draft_done(rec):
    if rec.draft_contract_id:
        return rec.draft_contract is not None and rec.draft_contract.status == 'active'
    if rec.draft_quote_id:
        return rec.draft_quote is not None and rec.draft_quote.status == 'accepted'
    return False


def sync_implemented(queryset=None):
    """Move accepted recommendations whose draft went live to "implemented"."""
    from .models import Recommendation
    qs = queryset if queryset is not None else Recommendation.objects.filter(status='accepted')
    n = 0
    for rec in qs.select_related('draft_contract', 'draft_quote', 'finding__client_org'):
        if rec.status == 'accepted' and _draft_done(rec):
            rec.status = 'implemented'
            rec.implemented_at = timezone.now()
            rec.save(update_fields=['status', 'implemented_at', 'updated_at'])
            audit(None, 'update', rec, 'Recommendation implemented: its draft was approved through the '
                  'existing flow.', event='advisor_recommendation_implemented')
            n += 1
    return n
