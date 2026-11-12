"""What a rule means, what it collides with, and how it fits with the rest.

Used by the rule review step (shown before saving) and by activation, which
refuses a rule with blocking problems.
"""
from __future__ import annotations

from django.db.models import Q

from .models import (
    DEST_LEAST_LOADED, DEST_NEAREST, DEST_QUEUE, DEST_ROUND_ROBIN, DEST_SKILL, DEST_TEAM, DEST_TECHNICIAN,
    FALLBACK_QUEUE, MODE_OFF, PICKING_DESTINATIONS, RoutingRule,
)

PRECEDENCE = [
    ('Email routing rules',
     'At intake, a sender-domain rule decides which customer an email belongs to and may set its queue and '
     'priority. Routing never changes the customer; it starts from what intake decided.'),
    ('Service catalog defaults',
     'A catalog request is created with the item\'s default queue, priority and type. A routing rule that '
     'names a queue replaces the queue; otherwise the catalog queue stays.'),
    ('Manual assignment and workflow rules',
     'A ticket created with an assignee, or assigned by a workflow rule while it is being saved, keeps that '
     'assignee: routing records "already assigned" and changes nothing.'),
    ('Ticket Routing',
     'Runs after the ticket is saved. Customer rules first, then rules for every customer, each in priority '
     'order; the first rule whose conditions all match wins. Later rules are not evaluated.'),
    ('Reroutes',
     'On a customer reply, a reopen or an SLA threshold (each optional), routing re-evaluates. A person\'s '
     'assignment is kept unless "preserve manual assignments" is switched off, and a current assignee who '
     'still qualifies stays.'),
]

_SOURCE_LABELS = None


def _source_labels():
    global _SOURCE_LABELS
    if _SOURCE_LABELS is None:
        from psa.models import SOURCE_CHOICES
        _SOURCE_LABELS = dict(SOURCE_CHOICES)
    return _SOURCE_LABELS


def _names(model, field, values):
    if not values:
        return []
    return list(model.objects.filter(**{f'{field}__in': values}).values_list('name', flat=True))


def _site_names(ids):
    try:
        from locations.models import Location
        rows = {str(pk): name for pk, name in Location.objects.filter(
            pk__in=[int(i) for i in ids if str(i).isdigit()]).values_list('pk', 'name')}
    except Exception:  # noqa: BLE001
        rows = {}
    return [rows.get(str(i), f'(missing site #{i})') for i in ids]


def summarize(organization, conditions, destination, fallback):
    """One paragraph, plain words."""
    from django.contrib.auth.models import Group, User
    from psa.models import Queue, ServiceCatalogItem, TicketType
    c, d, f = conditions or {}, destination or {}, fallback or {}
    who = f'tickets from {organization.name}' if organization else 'tickets from any customer'
    parts = []
    if c.get('sources'):
        labels = _source_labels()
        parts.append('arriving by ' + ' or '.join(labels.get(s, s) for s in c['sources']))
    if c.get('ticket_types'):
        parts.append('of type ' + ' or '.join(_names(TicketType, 'slug', c['ticket_types']) or c['ticket_types']))
    if c.get('priorities'):
        parts.append('with priority ' + ' or '.join(c['priorities']))
    if c.get('queues'):
        parts.append('in queue ' + ' or '.join(c['queues']))
    if c.get('tags_any'):
        parts.append('tagged ' + ' or '.join(c['tags_any']))
    if c.get('keywords_any'):
        parts.append('mentioning ' + ' or '.join(f'"{w}"' for w in c['keywords_any']))
    if c.get('services'):
        parts.append('requesting ' + ' or '.join(
            _names(ServiceCatalogItem, 'slug', c['services']) or c['services']))
    if c.get('answers'):
        from .engine import answer_condition_text
        parts.append('where the request answer ' + ' and '.join(
            f'"{a.get("field")}" {answer_condition_text(a)}' for a in c['answers']
            if isinstance(a, dict)))
    if c.get('contract') == 'yes':
        parts.append('where the customer has an active contract')
    elif c.get('contract') == 'no':
        parts.append('where the customer has no active contract')
    if c.get('contract_types'):
        parts.append('under a ' + ' or '.join(c['contract_types']) + ' contract')
    if c.get('hours') == 'business':
        parts.append('during business hours')
    elif c.get('hours') == 'after':
        parts.append('outside business hours')
    if c.get('sla_pct_at_least') not in (None, ''):
        parts.append(f'once {c["sla_pct_at_least"]}% of the resolution SLA has elapsed')
    if c.get('sites'):
        parts.append('at site ' + ' or '.join(_site_names(c['sites'])))
    if c.get('site') == 'set':
        parts.append('that name a site')
    elif c.get('site') == 'unset':
        parts.append('that name no site')
    lead = f'For {who}' + (', ' + ', '.join(parts) if parts else '') + ': '

    dtype = d.get('type') or DEST_QUEUE
    queue = Queue.objects.filter(pk=d.get('queue_id') or 0).first()
    team = Group.objects.filter(pk=d.get('team_id') or 0).first()
    team_txt = f' in team {team.name}' if team else ''
    skills = d.get('skills') or []
    skill_txt = (' with skill ' + ' and '.join(skills)
                 + (f' ({d["min_proficiency"]} or above)' if d.get('min_proficiency') else '')) if skills else ''
    oncall = ' who is on call now' if d.get('require_on_call') else ''
    avail = ('' if d.get('require_on_call') or d.get('require_available', True) is False
             else ', skipping anyone on leave or outside their shifts or working hours')
    if dtype == DEST_QUEUE:
        what = f'put it in queue {queue.name if queue else "(missing queue)"} without assigning anyone'
    elif dtype == DEST_TEAM:
        what = f'give it to team {team.name if team else "(missing team)"}' + (
            f' in queue {queue.name}' if queue else '') + ' without picking an individual'
    elif dtype == DEST_TECHNICIAN:
        u = User.objects.filter(pk=d.get('user_id') or 0).first()
        what = f'assign it to {u.get_username() if u else "(missing technician)"}'
    elif dtype == DEST_ROUND_ROBIN:
        what = f'assign it in turn to each authorized technician{team_txt}{skill_txt}{oncall}'
    elif dtype == DEST_SKILL:
        what = f'assign it to the least-busy authorized technician{team_txt}{skill_txt}{oncall}'
    elif dtype == DEST_LEAST_LOADED:
        what = f'assign it to the authorized technician{team_txt}{skill_txt}{oncall} with the fewest open tickets'
    elif dtype == DEST_NEAREST:
        what = (f'assign it to the authorized technician{team_txt}{skill_txt}{oncall} nearest to the ticket\'s '
                'site, by their last shared position')
    else:
        what = f'(unknown destination "{dtype}")'
    if dtype in PICKING_DESTINATIONS:
        what += avail
        if queue is not None and dtype != DEST_TEAM:
            what += f', in queue {queue.name}'
    if f.get('type') == FALLBACK_QUEUE:
        fq = Queue.objects.filter(pk=f.get('queue_id') or 0).first()
        fb = f'put it in queue {fq.name if fq else "(missing queue)"}, unassigned'
    else:
        fb = 'leave it unassigned in triage'
    tail = f'. If nobody qualifies, {fb}, and record why.' if dtype in PICKING_DESTINATIONS else '.'
    return lead + what + tail


def _subsumes(earlier, later):
    """True when every condition `earlier` sets is also set, identically, by
    `later` — so `earlier` matches every ticket `later` matches."""
    e = {k: v for k, v in (earlier or {}).items() if v not in (None, '', [], 'any')}
    lt = {k: v for k, v in (later or {}).items() if v not in (None, '', [], 'any')}
    for k, v in e.items():
        if k not in lt:
            return False
        if isinstance(v, list):
            if not set(map(str, lt[k])) <= set(map(str, v)):
                return False
        elif str(lt[k]) != str(v):
            return False
    return True


def problems(rule_pk, organization, priority, conditions, destination, fallback):
    """(errors, warnings). Errors block activation; warnings are shown."""
    from django.contrib.auth.models import Group, User
    from psa.models import Queue
    errors, warnings = [], []
    d, f = destination or {}, fallback or {}
    dtype = d.get('type') or DEST_QUEUE
    if dtype == DEST_QUEUE:
        if not Queue.objects.filter(pk=d.get('queue_id') or 0, is_active=True).exists():
            errors.append('Choose an active queue for "Queue only".')
    elif d.get('queue_id') and not Queue.objects.filter(pk=d['queue_id'], is_active=True).exists():
        errors.append('The destination queue is inactive or missing.')
    if dtype == DEST_TEAM or d.get('team_id'):
        team = Group.objects.filter(pk=d.get('team_id') or 0).first()
        if team is None:
            errors.append('Choose a team.')
        elif not team.user_set.filter(is_active=True).exists():
            errors.append(f'Team {team.name} has no active members.')
    if dtype == DEST_SKILL and not d.get('skills'):
        errors.append('Skill match needs at least one skill.')
    if dtype == DEST_TECHNICIAN:
        u = User.objects.filter(pk=d.get('user_id') or 0).first()
        if u is None:
            errors.append('Choose a technician.')
        else:
            from psa.visibility import is_msp_staff
            if not u.is_active or not is_msp_staff(u):
                errors.append(f'{u.get_username()} is not an active MSP technician.')
            elif organization is not None:
                from . import engine
                cust = engine.customer_settings(organization)
                ids = set(cust.authorized_technicians.values_list('pk', flat=True)) if cust else set()
                why = engine._authorization_problem(u, organization, cust, ids)
                if why:
                    errors.append(f'{u.get_username()} is {why}.')
    if dtype in PICKING_DESTINATIONS:
        if f.get('type') == FALLBACK_QUEUE and not Queue.objects.filter(
                pk=f.get('queue_id') or 0, is_active=True).exists():
            errors.append('Choose an active fallback queue (or leave unassigned in triage).')
    if d.get('require_on_call'):
        from .models import OnCallShift
        try:
            from resourcing.models import ShiftAssignment
            scheduled = ShiftAssignment.objects.filter(template__is_on_call=True, template__is_active=True).exists()
        except Exception:  # noqa: BLE001
            scheduled = False
        if not OnCallShift.objects.exists() and not scheduled:
            warnings.append('No on-call shifts exist yet; until one is added this rule will always fall back.')
    site_ids = [int(i) for i in (conditions or {}).get('sites') or [] if str(i).isdigit()]
    if site_ids:
        from locations.models import Location
        found = {loc.pk: loc for loc in Location.objects.filter(pk__in=site_ids)}
        missing = [i for i in site_ids if i not in found]
        if missing:
            warnings.append(f'{len(missing)} site(s) in this rule no longer exist; they never match.')
        if organization is not None:
            from psa.ticket_site import site_allowed
            foreign = [loc.name for loc in found.values() if not site_allowed(organization, loc)]
            if foreign:
                errors.append(f'Site(s) {", ".join(foreign)} do not belong to {organization.name}.')
        if (conditions or {}).get('site') == 'unset':
            errors.append('"Has no site" cannot be combined with a list of sites.')
    if dtype == DEST_NEAREST:
        try:
            from field_ops.models import DispatchGeoSettings
            geo_on = DispatchGeoSettings.load().enabled
        except Exception:  # noqa: BLE001
            geo_on = False
        if not geo_on:
            warnings.append('Geo-aware dispatch is switched off (Field Ops → Dispatch locations); until it is on, '
                            'this rule always falls back.')
        else:
            warnings.append('Only technicians who share their position with dispatch and whose position is '
                            'recent are candidates; tickets need a site with coordinates.')
    answer_conds = [a for a in (conditions or {}).get('answers') or [] if isinstance(a, dict)]
    if answer_conds:
        from psa.models import ServiceCatalogItem
        services = (conditions or {}).get('services') or []
        if not services:
            warnings.append('Request-answer conditions only match tickets raised from a request form; '
                            'also pick the request type(s) so the field names are unambiguous.')
        else:
            keys = set()
            for item in ServiceCatalogItem.objects.filter(slug__in=services):
                keys |= {f.get('key') for f in item.get_form_schema()}
            unknown = sorted({a['field'] for a in answer_conds} - keys)
            if unknown:
                warnings.append('No selected request type has a field called '
                                + ', '.join(f'"{k}"' for k in unknown) + '; that condition never matches.')
    if (conditions or {}).get('hours') in ('business', 'after'):
        warnings.append('Business hours come from Ticket Routing settings (MSP-wide) and holidays in Resourcing.')

    org_id = getattr(organization, 'pk', None)
    others = (RoutingRule.objects.filter(is_active=True, current_version__isnull=False)
              .filter(Q(organization__isnull=True) | Q(organization_id=org_id))
              .exclude(pk=rule_pk or 0).select_related('current_version', 'organization'))
    me_key = (0 if org_id else 1, priority)
    for o in others:
        v = o.current_version
        o_key = (0 if o.organization_id else 1, v.priority)
        same_scope = o.organization_id == org_id
        if same_scope and v.priority == priority:
            warnings.append(f'"{o.name}" has the same scope and priority ({priority}); the older rule is '
                            'evaluated first. Give one of them a different priority.')
        earlier = o_key < me_key or (o_key == me_key and (rule_pk is None or o.pk < rule_pk))
        if earlier and _subsumes(v.conditions, conditions):
            warnings.append(f'"{o.name}" is evaluated first and matches every ticket this rule matches, '
                            'so this rule would never win.')
    if organization is not None:
        from .engine import effective_mode
        if effective_mode(organization)[0] == MODE_OFF:
            warnings.append(f'Routing is Off for {organization.name}; this rule has no effect until it is '
                            'switched on.')
    return errors, warnings


def interactions(organization, conditions, destination):
    """Other automation that touches the same tickets, in precedence order."""
    from psa.models import EmailRoutingRule, ServiceCatalogItem, WorkflowRule
    out = []
    org_id = getattr(organization, 'pk', None)
    email_rules = EmailRoutingRule.objects.filter(enabled=True)
    if org_id:
        email_rules = email_rules.filter(target_client_org_id=org_id)
    n_email = email_rules.filter(Q(queue_override__isnull=False) | Q(priority_override__isnull=False)).count()
    if n_email and (not conditions.get('sources') or 'email' in conditions.get('sources', [])):
        out.append(f'{n_email} email routing rule(s) set queue or priority at intake first'
                   + (' for this customer.' if org_id else '.'))
    if not conditions.get('sources') or 'portal' in conditions.get('sources', []):
        n_cat = ServiceCatalogItem.objects.filter(is_active=True, default_queue__isnull=False).count()
        if n_cat:
            out.append(f'{n_cat} service catalog item(s) set a default queue on portal requests; '
                       + ('this rule replaces it.' if (destination or {}).get('queue_id')
                          else 'this rule keeps it (it names no queue).'))
    wf = WorkflowRule.objects.filter(is_active=True, trigger='ticket_created')
    wf = wf.filter(Q(organization__isnull=True) | Q(organization_id=org_id)) if org_id else wf
    assigning = [r.name for r in wf if any(
        (a or {}).get('type', '').startswith('assign') for a in (r.actions or []) + (r.else_actions or []))]
    if assigning:
        out.append('Workflow rule(s) ' + ', '.join(f'"{n}"' for n in assigning[:5])
                   + ' assign on ticket creation and run first; tickets they assign are left alone.')
    return out
