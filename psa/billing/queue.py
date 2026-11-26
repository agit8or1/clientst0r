"""Phase 102.3: the Ready for Billing queue.

Per customer, everything ready to bill: the lines of every ticket sent to
billing, flagged for billing review or with work held or excluded here (the
exact lines "Invoice this ticket"
would write - psa.billing.invoicing.ticket_billing_lines, never priced a
second way), the customer's unbilled account charges and adjustments, and
completed, priced project milestones not billed yet.

Actions (all audited; `billing_manage_charges` at the customer):

* approve - marks the line reviewed and ready. No invoice is created or sent.
* hold    - keeps the line off every invoice until the until-date (when
            given) or until it is released; a reason is required.
* exclude - keeps the line off every invoice until someone includes it
            again; a reason is required.
* include - removes the decision (the line is ready again).
* adjust  - adds an explicit adjustment: an account charge or credit with its
            reason (optionally for one ticket). Source records are never
            edited.

"Create draft invoices" (`billing_send_invoices`) drafts the selected tickets'
invoices and bundles the selected customer's account charges through the
existing draft code under the customer billing lock (psa.billing.billed).
"Create one consolidated draft" (Phase 102.4, same permission) puts the
selected tickets, the account charges and optionally one agreement's next
recurring fee on a single draft (psa.billing.consolidated).
Drafts are never sent from here.

Viewing needs `billing_view_invoices` per customer.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import billed, invoicing

ZERO = Decimal('0')
CENT = Decimal('0.01')
VIEW = 'billing_view_invoices'
MANAGE = 'billing_manage_charges'
DRAFT = 'billing_send_invoices'
DECISIONS = ('approve', 'hold', 'exclude', 'include')
MAX_AMOUNT = Decimal('9999999999.99')
SOURCE_LABELS = {'time': 'Time', 'expense': 'Item', 'fee': 'Fee', 'charge': 'Charge', 'milestone': 'Milestone'}


class QueueError(ValueError):
    pass


def _q2(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _is_staff(user):
    from psa.visibility import is_msp_staff
    return bool(user and user.is_authenticated and (user.is_superuser or is_msp_staff(user)))


def allowed_customers(user, perm):
    """None = every customer, else a set of customer ids (staff only)."""
    from accounts.permission_utils import orgs_with_perm
    if not _is_staff(user):
        return set()
    return orgs_with_perm(user, perm)


def can(user, client, perm):
    from accounts.permission_utils import has_perm_for_org
    return _is_staff(user) and has_perm_for_org(user, getattr(client, 'pk', client), perm)


# --- building the queue ------------------------------------------------------------

@dataclass
class QueueLine:
    source: str
    source_id: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    kind: str = 'ready'          # ready | approved | held | excluded
    decision: object = None
    ticket: object = None
    link: str = ''

    @property
    def key(self):
        return f'{self.source}:{self.source_id}'

    @property
    def source_label(self):
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def coverage(self):
        return coverage_of(self)

    @property
    def coverage_label(self):
        return COVERAGE_LABELS.get(self.coverage, '')


@dataclass
class TicketGroup:
    ticket: object
    lines: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    total: Decimal = ZERO
    # The info dict ticket_billing_lines returned (covered / overage /
    # chargeable minutes, entries waiting for approval...). Shown as is.
    info: dict = field(default_factory=dict)

    @property
    def draftable(self):
        """Lines "Invoice this ticket" would write now (ready or approved)."""
        return bool(self.lines)


@dataclass
class CustomerQueue:
    client: object
    tickets: list = field(default_factory=list)
    charges: list = field(default_factory=list)
    milestones: list = field(default_factory=list)
    # Phase 102.4: the customer's agreements and whether each one's next
    # recurring fee can go on a consolidated draft now (FeeStatus).
    fees: list = field(default_factory=list)
    can_manage: bool = False
    can_draft: bool = False

    def _lines(self):
        for g in self.tickets:
            yield from g.lines
            yield from g.withheld
        yield from self.charges
        yield from self.milestones

    @property
    def ready_total(self):
        return sum((ln.total for ln in self._lines() if ln.kind in ('ready', 'approved')), ZERO)

    @property
    def held_total(self):
        return sum((ln.total for ln in self._lines() if ln.kind == 'held'), ZERO)

    @property
    def excluded_total(self):
        return sum((ln.total for ln in self._lines() if ln.kind == 'excluded'), ZERO)

    @property
    def charges_ready(self):
        return [c for c in self.charges if c.kind in ('ready', 'approved')]

    # 113.9: counts for the Billing Review header (no amounts are computed
    # here beyond the existing ready_total).
    @property
    def draftable_tickets(self):
        return [g for g in self.tickets if g.draftable]

    @property
    def approved_count(self):
        return sum(1 for ln in self._lines() if ln.kind == 'approved' and ln.source != 'milestone')

    @property
    def ready_count(self):
        return sum(1 for ln in self._lines() if ln.kind in ('ready', 'approved') and ln.source != 'milestone')

    @property
    def can_create_draft(self):
        return self.can_draft and bool(self.draftable_tickets or self.charges_ready)


# 113.9: how a line is covered, read from the line psa.billing.invoicing
# wrote (its source, its price and the description prefix it gives each
# kind of time line). A label only: amounts are never derived from it.
COVERAGE_LABELS = {
    'covered': 'Covered by agreement',
    'prepaid': 'Prepaid hours',
    'overage': 'Billable beyond prepaid hours',
    'billable': 'Billable',
    'credit': 'Credit',
    'held': 'Held (not on this draft)',
    'excluded': 'Excluded (not on this draft)',
}


def coverage_of(line):
    if line.kind in ('held', 'excluded'):
        return line.kind
    d = line.description or ''
    if line.source == 'time':
        if d.startswith('Time (covered by '):
            head = d.split('): ', 1)[0]
            return 'prepaid' if head.endswith(' prepaid hours') else 'covered'
        if d.startswith('Time (beyond prepaid hours)'):
            return 'overage'
    if line.unit_price < 0:
        return 'credit'
    return 'billable'


def _line(ln, *, kind, decision=None, ticket=None):
    q, p = Decimal(str(ln['quantity'])), Decimal(str(ln['unit_price']))
    return QueueLine(source=ln['source'], source_id=str(ln['source_id']), description=ln['description'],
                     quantity=q, unit_price=p, total=_q2(q * p), kind=kind, decision=decision, ticket=ticket)


def _kind(decision):
    if decision is None:
        return 'ready'
    if decision.withholds():
        return decision.state
    return 'approved' if decision.state == 'approved' else 'ready'


def _ticket_group(ticket):
    from .ticket_charges import blockers
    lines, info = invoicing.ticket_billing_lines(ticket)
    g = TicketGroup(ticket=ticket, blockers=blockers(ticket, info), info=info)
    decided = billed.decisions_for((ln['source'], ln['source_id']) for ln in lines)
    for ln in lines:
        d = decided.get((ln['source'], str(ln['source_id'])))
        g.lines.append(_line(ln, kind=_kind(d), decision=d, ticket=ticket))
    for kind in ('held', 'excluded'):
        for ln, d in info.get(kind, []):
            g.withheld.append(_line(ln, kind=kind, decision=d, ticket=ticket))
    # The same total "Invoice this ticket" writes.
    g.total = invoicing.lines_total(lines)
    return g


def _charge_line(c, decision):
    amount = Decimal(str(c.amount))
    price = -amount if c.is_credit else amount
    label = 'Adjustment' if c.adjustment_reason else ('Credit' if c.is_credit else 'Charge')
    return QueueLine(source='charge', source_id=str(c.pk), description=f'{label}: {c.description}'[:300],
                     quantity=Decimal('1'), unit_price=price, total=_q2(price), kind=_kind(decision),
                     decision=decision, ticket=c.ticket)


def _milestone_line(task, decision):
    from django.urls import reverse
    amount = Decimal(str(task.billing_amount))
    link = ''
    try:
        link = reverse('psa:project_detail', args=[task.project_id])
    except Exception:  # pragma: no cover - URL name differs
        pass
    return QueueLine(source='milestone', source_id=str(task.pk),
                     description=f'{task.project.name} — {task.title}'[:300], quantity=Decimal('1'),
                     unit_price=amount, total=_q2(amount), kind=_kind(decision), decision=decision, link=link)


def build_queue(user, customer=None, limit=100):
    """[CustomerQueue] for the customers `user` holds billing_view_invoices at,
    ordered by customer name. `customer` narrows it to one customer id."""
    from core.models import Organization
    from psa.models import Charge, Project, ProjectTask, Ticket
    allowed = allowed_customers(user, VIEW)
    if allowed is not None and not allowed:
        return []

    def scope(qs, field_name):
        if allowed is not None:
            qs = qs.filter(**{f'{field_name}__in': allowed})
        if customer:
            qs = qs.filter(**{field_name: customer})
        return qs

    groups = OrderedDict()

    def group(org):
        if org.pk not in groups:
            groups[org.pk] = CustomerQueue(client=org, can_manage=can(user, org, MANAGE),
                                           can_draft=can(user, org, DRAFT))
        return groups[org.pk]

    from psa.models import BillingQueueDecision
    # Tickets sent to billing or flagged, and tickets with work held or
    # excluded here (so it can be released or included again after the rest
    # of the ticket was invoiced).
    withheld_tickets = (BillingQueueDecision.objects.filter(state__in=('held', 'excluded'), ticket__isnull=False)
                        .values('ticket_id'))
    tickets = scope(Ticket.objects.filter(Q(billing_status__in=('ready', 'review')) | Q(pk__in=withheld_tickets)),
                    'organization_id')
    for t in tickets.select_related('organization').order_by('organization__name', 'pk')[:limit]:
        g = _ticket_group(t)
        if g.lines or g.withheld or g.blockers:
            group(t.organization).tickets.append(g)

    charges = list(scope(billed.unbilled_charges(Charge.objects.all()), 'client_org_id')
                   .select_related('client_org', 'ticket').order_by('charge_date', 'pk')[:500])
    decided = billed.decisions_for(('charge', c.pk) for c in charges)
    for c in charges:
        group(c.client_org).charges.append(_charge_line(c, decided.get(('charge', str(c.pk)))))

    projects = Project.objects.filter(billing_type=Project.BILLING_MILESTONE)
    if allowed is not None or customer:
        ids = allowed if allowed is not None else None
        q = Q()
        if ids is not None:
            q &= (Q(client_org_id__in=ids) | Q(client_org__isnull=True, organization_id__in=ids))
        if customer:
            q &= (Q(client_org_id=customer) | Q(client_org__isnull=True, organization_id=customer))
        projects = projects.filter(q)
    tasks = list(ProjectTask.objects.filter(project__in=projects, is_milestone=True, status='done',
                                            billed_on_invoice__isnull=True, billing_amount__isnull=False)
                 .select_related('project', 'project__client_org', 'project__organization')
                 .order_by('project__name', 'sort_order', 'pk')[:500])
    decided = billed.decisions_for(('milestone', t.pk) for t in tasks)
    for task in tasks:
        org = task.project.client_org or task.project.organization
        group(org).milestones.append(_milestone_line(task, decided.get(('milestone', str(task.pk)))))

    from .consolidated import fee_candidates
    for g in groups.values():
        if g.can_draft:
            g.fees = fee_candidates(g.client)

    names = dict(Organization.objects.filter(pk__in=list(groups)).values_list('pk', 'name'))
    return sorted(groups.values(), key=lambda g: ((names.get(g.client.pk) or '').lower(), g.client.pk))


def summary(queue):
    return {'customers': len(queue), 'tickets': sum(len(g.tickets) for g in queue),
            'ready_total': sum((g.ready_total for g in queue), ZERO),
            'held_total': sum((g.held_total for g in queue), ZERO),
            'excluded_total': sum((g.excluded_total for g in queue), ZERO)}


# --- decisions ---------------------------------------------------------------------

def parse_key(raw):
    src, _, sid = (raw or '').partition(':')
    if src not in dict(_sources()) or not sid or len(sid) > 80:
        raise QueueError(f'Unknown line {raw!r}.')
    return src, sid


def _sources():
    from psa.models import BillingQueueDecision
    return BillingQueueDecision.SOURCE_CHOICES


def resolve(client, source, source_id):
    """(ticket or None, label) for a source line of `client`; QueueError when
    it is not this customer's or is already on a live invoice."""
    from psa.models import Charge, ProjectTask, Ticket, TicketExpense, TicketTimeEntry
    pk = None
    if source in ('time', 'expense', 'charge', 'milestone'):
        if not source_id.isdigit():
            raise QueueError('Unknown line.')
        pk = int(source_id)
    if source == 'time':
        obj = TicketTimeEntry.objects.filter(pk=pk, ticket__organization=client).select_related('ticket').first()
        ticket, label = (obj.ticket, f'time entry {pk}') if obj else (None, '')
    elif source == 'expense':
        obj = TicketExpense.objects.filter(pk=pk, ticket__organization=client).select_related('ticket').first()
        ticket, label = (obj.ticket, f'item {obj.description[:80]}') if obj else (None, '')
    elif source == 'fee':
        parts = source_id.split(':')
        obj = None
        if len(parts) == 3 and parts[1].isdigit():
            obj = Ticket.objects.filter(pk=int(parts[1]), organization=client).first()
        ticket, label = (obj, f'{parts[0]} fee {parts[2]}') if obj else (None, '')
    elif source == 'charge':
        obj = Charge.objects.filter(pk=pk, client_org=client).first()
        ticket, label = (obj.ticket, f'charge {obj.description[:80]}') if obj else (None, '')
    else:
        obj = (ProjectTask.objects.filter(pk=pk, is_milestone=True)
               .filter(Q(project__client_org=client) | Q(project__client_org__isnull=True,
                                                         project__organization=client))
               .first())
        ticket, label = (None, f'milestone {obj.title[:80]}') if obj else (None, '')
    if obj is None:
        raise QueueError('That line is not one of this customer\'s.')
    if source in ('time', 'expense', 'fee') and billed.live_lines(source).filter(source_id=source_id).exists():
        raise QueueError(f'{label} is already on an invoice.')
    if source == 'charge' and billed.charge_is_billed(obj):
        raise QueueError(f'{label} is already on an invoice.')
    if source == 'milestone' and obj.billed_on_invoice_id:
        raise QueueError(f'{label} is already on an invoice.')
    return ticket, label


def decide(client, keys, decision, *, actor, reason='', hold_until=None):
    """Apply one decision to the given 'source:source_id' keys of `client`.
    Returns the number of lines changed. Audited per line."""
    from psa.models import BillingQueueDecision
    if not can(actor, client, MANAGE):
        raise PermissionDenied("You don't have the 'billing_manage_charges' permission for this customer.")
    if decision not in DECISIONS:
        raise QueueError('Pick approve, hold, exclude or include.')
    reason = (reason or '').strip()[:500]
    if decision in ('hold', 'exclude') and not reason:
        raise QueueError('A reason is required to hold or exclude.')
    if hold_until is not None and hold_until <= timezone.localdate():
        raise QueueError('The hold-until date must be in the future.')
    keys = list(OrderedDict.fromkeys(k for k in keys if k))
    if not keys:
        raise QueueError('Select at least one line.')
    parsed = [parse_key(k) for k in keys]
    changed = 0
    with transaction.atomic():
        billed.lock_customer(client)
        for src, sid in parsed:
            ticket, label = resolve(client, src, sid)
            existing = BillingQueueDecision.objects.filter(source=src, source_id=sid).first()
            before = existing.state if existing else ''
            if decision == 'include':
                if existing is None:
                    continue
                existing.delete()
                after = ''
            else:
                state = {'approve': 'approved', 'hold': 'held', 'exclude': 'excluded'}[decision]
                BillingQueueDecision.objects.update_or_create(
                    source=src, source_id=sid,
                    defaults={'client_org': client, 'ticket': ticket, 'state': state, 'reason': reason,
                              'hold_until': hold_until if state == 'held' else None, 'decided_by': actor,
                              'decided_at': timezone.now()})
                after = state
            changed += 1
            _audit(actor, client, src, sid,
                   f'Ready for Billing: {decision} {label}'
                   + (f' until {hold_until}' if decision == 'hold' and hold_until else '')
                   + (f' — {reason}' if reason else ''),
                   {'event': 'billing_queue_decision', 'decision': decision, 'source': src, 'source_id': sid,
                    'before': before, 'after': after, 'reason': reason,
                    'hold_until': hold_until.isoformat() if hold_until else None,
                    'ticket': getattr(ticket, 'ticket_number', None)})
    return changed


# --- adjustments -------------------------------------------------------------------

def add_adjustment(client, *, actor, description, amount, is_credit, reason, ticket=None, msp_org=None):
    """An explicit adjustment line: a psa.Charge with its reason. Returns it."""
    from psa.models import Charge
    if not can(actor, client, MANAGE):
        raise PermissionDenied("You don't have the 'billing_manage_charges' permission for this customer.")
    description = (description or '').strip()[:300]
    reason = (reason or '').strip()[:500]
    if not description:
        raise QueueError('A description is required.')
    if not reason:
        raise QueueError('A reason is required for an adjustment.')
    try:
        value = Decimal(str(amount).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise QueueError('Enter the amount as a number.')
    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
        raise QueueError('The amount must be positive (use "credit" to reduce the bill).')
    value = _q2(value)
    if ticket is not None and ticket.organization_id != client.pk:
        raise QueueError('That ticket is not one of this customer\'s.')
    charge = Charge.objects.create(
        organization=msp_org or client, client_org=client, description=description, amount=value,
        charge_date=timezone.localdate(), is_credit=bool(is_credit), notes=reason, adjustment_reason=reason,
        ticket=ticket, created_by=actor)
    _audit(actor, client, 'charge', str(charge.pk),
           f'Ready for Billing: {"credit" if is_credit else "charge"} adjustment {value} on {client.name}'
           + (f' ({ticket.ticket_number})' if ticket else '') + f': {description} — {reason}',
           {'event': 'billing_queue_adjustment', 'amount': str(value), 'is_credit': bool(is_credit),
            'reason': reason, 'ticket': getattr(ticket, 'ticket_number', None)}, action='create')
    return charge


# --- drafts --------------------------------------------------------------------------

def draft_from_queue(client, *, actor, msp_org=None, ticket_ids=(), include_charges=False):
    """Draft invoices for the selected tickets of `client` (one per ticket,
    the existing "Invoice this ticket" draft) and, when asked, one draft for
    the customer's account charges. Each runs under the customer billing
    lock, so a double click or retry creates nothing more. Returns
    (invoices, notes)."""
    from psa.models import Ticket
    if not can(actor, client, DRAFT):
        raise PermissionDenied("You don't have the 'billing_send_invoices' permission for this customer.")
    invoices, notes = [], []
    tickets = Ticket.objects.filter(organization=client, pk__in=[int(i) for i in ticket_ids if str(i).isdigit()])
    for t in tickets.order_by('pk'):
        try:
            inv, _info, _c = billed.draft_ticket_invoice(t, actor=actor, msp_org=msp_org)
        except billed.DoubleBilling:
            notes.append(f'{t.ticket_number} was being invoiced at the same time; nothing was added.')
            continue
        if inv is None:
            notes.append(f'Nothing left to invoice on {t.ticket_number}.')
        else:
            invoices.append(inv)
    if include_charges:
        try:
            inv, n = billed.bundle_charges(client, actor=actor, msp_org=msp_org)
        except billed.DoubleBilling:
            inv, n = None, 0
            notes.append('The account charges were being invoiced at the same time; nothing was added.')
        if inv is not None:
            invoices.append(inv)
        elif not notes or 'account charges' not in notes[-1]:
            notes.append('No account charges left to invoice.')
    return invoices, notes


def draft_consolidated_from_queue(client, *, actor, msp_org=None, ticket_ids=(), include_charges=False,
                                  contract_id=None):
    """Phase 102.4: one consolidated draft for `client` (see
    psa.billing.consolidated). Returns (invoice or None, notes). A double
    click or retry finds nothing left and creates nothing more."""
    from .consolidated import draft_consolidated
    if not can(actor, client, DRAFT):
        raise PermissionDenied("You don't have the 'billing_send_invoices' permission for this customer.")
    cid = int(contract_id) if str(contract_id or '').isdigit() else None
    try:
        res = draft_consolidated(client, actor=actor, msp_org=msp_org, ticket_ids=ticket_ids,
                                 include_charges=include_charges, contract_id=cid)
    except billed.DoubleBilling:
        return None, ['Some of this work was being invoiced at the same time; nothing was created. '
                      'Check the customer\'s invoices, then try again.']
    return res.invoice, res.notes


# --- 113.9: draft preview -------------------------------------------------------------

@dataclass
class DraftPreview:
    """What "Create draft" will write for one customer: the selected
    tickets' lines (TicketGroup.lines, the lines "Invoice this ticket"
    writes, with their existing totals) and the account charges the draft
    code reads (billed._read_charges). Nothing here prices a line."""
    group: CustomerQueue
    tickets: list = field(default_factory=list)
    charges: list = field(default_factory=list)
    include_charges: bool = False
    # Ticket groups that were asked for but have nothing to draft now.
    skipped: list = field(default_factory=list)
    # Ready charge lines the draft will not take (another organization's
    # record: billed._read_charges filters by the MSP organization).
    other_charges: list = field(default_factory=list)

    @property
    def charges_total(self):
        return sum((c.total for c in self.charges), ZERO)

    @property
    def total(self):
        return sum((t.total for t in self.tickets), ZERO) + self.charges_total

    @property
    def invoice_count(self):
        return len(self.tickets) + (1 if self.charges else 0)

    @property
    def is_empty(self):
        return not self.tickets and not self.charges

    @property
    def ticket_ids(self):
        return [t.ticket.pk for t in self.tickets]

    @property
    def fingerprint(self):
        """A digest of every line and amount shown, so the confirmation
        drafts exactly what was previewed (or nothing)."""
        import hashlib
        import json
        rows = []
        for t in self.tickets:
            rows.append(['ticket', t.ticket.pk, str(t.total)])
            rows.extend([ln.source, ln.source_id, str(ln.quantity), str(ln.unit_price), str(ln.total)]
                        for ln in t.lines)
        for c in self.charges:
            rows.append([c.source, c.source_id, str(c.quantity), str(c.unit_price), str(c.total)])
        raw = json.dumps([self.group.client.pk, bool(self.include_charges), rows], separators=(',', ':'))
        return hashlib.sha256(raw.encode()).hexdigest()


def draft_preview(user, client, *, ticket_ids=None, include_charges=None, msp_org=None):
    """DraftPreview for `client`, or None when the user may not view it.
    With no `ticket_ids` every ticket with lines to draft is selected, and
    the account charges are included unless `include_charges` is False."""
    groups = build_queue(user, customer=client.pk)
    group = next((g for g in groups if g.client.pk == client.pk), None)
    if group is None:
        group = CustomerQueue(client=client, can_manage=can(user, client, MANAGE),
                              can_draft=can(user, client, DRAFT))
    p = DraftPreview(group=group)
    if ticket_ids is None:
        p.tickets = list(group.draftable_tickets)
    else:
        wanted = {int(i) for i in ticket_ids if str(i).isdigit()}
        for g in group.tickets:
            if g.ticket.pk in wanted:
                (p.tickets if g.draftable else p.skipped).append(g)
    p.include_charges = bool(group.charges_ready) if include_charges is None else bool(include_charges)
    if p.include_charges:
        readable = {str(c.pk) for c in billed._read_charges(client, msp_org)}
        for c in group.charges_ready:
            (p.charges if c.source_id in readable else p.other_charges).append(c)
    return p


def _audit(actor, client, source, source_id, description, extra, action='update'):
    from audit.models import AuditLog
    AuditLog.log(user=actor, action=action, organization=client, object_type='psa.BillingQueueDecision',
                 object_id=0, object_repr=f'{source}:{source_id}'[:200], description=description[:500],
                 extra_data=extra)
