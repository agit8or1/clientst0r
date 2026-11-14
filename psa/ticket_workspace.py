"""
The ticket workspace: the views of the ticket list chosen by ``?view=``.

    (none)       All Tickets — the list as it always was
    overview     counts (open, mine, unassigned, SLA at risk / breached,
                 escalated, pending approvals), each opening its list
    unassigned   open tickets nobody has, soonest SLA deadline first, with
                 an inline assignment control (psa:dispatch_assign)
    sla          open tickets with their SLA state and time remaining
    escalated    open tickets a customer escalated (Ticket.escalated_at)
    approvals    pending ticket-related approvals (PSAApproval with a
                 ticket, and CAB votes awaiting this user)

Every view starts from ``psa.views._scoped_ticket_qs`` — the same tickets the
plain list shows — and only narrows it. The views other than All Tickets are
for MSP technicians (``psa.visibility.is_msp_staff``); for anyone else the
parameter is ignored and the plain list renders. Nothing here grants an
action: the assignment control is drawn only where ``psa:dispatch_assign``
would accept it, and approve / deny only where ``psa:approval_decide`` would
(both endpoints keep their own checks).

SLA states are psa.my_work.sla_bucket_qs (shared with the dashboard's SLA
figures). A ticket without a deadline is "No SLA"; no deadline is invented.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

TICKET_VIEWS = {
    'overview': 'Overview',
    'unassigned': 'Unassigned',
    'sla': 'SLA',
    'escalated': 'Escalated',
    'approvals': 'Approvals',
}

# ?age= — opened at least this long ago.
AGE_FILTERS = {
    '1d': ('Older than 1 day', timedelta(days=1)),
    '3d': ('Older than 3 days', timedelta(days=3)),
    '7d': ('Older than 7 days', timedelta(days=7)),
    '30d': ('Older than 30 days', timedelta(days=30)),
}

# ?sort=
SORTS = {
    'deadline': 'SLA deadline (soonest first)',
    'age': 'Age (oldest first)',
    'newest': 'Newest first',
}

SLA_TONES = {
    'breached': 'danger',
    'at_risk': 'warn',
    'on_track': 'active',
    'paused': 'neutral',
    'no_sla': 'neutral',
}


def view_for(request) -> str:
    """The validated ?view= value ('' for All Tickets)."""
    from .visibility import is_msp_staff
    view = request.GET.get('view') or ''
    if view not in TICKET_VIEWS or not is_msp_staff(request.user):
        return ''
    return view


def short_delta(delta) -> str:
    """'3d 4h', '4h 08m', '12m' for a non-negative timedelta."""
    mins = max(0, int(delta.total_seconds() // 60))
    d, rem = divmod(mins, 1440)
    h, m = divmod(rem, 60)
    if d:
        return f'{d}d {h}h'
    if h:
        return f'{h}h {m:02d}m'
    return f'{m}m'


def decorate_sla(tickets, now=None):
    """Label rows annotated by psa.my_work.annotate_activity() with their SLA
    bucket, tone, deadline kind and time remaining (or overdue by)."""
    from .my_work import SLA_BUCKETS, sla_bucket_of
    now = now or timezone.now()
    for t in tickets:
        bucket = sla_bucket_of(t, now)
        t.sla_bucket = bucket
        t.sla_bucket_label = SLA_BUCKETS[bucket]
        t.sla_tone = SLA_TONES[bucket]
        due = getattr(t, 'sla_due_at', None)
        t.sla_which = ''
        t.sla_left = ''
        if due is not None:
            t.sla_which = ('First response' if t.first_response_at is None
                           and t.first_response_due_at is not None else 'Resolution')
            t.sla_left = (f'{short_delta(now - due)} overdue' if due < now
                          else f'{short_delta(due - now)} left')
    return tickets


def _write_ok(request) -> bool:
    """core.decorators.require_write, as it applies to a POST without an
    org_id in the URL (approval_decide, ticket_quick_action, dispatch_assign)."""
    user = request.user
    if user.is_superuser or user.is_staff:
        return True
    from core.decorators import get_user_membership
    membership = get_user_membership(request)
    return bool(membership is not None and membership.can_write())


def decorate_assign(request, tickets):
    """Mark which unassigned rows the user may assign from the list.

    ``t.can_assign``: psa:dispatch_assign would accept it — MSP staff with
    tickets_assign on the ticket's customer (psa.views._can_assign), write
    access, and the ticket inside the endpoint's scope (the selected customer,
    when one is selected). ``t.can_take``: no reassign right, but "Assign to
    me" (psa:ticket_quick_action, needs tickets_edit) would work.
    Returns the technician list for the picker (empty when no row needs it).
    """
    from core.middleware import get_request_organization
    from .views import _can_assign, _eligible_assignees, _org_perm
    from .visibility import is_msp_staff
    staff = is_msp_staff(request.user)
    write = _write_ok(request)
    org = get_request_organization(request)
    assign_cache, edit_cache = {}, {}
    any_assign = False
    for t in tickets:
        t.can_assign = t.can_take = False
        if not (staff and write) or t.assigned_to_id:
            continue
        oid = t.organization_id
        if oid not in assign_cache:
            assign_cache[oid] = _can_assign(request, t.organization)
        in_scope = org is None or org.pk == oid
        if assign_cache[oid] and in_scope:
            t.can_assign = any_assign = True
            continue
        if oid not in edit_cache:
            edit_cache[oid] = _org_perm(request, oid, 'tickets_edit')
        t.can_take = edit_cache[oid]
    if not any_assign:
        return []
    return list(_eligible_assignees(org).only('id', 'username', 'first_name', 'last_name'))


# -- Approvals -----------------------------------------------------------------

def approval_rows(request, tickets_qs):
    """Pending ticket-related approvals this user can see.

    PSA approvals use psa.views.approval_list's scoping (the selected
    customer, else every customer for MSP staff) narrowed to approvals whose
    ticket is in ``tickets_qs`` (the user's ticket scope). ``can_decide``
    repeats psa.views.approval_decide's checks so the buttons appear only
    where a POST would succeed; ``blocked_reason`` says why they don't.
    CAB votes: pending_cab changes where this user is a required approver
    and has not voted (psa.views._my_work_approvals), voted on the change page.
    """
    from accounts.permission_utils import user_has_perm
    from core.middleware import get_request_organization
    from .models import PSAApproval
    from .views import _org_perm, _scoped_change_request_qs
    from .visibility import is_msp_staff

    user = request.user
    org = get_request_organization(request)
    staff_flag = user.is_superuser or getattr(request, 'is_staff_user', False)
    staff = is_msp_staff(user)
    write = _write_ok(request)
    rows = []

    qs = (PSAApproval.objects.select_related('related_ticket', 'requested_by', 'organization')
          .filter(related_ticket__isnull=False, related_ticket__in=tickets_qs.values('pk'),
                  status__in=('pending', 'blocked')))
    if org is not None:
        qs = qs.filter(organization=org)
    elif not staff_flag:
        qs = qs.none()
    ai_ok = {}
    for a in qs.order_by('-requested_at')[:200]:
        reason = ''
        if a.status == 'blocked':
            reason = 'Waiting on an earlier stage'
        elif a.is_client_approval:
            reason = 'Customer decides in the portal'
        elif not (staff and write):
            reason = 'Read-only access'
        elif a.requested_by_id == user.pk and not user.is_superuser:
            reason = 'You requested it; someone else approves'
        elif a.kind == 'action':
            if a.organization_id not in ai_ok:
                ai_ok[a.organization_id] = _org_perm(request, a.organization_id,
                                                     'psa_ai_approve_action')
            if not ai_ok[a.organization_id]:
                reason = 'Needs the AI action approval permission'
        rows.append({
            'kind': 'approval',
            'type': a.get_kind_display() + (' · customer sign-off' if a.is_client_approval else ''),
            'title': a.object_repr or f'{a.get_kind_display()} #{a.pk}',
            'ticket': a.related_ticket,
            'client': a.organization.name if a.organization_id else '',
            'requester': (a.requested_by.get_full_name() or a.requested_by.username)
            if a.requested_by_id else '',
            'requested_at': a.requested_at,
            'approver': ('Customer (portal)' if a.is_client_approval else 'MSP approver'),
            'status': a.get_status_display(),
            'status_key': a.status,
            'pk': a.pk,
            'can_decide': not reason,
            'blocked_reason': reason,
            'history_url': reverse('psa:approval_history', args=[a.pk]),
        })

    if user_has_perm(user, 'change_approve_cab'):
        changes = (_scoped_change_request_qs(request)
                   .filter(implementation_status='pending_cab', required_approvers=user,
                           ticket__in=tickets_qs.values('pk'))
                   .exclude(cab_votes__user=user)
                   .select_related('submitted_by')
                   .distinct().order_by('-submitted_at')[:100])
        for c in changes:
            rows.append({
                'kind': 'cab',
                'type': f'Change · CAB vote ({c.get_risk_display()} risk)',
                'title': c.ticket.subject,
                'ticket': c.ticket,
                'client': c.organization.name if c.organization_id else '',
                'requester': (c.submitted_by.get_full_name() or c.submitted_by.username)
                if c.submitted_by_id else '',
                'requested_at': c.submitted_at,
                'approver': 'You (CAB member)',
                'status': 'Pending CAB',
                'status_key': 'pending',
                'pk': c.pk,
                'can_decide': False,
                'blocked_reason': '',
                'vote_url': reverse('psa:change_request_detail', args=[c.ticket.ticket_number]),
            })
    rows.sort(key=lambda r: r['requested_at'] or timezone.now(), reverse=True)
    return rows


# -- Overview ------------------------------------------------------------------

def overview_counts(request, tickets_qs, client_id=''):
    """The Overview tab's tiles, from the same scoped queryset as the lists
    they open (each count equals its list, up to the list's 200-row cap)."""
    from urllib.parse import urlencode
    from .my_work import annotate_activity, open_q, sla_bucket_qs

    base = tickets_qs
    if client_id:
        base = base.filter(organization_id=client_id)
    qs = annotate_activity(base.filter(open_q()))
    b = sla_bucket_qs('sla_due_at')
    c = qs.aggregate(
        open=Count('id'),
        mine=Count('id', filter=Q(assigned_to=request.user)),
        unassigned=Count('id', filter=Q(assigned_to__isnull=True)),
        escalated=Count('id', filter=Q(escalated_at__isnull=False)),
        **{k: Count('id', filter=q) for k, q in b.items()},
    )
    approvals = sum(1 for r in approval_rows(request, base) if r['status_key'] == 'pending')

    list_url = reverse('psa:ticket_list')

    def link(**params):
        if client_id:
            params = {'client': client_id, **params}
        return f'{list_url}?{urlencode(params)}'

    tiles = [
        {'key': 'open', 'label': 'Open', 'icon': 'fa-folder-open', 'count': c['open'],
         'tone': 'primary', 'href': link(queue='open')},
        {'key': 'mine', 'label': 'Assigned to me', 'icon': 'fa-user-check', 'count': c['mine'],
         'tone': 'primary', 'href': link(assigned='me', queue='open')},
        {'key': 'unassigned', 'label': 'Unassigned', 'icon': 'fa-user-plus',
         'count': c['unassigned'], 'tone': 'warning' if c['unassigned'] else 'neutral',
         'href': link(view='unassigned')},
        {'key': 'at_risk', 'label': 'SLA at risk', 'icon': 'fa-hourglass-half',
         'count': c['at_risk'], 'tone': 'warning' if c['at_risk'] else 'neutral',
         'href': link(view='sla', sla='at_risk')},
        {'key': 'breached', 'label': 'SLA breached', 'icon': 'fa-circle-exclamation',
         'count': c['breached'], 'tone': 'danger' if c['breached'] else 'neutral',
         'href': link(view='sla', sla='breached')},
        {'key': 'approvals', 'label': 'Pending approvals', 'icon': 'fa-circle-check',
         'count': approvals, 'tone': 'warning' if approvals else 'neutral',
         'href': link(view='approvals')},
        {'key': 'escalated', 'label': 'Escalated', 'icon': 'fa-arrow-up-right-dots',
         'count': c['escalated'], 'tone': 'danger' if c['escalated'] else 'neutral',
         'href': link(view='escalated')},
    ]
    sla_rows = [
        {'key': k, 'label': label, 'count': c[k], 'tone': SLA_TONES[k],
         'pct': round(100 * c[k] / c['open']) if c['open'] else 0,
         'href': link(view='sla', sla=k)}
        for k, label in (('breached', 'Breached'), ('at_risk', 'At risk (next 2 h)'),
                         ('on_track', 'On track'), ('paused', 'Paused (waiting)'),
                         ('no_sla', 'No SLA'))
    ]
    return {'tiles': tiles, 'sla_rows': sla_rows, 'open': c['open']}
