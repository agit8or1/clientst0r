"""Ticket Routing admin pages: settings, customer overrides, rules (with a
review step before saving), on-call shifts, Test routing, triage, and the
dispatcher's accept / reject of suggestions."""
from __future__ import annotations

import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from psa.feature_flags import require_psa_enabled

from . import engine, review, service
from .models import (
    CUSTOMER_MODE_CHOICES, DESTINATION_CHOICES, FALLBACK_CHOICES, FALLBACK_QUEUE,
    FALLBACK_TRIAGE, MODE_CHOICES, PICKING_DESTINATIONS, STATUS_FALLBACK, STATUS_SUGGESTED,
    CustomerRoutingSettings, OnCallShift, RoutingDecision, RoutingRule, RoutingRuleVersion,
    RoutingSettings,
)
from .permissions import (
    PERM_MANAGE, PERM_OVERRIDE, PERM_TEST, can_manage, can_override, can_test,
    require_routing_perm,
)

WEEKDAYS = [(0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'), (4, 'Fri'), (5, 'Sat'), (6, 'Sun')]
PROFICIENCIES = [('', 'Any level'), ('beginner', 'Beginner'), ('intermediate', 'Intermediate'),
                 ('advanced', 'Advanced'), ('expert', 'Expert')]


def _ip(request):
    try:
        from core.client_ip import get_client_ip
        return get_client_ip(request)
    except Exception:  # noqa: BLE001
        return None


def _audit(request, action, obj_type, obj_id, repr_, description, org=None, extra=None):
    AuditLog.log(user=request.user, action=action, organization=org, object_type=obj_type,
                 object_id=obj_id, object_repr=str(repr_)[:200], description=description[:1000],
                 ip_address=_ip(request), path=request.path, extra_data=extra or {})


def _choices():
    from django.contrib.auth.models import Group
    from core.models import Organization
    from psa.models import SOURCE_CHOICES, Queue, ServiceCatalogItem, TicketPriority, TicketType
    from psa.visibility import msp_technicians
    from resourcing.models import UserSkill
    return {
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'sources': SOURCE_CHOICES,
        'ticket_types': TicketType.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'priorities': TicketPriority.objects.order_by('sort_order', 'code'),
        'queues': Queue.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'services': ServiceCatalogItem.objects.filter(is_active=True).order_by('name'),
        'teams': Group.objects.order_by('name'),
        'technicians': msp_technicians(),
        'skills': sorted({n.strip() for n in UserSkill.objects.values_list('name', flat=True) if n.strip()},
                         key=str.lower),
        'contract_types': _contract_types(),
        'destination_choices': DESTINATION_CHOICES,
        'fallback_choices': FALLBACK_CHOICES,
        'proficiencies': PROFICIENCIES,
        'weekdays': WEEKDAYS,
        'sites': _site_choices(),
    }


def _site_choices():
    """Every customer's active sites, labelled with the customer."""
    try:
        from locations.models import Location
        from psa.ticket_site import INACTIVE_STATUSES
        return list(Location.objects.exclude(status__in=INACTIVE_STATUSES)
                    .select_related('organization').order_by('organization__name', 'name')[:2000])
    except Exception:  # noqa: BLE001 — locations optional
        return []


def _contract_types():
    try:
        from psa.models import Contract
        return list(Contract._meta.get_field('contract_type').choices or [])
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Settings + overview
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def overview(request):
    msp = RoutingSettings.load()
    if request.method == 'POST':
        before = {'mode': msp.mode, 'reroute_on_reply': msp.reroute_on_reply,
                  'reroute_on_reopen': msp.reroute_on_reopen, 'reroute_on_sla': msp.reroute_on_sla,
                  'preserve_manual_assignment': msp.preserve_manual_assignment}
        mode = request.POST.get('mode') or 'off'
        msp.mode = mode if mode in dict(MODE_CHOICES) else 'off'
        msp.reroute_on_reply = request.POST.get('reroute_on_reply') == 'on'
        msp.reroute_on_reopen = request.POST.get('reroute_on_reopen') == 'on'
        msp.reroute_on_sla = request.POST.get('reroute_on_sla') == 'on'
        msp.preserve_manual_assignment = request.POST.get('preserve_manual_assignment') == 'on'
        msp.sla_reroute_pct = _int(request.POST.get('sla_reroute_pct'), 75, 1, 100)
        msp.max_reroutes = _int(request.POST.get('max_reroutes'), 5, 0, 50)
        days = sorted({int(d) for d in request.POST.getlist('business_days') if d.isdigit() and int(d) < 7})
        msp.business_days = days
        msp.business_start = _time(request.POST.get('business_start'), msp.business_start)
        msp.business_end = _time(request.POST.get('business_end'), msp.business_end)
        tz = (request.POST.get('business_timezone') or '').strip()[:64]
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except Exception:  # noqa: BLE001
                messages.error(request, f'Unknown time zone "{tz}"; kept the previous one.')
                tz = msp.business_timezone
        msp.business_timezone = tz
        if msp.business_end <= msp.business_start:
            messages.error(request, 'Business hours must end after they start; not saved.')
            return redirect('ticket_routing:overview')
        msp.updated_by = request.user
        msp.save()
        after = {k: getattr(msp, k) for k in before}
        _audit(request, 'update', 'ticket_routing.RoutingSettings', msp.pk, 'Ticket routing settings',
               f'Ticket routing settings saved (mode {msp.get_mode_display()})',
               extra={'changed': {k: [before[k], after[k]] for k in before if before[k] != after[k]}})
        messages.success(request, 'Ticket routing settings saved.')
        return redirect('ticket_routing:overview')

    rules = list(RoutingRule.objects.select_related('organization', 'current_version')
                 .order_by('organization__name', 'priority', 'pk'))
    for r in rules:
        r.summary = r.current_version.summary if r.current_version else ''
    overrides = (CustomerRoutingSettings.objects.select_related('organization')
                 .exclude(mode='inherit', restrict_technicians=False).order_by('organization__name'))
    ctx = {
        'msp': msp, 'rules': rules, 'overrides': overrides, 'precedence': review.PRECEDENCE,
        'mode_choices': MODE_CHOICES, 'customer_mode_choices': CUSTOMER_MODE_CHOICES,
        'can_test': can_test(request.user), 'shift_count': OnCallShift.objects.filter(
            ends_at__gt=timezone.now()).count(),
        'suggested_count': RoutingDecision.objects.filter(status=STATUS_SUGGESTED).count(),
        **_choices(),
    }
    return render(request, 'ticket_routing/overview.html', ctx)


def _int(raw, default, lo, hi):
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


def _time(raw, default):
    try:
        return datetime.strptime((raw or '').strip(), '%H:%M').time()
    except ValueError:
        return default


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['POST'])
def quick_mode(request):
    """The Ticket Routing card on Settings → PSA posts here."""
    msp = RoutingSettings.load()
    mode = request.POST.get('mode') or 'off'
    if mode not in dict(MODE_CHOICES):
        mode = 'off'
    previous = msp.mode
    msp.mode, msp.updated_by = mode, request.user
    msp.save()
    _audit(request, 'update', 'ticket_routing.RoutingSettings', msp.pk, 'Ticket routing settings',
           f'Ticket routing MSP default mode: {previous} → {mode}')
    messages.success(request, f'Ticket routing default set to {msp.get_mode_display()}.')
    nxt = request.POST.get('next') or ''
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else 'ticket_routing:overview')


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def customer_settings(request, org_id):
    from core.models import Organization
    from psa.visibility import msp_technicians
    org = get_object_or_404(Organization, pk=org_id)
    cust = CustomerRoutingSettings.objects.filter(organization=org).first()
    if request.method == 'POST':
        mode = request.POST.get('mode') or 'inherit'
        if mode not in dict(CUSTOMER_MODE_CHOICES):
            mode = 'inherit'
        cust = cust or CustomerRoutingSettings(organization=org)
        cust.mode = mode
        cust.restrict_technicians = request.POST.get('restrict_technicians') == 'on'
        cust.updated_by = request.user
        cust.save()
        ids = [int(x) for x in request.POST.getlist('authorized_technicians') if x.isdigit()]
        cust.authorized_technicians.set(msp_technicians().filter(pk__in=ids))
        _audit(request, 'update', 'ticket_routing.CustomerRoutingSettings', cust.pk, org.name,
               f'Ticket routing for {org.name}: {cust.get_mode_display()}'
               + (f', restricted to {len(ids)} technician(s)' if cust.restrict_technicians else ''), org=org)
        messages.success(request, f'Routing for {org.name} saved.')
        return redirect('ticket_routing:overview')
    msp = RoutingSettings.load()
    return render(request, 'ticket_routing/customer.html', {
        'org': org, 'cust': cust, 'msp': msp,
        'effective': engine.effective_mode(org, msp=msp),
        'customer_mode_choices': CUSTOMER_MODE_CHOICES,
        'technicians': msp_technicians(),
        'authorized_ids': set(cust.authorized_technicians.values_list('pk', flat=True)) if cust else set(),
        'rules': RoutingRule.objects.filter(organization=org).order_by('priority', 'pk'),
    })


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def payload_from_post(post):
    """Visual form → (payload dict). Values are validated against real rows
    on review; unknown ids simply produce review errors."""
    def ids(name):
        return [int(x) for x in post.getlist(name) if str(x).isdigit()]

    def words(name):
        raw = post.get(name) or ''
        return [w.strip() for w in raw.replace(';', ',').split(',') if w.strip()][:20]

    conditions = {
        'sources': [s for s in post.getlist('sources') if s][:20],
        'ticket_types': [s for s in post.getlist('ticket_types') if s][:50],
        'priorities': [s for s in post.getlist('priorities') if s][:20],
        'queues': [s for s in post.getlist('queues') if s][:50],
        'tags_any': [t.lower() for t in words('tags_any')],
        'keywords_any': [w.lower() for w in words('keywords_any')],
        'services': [s for s in post.getlist('services') if s][:50],
        'contract': post.get('contract') if post.get('contract') in ('yes', 'no') else 'any',
        'contract_types': [s for s in post.getlist('contract_types') if s][:20],
        'hours': post.get('hours') if post.get('hours') in ('business', 'after') else 'any',
        'sites': ids('sites')[:50],
        'site': post.get('site') if post.get('site') in ('set', 'unset') else 'any',
    }
    if (post.get('sla_pct_at_least') or '').strip():
        conditions['sla_pct_at_least'] = _int(post.get('sla_pct_at_least'), 0, 0, 1000)
    conditions = {k: v for k, v in conditions.items() if v not in ([], '', None)}
    if conditions.get('site') == 'any':
        conditions.pop('site')
    dtype = post.get('destination_type') or 'queue'
    if dtype not in dict(DESTINATION_CHOICES):
        dtype = 'queue'
    destination = {'type': dtype}
    relevant = {'queue': ('queue_id',), 'team': ('team_id', 'queue_id'),
                'technician': ('user_id', 'queue_id')}.get(dtype, ('team_id', 'queue_id'))
    for key in relevant:
        v = post.get(f'dest_{key}') or ''
        if v.isdigit():
            destination[key] = int(v)
    if dtype in PICKING_DESTINATIONS:
        if dtype != 'technician':
            skills = words('dest_skills')
            if skills:
                destination['skills'] = skills
            prof = post.get('dest_min_proficiency') or ''
            if prof in dict(PROFICIENCIES) and prof:
                destination['min_proficiency'] = prof
        destination['require_on_call'] = post.get('dest_require_on_call') == 'on'
        destination['require_available'] = post.get('dest_require_available') == 'on'
    fb_type = post.get('fallback_type') if post.get('fallback_type') in (FALLBACK_QUEUE, FALLBACK_TRIAGE) \
        else FALLBACK_TRIAGE
    fallback = {'type': fb_type}
    if fb_type == FALLBACK_QUEUE and (post.get('fallback_queue_id') or '').isdigit():
        fallback['queue_id'] = int(post['fallback_queue_id'])
    org_id = post.get('organization') or ''
    return {
        'name': (post.get('name') or '').strip()[:200],
        'description': (post.get('description') or '').strip()[:2000],
        'organization_id': int(org_id) if org_id.isdigit() else None,
        'priority': _int(post.get('priority'), 100, 0, 100000),
        'activate': post.get('activate') == 'on',
        'conditions': conditions,
        'destination': destination,
        'fallback': fallback,
    }


def _payload_org(payload):
    from core.models import Organization
    if not payload.get('organization_id'):
        return None
    return Organization.objects.filter(pk=payload['organization_id']).first()


def _review(payload, rule_pk):
    org = _payload_org(payload)
    errors, warnings = review.problems(rule_pk, org, payload['priority'], payload['conditions'],
                                       payload['destination'], payload['fallback'])
    if not payload['name']:
        errors.insert(0, 'Give the rule a name.')
    if payload.get('organization_id') and org is None:
        errors.insert(0, 'That customer no longer exists.')
    return {
        'org': org,
        'summary': review.summarize(org, payload['conditions'], payload['destination'], payload['fallback']),
        'errors': errors, 'warnings': warnings,
        'interactions': review.interactions(org, payload['conditions'], payload['destination']),
    }


def publish(rule, payload, user, summary):
    """Save the rule and snapshot it as a new version. Touches no ticket."""
    rule.name = payload['name']
    rule.description = payload['description']
    rule.organization_id = payload['organization_id']
    rule.priority = payload['priority']
    rule.conditions = payload['conditions']
    rule.destination = payload['destination']
    rule.fallback = payload['fallback']
    with transaction.atomic():
        if rule.pk is None:
            rule.created_by = user
        rule.save()
        number = (rule.versions.order_by('-number').values_list('number', flat=True).first() or 0) + 1
        version = RoutingRuleVersion.objects.create(
            rule=rule, number=number, name=rule.name, organization_id_snapshot=rule.organization_id,
            priority=rule.priority, conditions=rule.conditions, destination=rule.destination,
            fallback=rule.fallback, summary=summary, published_by=user)
        rule.current_version = version
        rule.save(update_fields=['current_version', 'updated_at'])
    return version


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def rule_form(request, pk=None):
    rule = get_object_or_404(RoutingRule, pk=pk) if pk else None
    if request.method == 'POST':
        step = request.POST.get('step') or 'review'
        if step == 'confirm':
            try:
                payload = json.loads(request.POST.get('payload') or '{}')
                # Re-parse through the same normaliser so a hand-edited
                # payload can't smuggle fields in.
                payload = _normalise_payload(payload)
            except (ValueError, TypeError):
                messages.error(request, 'The review expired; please submit the form again.')
                return redirect(request.path)
            result = _review(payload, rule.pk if rule else None)
            if result['errors'] and not payload['name']:
                messages.error(request, result['errors'][0])
                return redirect(request.path)
            rule = rule or RoutingRule()
            version = publish(rule, payload, request.user, result['summary'])
            if payload['activate'] and result['errors']:
                rule.is_active = False
                messages.error(request, 'Saved but not activated: ' + ' '.join(result['errors']))
            else:
                rule.is_active = payload['activate']
            rule.save(update_fields=['is_active', 'updated_at'])
            _audit(request, 'update' if pk else 'create', 'ticket_routing.RoutingRule', rule.pk, rule.name,
                   f'Routing rule "{rule.name}" saved as v{version.number}'
                   f' ({"active" if rule.is_active else "inactive"}). No existing ticket was changed.',
                   org=result['org'], extra={'summary': result['summary']})
            messages.success(request, f'Saved "{rule.name}" v{version.number}'
                             f'{" and activated" if rule.is_active else ""}. Existing tickets were not changed.')
            return redirect('ticket_routing:rule_detail', pk=rule.pk)
        payload = payload_from_post(request.POST)
        result = _review(payload, rule.pk if rule else None)
        return render(request, 'ticket_routing/rule_review.html', {
            'rule': rule, 'payload': payload, 'payload_json': json.dumps(payload), **result,
        })

    data = {
        'name': rule.name if rule else '', 'description': rule.description if rule else '',
        'organization_id': rule.organization_id if rule else None,
        'priority': rule.priority if rule else 100, 'activate': rule.is_active if rule else True,
        'conditions': rule.conditions if rule else {},
        'destination': rule.destination if rule else {'type': 'round_robin', 'require_available': True},
        'fallback': rule.fallback if rule else {'type': FALLBACK_TRIAGE},
    }
    preset_org = request.GET.get('organization') or ''
    if not rule and preset_org.isdigit():
        data['organization_id'] = int(preset_org)
    return render(request, 'ticket_routing/rule_form.html', {'rule': rule, 'data': data, **_choices()})


def _normalise_payload(raw):
    """Run a review payload back through the form parser."""
    from django.http import QueryDict
    q = QueryDict(mutable=True)
    q['name'] = str(raw.get('name') or '')
    q['description'] = str(raw.get('description') or '')
    q['organization'] = str(raw.get('organization_id') or '')
    q['priority'] = str(raw.get('priority') or 100)
    if raw.get('activate'):
        q['activate'] = 'on'
    c = raw.get('conditions') or {}
    for key in ('sources', 'ticket_types', 'priorities', 'queues', 'services', 'contract_types'):
        q.setlist(key, [str(v) for v in (c.get(key) or [])])
    q['tags_any'] = ','.join(c.get('tags_any') or [])
    q['keywords_any'] = ','.join(c.get('keywords_any') or [])
    q['contract'] = str(c.get('contract') or 'any')
    q['hours'] = str(c.get('hours') or 'any')
    q.setlist('sites', [str(v) for v in (c.get('sites') or [])])
    q['site'] = str(c.get('site') or 'any')
    if c.get('sla_pct_at_least') not in (None, ''):
        q['sla_pct_at_least'] = str(c['sla_pct_at_least'])
    d = raw.get('destination') or {}
    q['destination_type'] = str(d.get('type') or 'queue')
    for key in ('queue_id', 'user_id', 'team_id'):
        if d.get(key):
            q[f'dest_{key}'] = str(d[key])
    q['dest_skills'] = ','.join(d.get('skills') or [])
    q['dest_min_proficiency'] = str(d.get('min_proficiency') or '')
    if d.get('require_on_call'):
        q['dest_require_on_call'] = 'on'
    if d.get('require_available'):
        q['dest_require_available'] = 'on'
    f = raw.get('fallback') or {}
    q['fallback_type'] = str(f.get('type') or FALLBACK_TRIAGE)
    if f.get('queue_id'):
        q['fallback_queue_id'] = str(f['queue_id'])
    return payload_from_post(q)


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
def rule_detail(request, pk):
    rule = get_object_or_404(RoutingRule.objects.select_related('organization', 'current_version'), pk=pk)
    errors, warnings = review.problems(rule.pk, rule.organization, rule.priority, rule.conditions,
                                       rule.destination, rule.fallback)
    return render(request, 'ticket_routing/rule_detail.html', {
        'rule': rule, 'versions': rule.versions.select_related('published_by'),
        'errors': errors, 'warnings': warnings,
        'interactions': review.interactions(rule.organization, rule.conditions, rule.destination),
        'recent': rule.decisions.select_related('ticket', 'new_assignee')[:20],
        'can_test': can_test(request.user),
    })


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['POST'])
def rule_toggle(request, pk):
    rule = get_object_or_404(RoutingRule, pk=pk)
    activate = request.POST.get('activate') == '1'
    if activate:
        errors, _ = review.problems(rule.pk, rule.organization, rule.priority, rule.conditions,
                                    rule.destination, rule.fallback)
        if errors or rule.current_version_id is None:
            messages.error(request, 'Not activated: ' + (' '.join(errors) or 'the rule has no saved version.'))
            return redirect('ticket_routing:rule_detail', pk=rule.pk)
    rule.is_active = activate
    rule.save(update_fields=['is_active', 'updated_at'])
    _audit(request, 'update', 'ticket_routing.RoutingRule', rule.pk, rule.name,
           f'Routing rule "{rule.name}" {"activated" if activate else "deactivated"}. '
           'No existing ticket was changed.', org=rule.organization)
    messages.success(request, f'"{rule.name}" {"activated" if activate else "deactivated"}. '
                     'Existing tickets were not changed.')
    return redirect('ticket_routing:rule_detail', pk=rule.pk)


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['POST'])
def rule_delete(request, pk):
    rule = get_object_or_404(RoutingRule, pk=pk)
    name, org = rule.name, rule.organization
    rule.delete()
    _audit(request, 'delete', 'ticket_routing.RoutingRule', pk, name, f'Routing rule "{name}" deleted.', org=org)
    messages.success(request, f'Deleted "{name}". Routing history that used it is kept.')
    return redirect('ticket_routing:overview')


# ---------------------------------------------------------------------------
# On-call
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def on_call(request):
    from django.contrib.auth.models import Group
    from psa.visibility import msp_technicians
    if request.method == 'POST':
        if request.POST.get('delete'):
            OnCallShift.objects.filter(pk=_int(request.POST.get('delete'), 0, 0, 10 ** 12)).delete()
            messages.success(request, 'Shift removed.')
            return redirect('ticket_routing:on_call')
        user = msp_technicians().filter(pk=_int(request.POST.get('user'), 0, 0, 10 ** 12)).first()
        team = Group.objects.filter(pk=_int(request.POST.get('team'), 0, 0, 10 ** 12)).first()
        starts, ends = _dt(request.POST.get('starts_at')), _dt(request.POST.get('ends_at'))
        if user is None or starts is None or ends is None or ends <= starts:
            messages.error(request, 'Pick a technician and a start before the end.')
            return redirect('ticket_routing:on_call')
        shift = OnCallShift.objects.create(user=user, team=team, starts_at=starts, ends_at=ends,
                                           note=(request.POST.get('note') or '')[:200],
                                           created_by=request.user)
        _audit(request, 'create', 'ticket_routing.OnCallShift', shift.pk, str(shift), f'On-call shift: {shift}')
        messages.success(request, 'Shift added.')
        return redirect('ticket_routing:on_call')
    now = timezone.now()
    return render(request, 'ticket_routing/on_call.html', {
        'shifts': OnCallShift.objects.filter(ends_at__gt=now).select_related('user', 'team'),
        'technicians': msp_technicians(), 'teams': Group.objects.order_by('name'), 'now': now,
    })


def _dt(raw):
    try:
        value = datetime.strptime((raw or '').strip(), '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


# ---------------------------------------------------------------------------
# Test routing (dry run)
# ---------------------------------------------------------------------------

def _ticket_in_scope(user, ticket):
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(user, 'tickets_view')
    return allowed is None or ticket.organization_id in allowed


def _sample_ticket(get):
    """An unsaved Ticket built from the sample form. Never saved."""
    from core.models import Organization
    from psa.models import Queue, Ticket, TicketPriority, TicketStatus, TicketType
    org = Organization.objects.filter(pk=_int(get.get('organization'), 0, 0, 10 ** 12)).first()
    if org is None:
        return None
    t = Ticket(
        organization=org, subject=(get.get('subject') or '')[:300],
        description=(get.get('description') or '')[:2000],
        source=get.get('source') or 'portal',
        queue=Queue.objects.filter(pk=_int(get.get('queue'), 0, 0, 10 ** 12)).first()
        or Queue.objects.filter(is_active=True).first(),
        priority=TicketPriority.objects.filter(code=get.get('priority') or '').first()
        or TicketPriority.objects.order_by('sort_order').first(),
        ticket_type=TicketType.objects.filter(slug=get.get('ticket_type') or '').first()
        or TicketType.objects.filter(is_active=True).first(),
        status=TicketStatus.objects.filter(slug='new').first(),
        tags=[w.strip().lower() for w in (get.get('tags') or '').split(',') if w.strip()],
    )
    site_id = _int(get.get('site'), 0, 0, 10 ** 12)
    if site_id:
        from psa.ticket_site import site_allowed
        from locations.models import Location
        loc = Location.objects.filter(pk=site_id).first()
        if loc is not None and site_allowed(org, loc):
            t.site = loc
    service_slug = (get.get('service') or '').strip()
    if service_slug:
        t.custom_fields = {'service_request': {'catalog_item_slug': service_slug}}
    return t


@login_required
@require_psa_enabled
@require_routing_perm(PERM_TEST)
def test_routing(request):
    """Dry run. Reads only; any accidental write is rolled back; nothing is
    sent. The page says so."""
    from psa.models import Ticket
    result, ticket, error = None, None, ''
    params = request.GET
    at = _dt(params.get('at')) if params.get('at') else None
    if params.get('ticket_number'):
        ticket = (Ticket.objects.select_related('organization', 'priority', 'queue', 'ticket_type',
                                                'status', 'assigned_to', 'site')
                  .filter(ticket_number=params['ticket_number'].strip()).first())
        if ticket is None or not _ticket_in_scope(request.user, ticket):
            error = 'No ticket with that number that you are authorized to see.'
            ticket = None
    elif params.get('organization'):
        ticket = _sample_ticket(params)
        if ticket is None:
            error = 'Choose a customer for the sample ticket.'
    if ticket is not None:
        with transaction.atomic():
            result = engine.evaluate(ticket, now=at, ignore_mode=params.get('ignore_mode') == '1')
            transaction.set_rollback(True)
    return render(request, 'ticket_routing/test.html', {
        'result': result, 'ticket': ticket, 'error': error, 'params': params,
        'is_sample': bool(ticket is not None and ticket.pk is None), **_choices(),
    })


# ---------------------------------------------------------------------------
# Triage + suggestions
# ---------------------------------------------------------------------------

@login_required
@require_psa_enabled
def triage(request):
    from psa.visibility import is_msp_staff
    if not is_msp_staff(request.user):
        raise Http404()
    from django.db.models import OuterRef, Subquery
    from psa.models import Ticket
    latest = (RoutingDecision.objects.filter(ticket=OuterRef('pk'))
              .exclude(trigger='manual').order_by('-created_at', '-pk'))
    qs = (Ticket.objects.filter(assigned_to__isnull=True, closed_at__isnull=True)
          .exclude(status__is_terminal=True)
          .annotate(routing_status=Subquery(latest.values('status')[:1]),
                    routing_reason=Subquery(latest.values('reason')[:1]))
          .filter(routing_status__in=[STATUS_FALLBACK, STATUS_SUGGESTED])
          .select_related('organization', 'priority', 'queue')
          .order_by('priority__sort_order', 'created_at'))
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(request.user, 'tickets_view')
    if allowed is not None:
        qs = qs.filter(organization_id__in=allowed)

    # Narrowing filters (saved views: core.workspace SAVED_VIEW_LISTS['routing_triage']).
    # Every choice comes from the scoped queryset, so a filter only hides rows.
    from core.models import Organization
    from psa.models import TicketPriority
    in_scope = qs
    customer_ids = set(in_scope.values_list('organization_id', flat=True).distinct())
    priority_ids = set(in_scope.values_list('priority_id', flat=True).distinct()) - {None}
    client = request.GET.get('client') or ''
    if client.isdigit() and int(client) in customer_ids:
        qs = qs.filter(organization_id=int(client))
    else:
        client = ''
    routing = request.GET.get('routing') or ''
    if routing == 'suggested':
        qs = qs.filter(routing_status=STATUS_SUGGESTED)
    elif routing == 'fallback':
        qs = qs.filter(routing_status=STATUS_FALLBACK)
    else:
        routing = ''
    priority = request.GET.get('priority') or ''
    if priority.isdigit() and int(priority) in priority_ids:
        qs = qs.filter(priority_id=int(priority))
    else:
        priority = ''
    q = (request.GET.get('q') or '').strip()[:100]
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(ticket_number__icontains=q) | Q(subject__icontains=q))
    total_waiting = in_scope.count()
    return render(request, 'ticket_routing/triage.html', {
        'tickets': qs[:500],
        'can_override': can_override(request.user),
        'customers': Organization.objects.filter(pk__in=customer_ids).order_by('name').values('pk', 'name')
                     if len(customer_ids) > 1 else [],
        'priorities': TicketPriority.objects.filter(pk__in=priority_ids).order_by('sort_order'),
        'filters': {'client': client, 'routing': routing, 'priority': priority, 'q': q},
        'has_filters': bool(client or routing or priority or q),
        'total_waiting': total_waiting,
    })


@login_required
@require_psa_enabled
@require_routing_perm(PERM_OVERRIDE)
@require_http_methods(['POST'])
def decide(request, pk):
    d = get_object_or_404(RoutingDecision.objects.select_related('ticket'), pk=pk)
    if not _ticket_in_scope(request.user, d.ticket):
        raise PermissionDenied('Not authorized for this customer.')
    if request.POST.get('decision') == 'accept':
        d, msg = service.accept_suggestion(d.pk, request.user)
    else:
        d, msg = service.reject_suggestion(d.pk, request.user)
    _audit(request, 'update', 'ticket_routing.RoutingDecision', d.pk, d.ticket.ticket_number,
           f'Routing suggestion for {d.ticket.ticket_number}: {d.get_status_display()}. {msg}',
           org=d.ticket.organization)
    messages.info(request, msg)
    nxt = request.POST.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect('psa:ticket_detail', ticket_number=d.ticket.ticket_number)
