"""Alert policy admin pages: settings, rules, maintenance windows, and the
recent alert log. Staff with "routing_manage_rules" only."""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from psa.feature_flags import require_psa_enabled

from .models import (
    AFTER_HOURS_CHOICES, ALERT_ACTION_CHOICES, ALERT_CATEGORY_CHOICES, ALERT_MODE_CHOICES, ALERT_SEVERITY_CHOICES,
    ASSIGN_CHOICES, ASSIGN_TECHNICIAN, MAINT_AFTER_CHOICES, RECOVERY_CHOICES, AlertMaintenanceWindow,
    AlertPolicyRule, AlertPolicySettings, AlertTicketLink,
)
from .permissions import PERM_MANAGE, require_routing_perm
from .views import _audit, _dt, _int

CATEGORY_KEYS = {k for k, _ in ALERT_CATEGORY_CHOICES}
SEVERITY_KEYS = {k for k, _ in ALERT_SEVERITY_CHOICES}


def _pick(post, name, allowed):
    return [v for v in post.getlist(name) if v in allowed]


def _lookups():
    from core.models import Organization
    from psa.models import Queue, TicketPriority, TicketType
    from psa.visibility import msp_technicians
    return {
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'queues': Queue.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'priorities': TicketPriority.objects.order_by('sort_order', 'code'),
        'ticket_types': TicketType.objects.filter(is_active=True).order_by('sort_order', 'name'),
        'technicians': msp_technicians(),
        'mode_choices': ALERT_MODE_CHOICES, 'action_choices': ALERT_ACTION_CHOICES,
        'category_choices': ALERT_CATEGORY_CHOICES, 'severity_choices': ALERT_SEVERITY_CHOICES,
        'assign_choices': ASSIGN_CHOICES, 'after_hours_choices': AFTER_HOURS_CHOICES,
        'recovery_choices': RECOVERY_CHOICES, 'maint_after_choices': MAINT_AFTER_CHOICES,
    }


def _fk(model, raw, **extra):
    pk = _int(raw, 0, 0, 10 ** 12)
    return model.objects.filter(pk=pk, **extra).first() if pk else None


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def alerts(request):
    from psa.models import Queue
    s = AlertPolicySettings.load()
    if request.method == 'POST':
        before = (s.mode, s.include_rmm_sync)
        s.mode = request.POST.get('mode') if request.POST.get('mode') in dict(ALERT_MODE_CHOICES) else s.mode
        s.include_rmm_sync = request.POST.get('include_rmm_sync') == 'on'
        s.default_action = (request.POST.get('default_action')
                            if request.POST.get('default_action') in dict(ALERT_ACTION_CHOICES) else s.default_action)
        s.default_queue = _fk(Queue, request.POST.get('default_queue'), is_active=True)
        s.offline_hold_minutes = _int(request.POST.get('offline_hold_minutes'), 5, 0, 120)
        s.site_outage_threshold = _int(request.POST.get('site_outage_threshold'), 5, 0, 1000)
        s.site_outage_window_minutes = _int(request.POST.get('site_outage_window_minutes'), 15, 1, 240)
        s.post_recovery_notes = request.POST.get('post_recovery_notes') == 'on'
        s.updated_by = request.user
        s.save()
        _audit(request, 'update', 'ticket_routing.AlertPolicySettings', 1, 'Alert policy settings',
               f'Alert policy settings saved (mode {s.mode}, RMM sync {s.include_rmm_sync}; was {before}).')
        messages.success(request, 'Alert policy saved.')
        return redirect('ticket_routing:alerts')
    ctx = _lookups()
    ctx.update({
        'settings': s,
        'rules': AlertPolicyRule.objects.select_related('organization', 'queue', 'ticket_priority', 'assign_user'),
        'recent': AlertTicketLink.objects.select_related('organization', 'ticket', 'connection')[:50],
    })
    return render(request, 'ticket_routing/alerts.html', ctx)


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def alert_rule_form(request, pk=None):
    from core.models import Organization
    from psa.models import Queue, TicketPriority, TicketType
    from psa.visibility import msp_technicians
    rule = get_object_or_404(AlertPolicyRule, pk=pk) if pk else AlertPolicyRule()
    if request.method == 'POST':
        if request.POST.get('delete') and rule.pk:
            _audit(request, 'delete', 'ticket_routing.AlertPolicyRule', rule.pk, rule.name,
                   f'Alert rule deleted: {rule.name}', org=rule.organization)
            rule.delete()
            messages.success(request, 'Alert rule deleted.')
            return redirect('ticket_routing:alerts')
        p = request.POST
        rule.name = (p.get('name') or '').strip()[:200] or 'Alert rule'
        rule.organization = _fk(Organization, p.get('organization'))
        rule.priority = _int(p.get('priority'), 100, 0, 100000)
        rule.is_active = p.get('is_active') == 'on'
        rule.conditions = {
            'sources': [v for v in p.getlist('sources') if v in ('rem0te', 'rmm')],
            'categories': _pick(p, 'categories', CATEGORY_KEYS),
            'severities': _pick(p, 'severities', SEVERITY_KEYS),
            'sites': [x.strip()[:255] for x in (p.get('sites') or '').split(',') if x.strip()][:50],
        }
        rule.action = p.get('action') if p.get('action') in dict(ALERT_ACTION_CHOICES) else rule.action
        rule.queue = _fk(Queue, p.get('queue'), is_active=True)
        rule.ticket_priority = _fk(TicketPriority, p.get('ticket_priority'))
        rule.ticket_type = _fk(TicketType, p.get('ticket_type'))
        rule.assign_mode = p.get('assign_mode') if p.get('assign_mode') in dict(ASSIGN_CHOICES) else rule.assign_mode
        rule.assign_user = (msp_technicians().filter(pk=_int(p.get('assign_user'), 0, 0, 10 ** 12)).first()
                            if rule.assign_mode == ASSIGN_TECHNICIAN else None)
        rule.after_hours = p.get('after_hours') if p.get('after_hours') in dict(AFTER_HOURS_CHOICES) else rule.after_hours
        esc = _int(p.get('escalate_after_minutes'), 0, 0, 100000)
        rule.escalate_after_minutes = esc or None
        rule.escalation_priority = _fk(TicketPriority, p.get('escalation_priority'))
        rule.escalation_queue = _fk(Queue, p.get('escalation_queue'), is_active=True)
        rule.on_recovery = p.get('on_recovery') if p.get('on_recovery') in dict(RECOVERY_CHOICES) else rule.on_recovery
        if not rule.pk:
            rule.created_by = request.user
        rule.save()
        _audit(request, 'update', 'ticket_routing.AlertPolicyRule', rule.pk, rule.name,
               f'Alert rule saved: {rule.name}', org=rule.organization, extra={'rule': rule.snapshot()})
        messages.success(request, 'Alert rule saved. Alerts already handled keep the rule as it was.')
        return redirect('ticket_routing:alerts')
    ctx = _lookups()
    ctx['rule'] = rule
    ctx['sites_text'] = ', '.join((rule.conditions or {}).get('sites') or [])
    return render(request, 'ticket_routing/alert_rule_form.html', ctx)


@login_required
@require_psa_enabled
@require_routing_perm(PERM_MANAGE)
@require_http_methods(['GET', 'POST'])
def alert_maintenance(request):
    from core.models import Organization
    if request.method == 'POST':
        if request.POST.get('cancel'):
            w = AlertMaintenanceWindow.objects.filter(pk=_int(request.POST.get('cancel'), 0, 0, 10 ** 12)).first()
            if w is not None:
                w.is_cancelled = True
                w.save(update_fields=['is_cancelled'])
                _audit(request, 'update', 'ticket_routing.AlertMaintenanceWindow', w.pk, str(w),
                       f'Maintenance window cancelled: {w}', org=w.organization)
            return redirect('ticket_routing:alert_maintenance')
        org = _fk(Organization, request.POST.get('organization'), is_active=True)
        starts, ends = _dt(request.POST.get('starts_at')), _dt(request.POST.get('ends_at'))
        if org is None or starts is None or ends is None or ends <= starts:
            messages.error(request, 'Pick a customer and a start before the end.')
            return redirect('ticket_routing:alert_maintenance')
        w = AlertMaintenanceWindow.objects.create(
            organization=org, site_name=(request.POST.get('site_name') or '').strip()[:255],
            categories=_pick(request.POST, 'categories', CATEGORY_KEYS), starts_at=starts, ends_at=ends,
            reason=(request.POST.get('reason') or '')[:300],
            after_window=(request.POST.get('after_window') if request.POST.get('after_window')
                          in dict(MAINT_AFTER_CHOICES) else 'ticket_if_open'),
            created_by=request.user)
        _audit(request, 'create', 'ticket_routing.AlertMaintenanceWindow', w.pk, str(w),
               f'Maintenance window: {w}', org=org)
        messages.success(request, 'Maintenance window added.')
        return redirect('ticket_routing:alert_maintenance')
    ctx = _lookups()
    ctx.update({'windows': AlertMaintenanceWindow.objects.filter(ends_at__gt=timezone.now() - timedelta(days=7))
                .select_related('organization', 'device'), 'now': timezone.now()})
    return render(request, 'ticket_routing/alert_maintenance.html', ctx)
