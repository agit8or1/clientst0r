"""Read-only routing evaluation.

Nothing in this module writes to the database or sends anything, so the Test
routing page can call it on a real ticket safely. `service.py` is the only
writer; it calls `evaluate()` and then applies the result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    DEST_LEAST_LOADED, DEST_NEAREST, DEST_QUEUE, DEST_ROUND_ROBIN, DEST_SKILL, DEST_TEAM,
    DEST_TECHNICIAN, FALLBACK_QUEUE, MODE_INHERIT, MODE_OFF, PICKING_DESTINATIONS,
    CustomerRoutingSettings, RoundRobinPointer, RoutingRule, RoutingSettings,
)

logger = logging.getLogger('psa.routing')

PROFICIENCY_ORDER = ['beginner', 'intermediate', 'advanced', 'expert']


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

def customer_settings(organization) -> Optional[CustomerRoutingSettings]:
    if organization is None or getattr(organization, 'pk', None) is None:
        return None
    return CustomerRoutingSettings.objects.filter(organization_id=organization.pk).first()


def effective_mode(organization, msp=None, cust=None):
    """(mode, where_from). where_from is 'customer' or 'msp'."""
    msp = msp or RoutingSettings.load()
    cust = cust if cust is not None else customer_settings(organization)
    if cust is not None and cust.mode != MODE_INHERIT:
        return cust.mode, 'customer'
    return msp.mode, 'msp'


# ---------------------------------------------------------------------------
# Customer verification
# ---------------------------------------------------------------------------

def verify_customer(ticket):
    """Is the ticket's customer settled enough to route on?

    Routing reads the customer; it never changes it. A ticket whose customer
    is doubtful is left where intake put it (unassigned, visible in triage).
    """
    org = getattr(ticket, 'organization', None)
    if org is None:
        return False, 'The ticket has no customer.'
    if not org.is_active:
        return False, f'Customer "{org.name}" is inactive.'
    contact = getattr(ticket, 'contact', None) if getattr(ticket, 'contact_id', None) else None
    if contact is not None and contact.organization_id != org.pk:
        return False, 'The requester contact belongs to a different customer.'
    email = (getattr(ticket, 'requester_email', '') or '').strip()
    if email and contact is None:
        try:
            from assets.models import Contact
            homes = set(Contact.objects.filter(email__iexact=email)
                        .values_list('organization_id', flat=True)[:20])
        except Exception:  # noqa: BLE001 — contacts are optional context
            homes = set()
        if homes and org.pk not in homes:
            return False, ('The requester email is a contact at a different customer; '
                           'confirm the customer before routing.')
    return True, f'Customer "{org.name}" verified.'


# ---------------------------------------------------------------------------
# Facts + conditions
# ---------------------------------------------------------------------------

def _tz(name):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(name) if name else timezone.get_default_timezone()
    except Exception:  # noqa: BLE001
        return timezone.get_default_timezone()


def in_business_hours(now: datetime, msp: RoutingSettings, organization=None) -> bool:
    local = now.astimezone(_tz(msp.business_timezone))
    days = msp.business_days if isinstance(msp.business_days, list) else [0, 1, 2, 3, 4]
    if local.weekday() not in days:
        return False
    try:
        from resourcing.models import Holiday
        if Holiday.is_holiday(local.date(), organization):
            return False
    except Exception:  # noqa: BLE001 — resourcing optional
        pass
    return msp.business_start <= local.time() < msp.business_end


def ticket_facts(ticket, now, msp):
    from psa.workflow_engine import _sla_pct_elapsed
    facts = {
        'source': ticket.source or '',
        'ticket_type': getattr(getattr(ticket, 'ticket_type', None), 'slug', '') or '',
        'priority': getattr(getattr(ticket, 'priority', None), 'code', '') or '',
        'queue': getattr(getattr(ticket, 'queue', None), 'name', '') or '',
        'tags': [str(t).strip().lower() for t in (ticket.tags or []) if str(t).strip()],
        'text': f'{ticket.subject or ""}\n{ticket.description or ""}'.lower(),
        'service': '',
        'contract_type': '',
        'business_hours': in_business_hours(now, msp, getattr(ticket, 'organization', None)),
        'sla_pct': 0.0,
        'site_id': getattr(ticket, 'site_id', None),
        'site': '',
    }
    if facts['site_id']:
        facts['site'] = getattr(getattr(ticket, 'site', None), 'name', '') or f'#{facts["site_id"]}'
    try:
        from psa.service_requests import SERVICE_REQUEST_KEY
        rec = (ticket.custom_fields or {}).get(SERVICE_REQUEST_KEY) or {}
        facts['service'] = rec.get('catalog_item_slug') or ''
    except Exception:  # noqa: BLE001
        pass
    try:
        from psa.models import Contract
        contract = Contract.for_ticket(ticket)
        facts['contract_type'] = contract.contract_type if contract else ''
    except Exception:  # noqa: BLE001
        pass
    try:
        facts['sla_pct'] = float(_sla_pct_elapsed(ticket)) if ticket.pk else 0.0
    except Exception:  # noqa: BLE001
        pass
    return facts


def _as_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


def condition_failures(conditions, facts) -> List[str]:
    """Empty list = the conditions match. Otherwise, why not (plain words)."""
    c = conditions or {}
    out = []

    def one_of(key, fact_key, label):
        wanted = _as_list(c.get(key))
        if wanted and facts[fact_key] not in wanted:
            out.append(f'{label} is "{facts[fact_key] or "none"}", not one of {", ".join(wanted)}')

    one_of('sources', 'source', 'intake source')
    one_of('ticket_types', 'ticket_type', 'ticket type')
    one_of('priorities', 'priority', 'priority')
    one_of('queues', 'queue', 'queue')
    one_of('services', 'service', 'service')
    tags = [t.lower() for t in _as_list(c.get('tags_any'))]
    if tags and not set(tags) & set(facts['tags']):
        out.append(f'no tag among {", ".join(tags)}')
    words = [w.lower() for w in _as_list(c.get('keywords_any'))]
    if words and not any(w in facts['text'] for w in words):
        out.append(f'subject/description mention none of {", ".join(words)}')
    contract = c.get('contract') or 'any'
    if contract == 'yes' and not facts['contract_type']:
        out.append('the customer has no active contract')
    if contract == 'no' and facts['contract_type']:
        out.append('the customer has an active contract')
    ctypes = _as_list(c.get('contract_types'))
    if ctypes and facts['contract_type'] not in ctypes:
        out.append(f'contract type is "{facts["contract_type"] or "none"}", not one of {", ".join(ctypes)}')
    site_ids = [str(v) for v in _as_list(c.get('sites'))]
    if site_ids and str(facts.get('site_id') or '') not in site_ids:
        out.append(f'site is "{facts.get("site") or "none"}", not one of the rule\'s sites')
    site_state = c.get('site') or 'any'
    if site_state == 'set' and not facts.get('site_id'):
        out.append('the ticket has no site')
    if site_state == 'unset' and facts.get('site_id'):
        out.append(f'the ticket has a site ({facts.get("site")})')
    hours = c.get('hours') or 'any'
    if hours == 'business' and not facts['business_hours']:
        out.append('it is outside business hours')
    if hours == 'after' and facts['business_hours']:
        out.append('it is inside business hours')
    pct = c.get('sla_pct_at_least')
    if pct not in (None, ''):
        try:
            if facts['sla_pct'] < float(pct):
                out.append(f'SLA elapsed {facts["sla_pct"]:.0f}% is below {float(pct):.0f}%')
        except (TypeError, ValueError):
            out.append('SLA threshold is not a number')
    return out


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def _authorization_problem(user, organization, cust, authorized_ids):
    """None when `user` may be given this customer's tickets, else why not."""
    from psa.visibility import is_msp_staff
    if not user.is_active:
        return 'account is inactive'
    if not is_msp_staff(user):
        return 'not an MSP technician'
    try:
        from accounts.permission_utils import orgs_with_perm
        allowed = orgs_with_perm(user, 'tickets_view')
    except Exception:  # noqa: BLE001
        allowed = None
    if allowed is not None and organization.pk not in allowed:
        return 'not authorized for this customer (no ticket access there)'
    if cust is not None and cust.restrict_technicians and user.pk not in authorized_ids:
        return "not on this customer's authorized technician list"
    try:
        from tech_access.resolver import active_containment
        if active_containment(user) is not None:
            return 'contained by theft detection'
        from tech_access.models import ExplicitDeny
        now = timezone.now()
        denied = (ExplicitDeny.objects.filter(user=user, capability='*')
                  .filter(Q(organization=organization) | Q(organization__isnull=True))
                  .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).exists())
        if denied:
            return 'explicitly denied at this customer'
    except Exception:  # noqa: BLE001 — tech_access optional
        pass
    return None


def _skill_problem(user, skills, min_prof):
    if not skills:
        return None
    from resourcing.models import UserSkill
    have = {s.name.strip().lower(): s.proficiency
            for s in UserSkill.objects.filter(user=user)}
    floor = PROFICIENCY_ORDER.index(min_prof) if min_prof in PROFICIENCY_ORDER else 0
    missing = []
    for s in skills:
        prof = have.get(s.strip().lower())
        if prof is None or (prof in PROFICIENCY_ORDER and PROFICIENCY_ORDER.index(prof) < floor):
            missing.append(s)
    if missing:
        return f'missing skill {", ".join(missing)}' + (f' at {min_prof} or above' if floor else '')
    return None


def _on_call(user, team_id, now):
    """On call now: an on-call shift entered on the Ticket Routing page, or a
    running on-call shift from the weekly shift schedule (Resourcing)."""
    from .models import OnCallShift
    qs = OnCallShift.objects.filter(user=user, starts_at__lte=now, ends_at__gt=now)
    if team_id:
        qs = qs.filter(Q(team__isnull=True) | Q(team_id=team_id))
    if qs.exists():
        return True
    try:
        from resourcing.shifts import on_call_shift
        return on_call_shift(user, now, team_id=team_id) is not None
    except Exception:  # noqa: BLE001 — resourcing optional
        logger.exception('shift schedule on-call lookup failed')
        return False


def _availability_problem(user, now, msp):
    """Leave, then the weekly shift schedule when the technician has one,
    else WorkingHours (resourcing/shifts.py)."""
    try:
        from resourcing.shifts import availability_problem
    except Exception:  # noqa: BLE001
        return None
    return availability_problem(user, now, tz_fallback=msp.business_timezone)


def candidates(ticket, destination, now, msp, cust=None):
    """(eligible users ordered by id, skipped [{user_id, username, reason}])."""
    from django.contrib.auth.models import User
    from psa.visibility import msp_staff_q
    dest = destination or {}
    dtype = dest.get('type')
    org = ticket.organization
    authorized_ids = set()
    if cust is not None and cust.restrict_technicians:
        authorized_ids = set(cust.authorized_technicians.values_list('pk', flat=True))

    if dtype == DEST_TECHNICIAN:
        pool = list(User.objects.filter(pk=dest.get('user_id') or 0))
        if not pool:
            return [], [{'user_id': None, 'username': '?', 'reason': 'the named technician no longer exists'}]
    else:
        # Every active MSP technician; inactive accounts never enter the pool.
        pool = list(User.objects.filter(is_active=True).filter(msp_staff_q())
                    .distinct().order_by('pk'))

    team_id = dest.get('team_id') or None
    team_members = None
    if team_id and dtype != DEST_TECHNICIAN:
        from django.contrib.auth.models import Group
        team_members = set(Group.objects.filter(pk=team_id)
                           .values_list('user__pk', flat=True))
    skills = (_as_list(dest.get('skills'))
              if dtype in (DEST_SKILL, DEST_ROUND_ROBIN, DEST_LEAST_LOADED, DEST_NEAREST) else [])
    min_prof = dest.get('min_proficiency') or ''
    require_on_call = bool(dest.get('require_on_call'))
    require_available = dest.get('require_available', True) is not False

    eligible, skipped = [], []
    for u in pool:
        reason = _authorization_problem(u, org, cust, authorized_ids)
        if reason is None and team_members is not None and u.pk not in team_members:
            reason = 'not in the team'
        if reason is None:
            reason = _skill_problem(u, skills, min_prof)
        if reason is None and require_on_call and not _on_call(u, team_id, now):
            reason = 'not on call now'
        if reason is None and require_available and not require_on_call:
            reason = _availability_problem(u, now, msp)
        elif reason is None and require_on_call:
            # On call overrides working hours, not leave.
            avail = _availability_problem(u, now, msp)
            if avail and 'leave' in avail:
                reason = avail
        if reason:
            skipped.append({'user_id': u.pk, 'username': u.get_username(), 'reason': reason})
        else:
            eligible.append(u)
    eligible.sort(key=lambda u: u.pk)
    return eligible, skipped


def open_loads(users):
    from django.contrib.auth.models import User
    ids = [u.pk for u in users]
    rows = (User.objects.filter(pk__in=ids)
            .annotate(open_count=Count('psa_assigned_tickets', filter=Q(
                psa_assigned_tickets__status__is_terminal=False,
                psa_assigned_tickets__closed_at__isnull=True)))
            .values_list('pk', 'open_count'))
    return dict(rows)


def round_robin_key(rule_id):
    return f'rule:{rule_id}'


def peek_counter(key):
    row = RoundRobinPointer.objects.filter(key=key).values_list('counter', flat=True).first()
    return int(row or 0)


def choose(dtype, eligible, counter=0):
    """Pick from an eligible list. `counter` = round-robin hand-outs so far."""
    if not eligible:
        return None, ''
    if dtype == DEST_ROUND_ROBIN:
        u = eligible[counter % len(eligible)]
        return u, f'round-robin turn {counter + 1} of {len(eligible)} eligible'
    if dtype in (DEST_SKILL, DEST_LEAST_LOADED):
        loads = open_loads(eligible)
        u = sorted(eligible, key=lambda x: (loads.get(x.pk, 0), x.pk))[0]
        label = 'skill match, ' if dtype == DEST_SKILL else ''
        return u, f'{label}least loaded ({loads.get(u.pk, 0)} open tickets)'
    if dtype == DEST_TECHNICIAN:
        return eligible[0], 'named technician'
    return None, ''


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class Evaluation:
    mode: str = MODE_OFF
    mode_source: str = 'msp'
    verified: bool = False
    verification: str = ''
    rule: Optional[RoutingRule] = None
    version: object = None
    considered: list = field(default_factory=list)   # [(rule, version, failures)]
    destination_type: str = ''
    assignee: object = None
    queue: object = None
    team: str = ''
    used_fallback: bool = False
    leave_in_triage: bool = False
    reason: str = ''
    skipped: list = field(default_factory=list)
    eligible: list = field(default_factory=list)
    round_robin_key: str = ''

    @property
    def matched(self):
        return self.rule is not None


def active_rules(organization):
    """[(rule, version)] in evaluation order: this customer's rules, then
    inherited (all-customer) rules; each by priority then age. Only published,
    active versions count."""
    org_id = getattr(organization, 'pk', None)
    qs = (RoutingRule.objects.filter(is_active=True, current_version__isnull=False)
          .filter(Q(organization__isnull=True) | Q(organization_id=org_id))
          .select_related('current_version', 'organization'))
    rows = [(r, r.current_version) for r in qs]
    rows.sort(key=lambda rv: (0 if rv[0].organization_id else 1, rv[1].priority, rv[0].pk))
    return rows


def _queue(queue_id):
    if not queue_id:
        return None
    from psa.models import Queue
    return Queue.objects.filter(pk=queue_id, is_active=True).first()


def evaluate(ticket, *, now=None, msp=None, counter_override=None, ignore_mode=False) -> Evaluation:
    """Decide where `ticket` should go. Pure read.

    `counter_override` lets the service pass the round-robin counter it just
    reserved; otherwise the next turn is peeked without reserving it.
    """
    now = now or timezone.now()
    msp = msp or RoutingSettings.load()
    org = getattr(ticket, 'organization', None)
    cust = customer_settings(org)
    ev = Evaluation()
    ev.mode, ev.mode_source = effective_mode(org, msp=msp, cust=cust)
    if ev.mode == MODE_OFF and not ignore_mode:
        ev.reason = 'Routing is off for this customer.'
        return ev
    ev.verified, ev.verification = verify_customer(ticket)
    if not ev.verified:
        ev.reason = f'Customer not verified: {ev.verification} Left unassigned for triage.'
        ev.leave_in_triage = True
        return ev

    facts = ticket_facts(ticket, now, msp)
    winner = None
    for rule, version in active_rules(org):
        failures = condition_failures(version.conditions, facts)
        ev.considered.append((rule, version, failures))
        if not failures and winner is None:
            winner = (rule, version)
            break
    if winner is None:
        ev.reason = 'No routing rule matched; nothing changes.'
        return ev

    rule, version = winner
    ev.rule, ev.version = rule, version
    dest = version.destination or {}
    dtype = dest.get('type') or DEST_QUEUE
    ev.destination_type = dtype
    dest_queue = _queue(dest.get('queue_id'))
    why = f'Rule "{version.name}" v{version.number}'

    if dtype == DEST_QUEUE:
        if dest_queue is None:
            return _fallback(ev, version, f'{why}: its queue is missing or inactive.')
        ev.queue = dest_queue
        ev.reason = f'{why}: queue {dest_queue.name}, left for the queue to pick up.'
        return ev

    if dtype == DEST_TEAM:
        from django.contrib.auth.models import Group
        team = Group.objects.filter(pk=dest.get('team_id') or 0).first()
        if team is None:
            return _fallback(ev, version, f'{why}: its team no longer exists.')
        ev.team = team.name[:100]
        ev.queue = dest_queue
        ev.reason = f'{why}: team {team.name}' + (f', queue {dest_queue.name}' if dest_queue else '') + '.'
        return ev

    if dtype not in PICKING_DESTINATIONS:
        return _fallback(ev, version, f'{why}: unknown destination "{dtype}".')

    eligible, skipped = candidates(ticket, dest, now, msp, cust)
    if dtype == DEST_NEAREST:
        return _nearest(ev, version, why, ticket, eligible, skipped, dest_queue, now)
    ev.eligible, ev.skipped = eligible, skipped
    if dtype == DEST_ROUND_ROBIN:
        ev.round_robin_key = round_robin_key(rule.pk)
    counter = counter_override if counter_override is not None else (
        peek_counter(ev.round_robin_key) if ev.round_robin_key else 0)
    chosen, how = choose(dtype, eligible, counter)
    if chosen is None:
        n = len(skipped)
        return _fallback(ev, version, f'{why}: nobody qualifies ({n} technician'
                                      f'{"s" if n != 1 else ""} skipped).')
    ev.assignee = chosen
    ev.queue = dest_queue
    ev.reason = f'{why}: {chosen.get_username()} ({how}).'
    return ev


def _nearest(ev, version, why, ticket, eligible, skipped, dest_queue, now):
    """Nearest eligible technician by straight-line distance from their last
    shared position to the ticket's site (field_ops/geo_dispatch.py). Reads
    only; no routing provider is called here. Technicians without a recent
    shared position are skipped with that reason."""
    try:
        from field_ops import geo_dispatch
        cfg = geo_dispatch.load_settings()
    except Exception:  # noqa: BLE001 — field_ops optional
        cfg = None
    if cfg is None or not cfg.enabled:
        ev.eligible, ev.skipped = [], skipped
        return _fallback(ev, version, f'{why}: geo-aware dispatch is switched off.')
    ranked, missing, point = geo_dispatch.nearest(ticket, eligible, now=now, cfg=cfg)
    ev.skipped = skipped + missing
    if point is None:
        ev.eligible = []
        return _fallback(ev, version, f'{why}: the ticket has no site with coordinates '
                                      '(and the customer has no primary site with coordinates).')
    ev.eligible = [u for u, _ in ranked]
    if not ranked:
        n = len(ev.skipped)
        return _fallback(ev, version, f'{why}: nobody qualifies with a recent shared position '
                                      f'({n} technician{"s" if n != 1 else ""} skipped).')
    chosen, est = ranked[0]
    ev.assignee = chosen
    ev.queue = dest_queue
    ev.reason = f'{why}: {chosen.get_username()} (nearest to {point[2]}, {est.label}).'
    return ev


def _fallback(ev, version, why):
    fb = version.fallback or {}
    ev.used_fallback = True
    ev.assignee = None
    q = _queue(fb.get('queue_id')) if fb.get('type') == FALLBACK_QUEUE else None
    if q is not None:
        ev.queue = q
        ev.reason = f'{why} Fallback: queue {q.name}, unassigned.'
    else:
        ev.leave_in_triage = True
        ev.reason = f'{why} Fallback: left unassigned in triage.'
    return ev
