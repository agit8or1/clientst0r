"""Pricing Advisor pages (Reports → Pricing Advisor). MSP staff only; see
advisor.permissions for who sees which customer and who may act."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Organization

from . import permissions as perms
from .actions import ActionRefused, accept as do_accept, dismiss as do_dismiss, sync_implemented
from .detectors import REGISTRY
from .models import AdvisorRun, AdvisorSettings, Finding, Recommendation

BANNER = 'Operational estimates — not your accounting P&L.'
FACT_ORDER = ('revenue', 'mrr', 'arr', 'labor_cost', 'licensing_cost', 'hardware_cost', 'delivery_cost',
              'total_cost', 'gross_profit', 'gross_margin', 'labor_margin', 'utilization', 'unbilled',
              'leakage', 'leakage_hours')


def _require_any(request):
    if not perms.can_view_any(request.user):
        raise PermissionDenied('The Pricing Advisor needs the profitability permission (MSP staff only).')


def _finding_or_404(request, pk):
    finding = get_object_or_404(Finding.objects.select_related('client_org'), pk=pk)
    if not perms.can_view_client(request.user, finding.client_org):
        raise Http404
    return finding


def _sources():
    from .inputs import sources
    labels = {'cost_rates': 'Labour cost rates', 'monthly_amount': 'Recurring amounts',
              'licensing': 'Vendor / licensing costs', 'pricing': 'Price book and service plans',
              'distributor_prices': 'Distributor prices'}
    return [(labels[k], v or 'not tracked on this install — margins that need it are marked incomplete')
            for k, v in sources().items()]


def _coverage():
    last = AdvisorRun.objects.filter(finished_at__isnull=False).first()
    if last is not None and last.coverage:
        return last, last.coverage
    from .engine import coverage
    return last, coverage()


@login_required
def finding_list(request):
    _require_any(request)
    qs = perms.filter_findings(Finding.objects.select_related('client_org'), request.user)
    status = request.GET.get('status', 'open')
    if status in dict(Finding.STATUS_CHOICES):
        qs = qs.filter(status=status)
    severity = request.GET.get('severity', '')
    if severity in dict(Finding.SEVERITY_CHOICES):
        qs = qs.filter(severity=severity)
    detector = request.GET.get('detector', '')
    if detector in REGISTRY:
        qs = qs.filter(detector=detector)
    client = request.GET.get('client', '')
    if client.isdigit():
        qs = qs.filter(client_org_id=int(client))
    complete = request.GET.get('complete', '')
    if complete in ('yes', 'no'):
        qs = qs.filter(is_complete=complete == 'yes')
    groups = []
    rows = list(qs.order_by('client_org__name', 'detector')[:1000])
    for key, label in Finding.SEVERITY_CHOICES:
        items = [f for f in rows if f.severity == key]
        if items:
            groups.append({'key': key, 'label': label, 'findings': items})
    visible = perms.visible_client_ids(request.user)
    clients = Organization.objects.filter(advisor_findings__isnull=False).distinct().order_by('name')
    if visible is not None:
        clients = clients.filter(pk__in=visible)
    last_run, coverage = _coverage()
    return render(request, 'advisor/finding_list.html', {
        'banner': BANNER, 'groups': groups, 'count': len(rows), 'last_run': last_run, 'coverage': coverage,
        'detectors': [(k, d.label) for k, d in REGISTRY.items()], 'clients': clients,
        'severities': Finding.SEVERITY_CHOICES, 'statuses': Finding.STATUS_CHOICES,
        'f': {'status': status, 'severity': severity, 'detector': detector, 'client': client,
              'complete': complete},
        'can_edit_defaults': request.user.is_superuser, 'sources': _sources(),
    })


def _ordered_facts(facts):
    out = [facts[k] for k in FACT_ORDER if k in facts]
    out += [v for k, v in facts.items() if k not in FACT_ORDER]
    return out


@login_required
def finding_detail(request, pk):
    _require_any(request)
    finding = _finding_or_404(request, pk)
    sync_implemented(finding.recommendations.filter(status='accepted'))
    from . import ai
    narrative = ai.cached(finding)
    return render(request, 'advisor/finding_detail.html', {
        'banner': BANNER, 'finding': finding, 'facts': _ordered_facts(finding.facts or {}),
        'recommendations': list(finding.recommendations.select_related(
            'contract', 'draft_quote', 'draft_contract', 'decided_by')),
        'can_act': perms.can_act(request.user, finding.client_org),
        'can_ai': perms.can_use_ai(request.user, finding.client_org),
        'narrative': narrative,
    })


@login_required
@require_POST
def recommendation_accept(request, pk):
    _require_any(request)
    rec = get_object_or_404(Recommendation.objects.select_related('finding__client_org', 'contract'), pk=pk)
    if not perms.can_view_client(request.user, rec.finding.client_org):
        raise Http404
    try:
        rec = do_accept(rec, request.user, request)
    except ActionRefused as e:
        if not perms.can_act(request.user, rec.finding.client_org):
            raise PermissionDenied(str(e))
        messages.error(request, str(e))
        return redirect('advisor:finding_detail', rec.finding_id)
    if rec.draft_contract_id:
        messages.success(request, 'Draft contract amendment created. The active contract is unchanged; '
                                  'review the draft and activate it through the usual flow.')
    else:
        messages.success(request, f'Draft quote {rec.draft_quote.quote_number} created. Nothing was sent.')
    return redirect('advisor:finding_detail', rec.finding_id)


@login_required
@require_POST
def recommendation_dismiss(request, pk):
    _require_any(request)
    rec = get_object_or_404(Recommendation.objects.select_related('finding__client_org'), pk=pk)
    if not perms.can_view_client(request.user, rec.finding.client_org):
        raise Http404
    try:
        do_dismiss(rec, request.user, request.POST.get('reason', ''), request)
    except ActionRefused as e:
        if not perms.can_act(request.user, rec.finding.client_org):
            raise PermissionDenied(str(e))
        messages.error(request, str(e))
    else:
        messages.success(request, 'Recommendation dismissed.')
    return redirect('advisor:finding_detail', rec.finding_id)


@login_required
@require_POST
def finding_explain(request, pk):
    """OPTIONAL AI: never required, never changes anything."""
    _require_any(request)
    finding = _finding_or_404(request, pk)
    from . import ai
    if not perms.can_use_ai(request.user, finding.client_org):
        raise PermissionDenied('AI explanations are off, or you lack the AI capability for this customer.')
    try:
        narrative = ai.explain(finding, request.user, request)
    except ai.NarrativeRefused as e:
        messages.error(request, f'No AI explanation: {e}')
    else:
        if narrative.status == 'rejected':
            messages.warning(request, 'The AI explanation used figures that are not in the facts, so it was '
                                      'discarded. The calculated summary is shown instead.')
    return redirect('advisor:finding_detail', finding.pk)


@login_required
def client_facts(request, org_id):
    """Trailing 1 / 3 / 6 / 12-month facts for one customer, computed now."""
    _require_any(request)
    client = get_object_or_404(Organization, pk=org_id)
    if not perms.can_view_client(request.user, client):
        raise Http404
    from .facts import CustomerFacts, last_full_month_end, window_ending
    from .inputs import Rates
    rates = Rates()
    settings = AdvisorSettings.for_client(client)
    as_of = last_full_month_end(timezone.localdate())
    windows = []
    for months in (1, 3, 6, 12):
        w = window_ending(as_of, months)
        facts = CustomerFacts(client, w, rates, settings).summary()
        windows.append({'window': w, 'facts': {k: v.as_json() for k, v in facts.items()}})
    keys = [k for k in FACT_ORDER if k in windows[0]['facts']]
    table = [{'key': k, 'label': windows[0]['facts'][k]['label'], 'unit': windows[0]['facts'][k]['unit'],
              'cells': [w['facts'][k] for w in windows]} for k in keys]
    findings = Finding.objects.filter(client_org=client, status='open').order_by('severity')
    return render(request, 'advisor/client_facts.html', {
        'banner': BANNER, 'client': client, 'windows': windows, 'table': table, 'findings': findings,
        'settings_row': settings,
    })


def _parse_settings(row, post):
    errors = []
    for name in AdvisorSettings.THRESHOLD_FIELDS:
        raw = (post.get(name) or '').strip()
        if raw == '':
            continue
        field = AdvisorSettings._meta.get_field(name)
        try:
            value = Decimal(raw) if field.get_internal_type() == 'DecimalField' else int(raw)
        except (InvalidOperation, ValueError):
            errors.append(f'{field.verbose_name}: not a number.')
            continue
        if value < 0:
            errors.append(f'{field.verbose_name}: must not be negative.')
            continue
        setattr(row, name, value)
    if row.lookback_months not in (3, 6, 12):
        errors.append('Window must be 3, 6 or 12 months.')
    if row.target_margin_pct >= 100:
        errors.append('Target margin must be below 100%.')
    if row.renewal_min_days > row.renewal_max_days:
        errors.append('Renewal window: the first day must not be after the last.')
    row.disabled_detectors = [k for k in REGISTRY if post.get(f'detector_{k}') != 'on']
    return errors


@login_required
def settings_view(request):
    """Thresholds: install-wide (superusers) or one customer (?client=ID; needs
    act_on_pricing_recommendations there)."""
    _require_any(request)
    client = None
    client_id = request.GET.get('client') or request.POST.get('client') or ''
    if client_id.isdigit():
        client = get_object_or_404(Organization, pk=int(client_id))
        if not perms.can_act(request.user, client):
            raise PermissionDenied('Changing a customer\'s advisor thresholds needs act_on_pricing_recommendations.')
        row = AdvisorSettings.objects.filter(organization=client).first() or AdvisorSettings(
            organization=client, **AdvisorSettings.for_client(client).thresholds())
    else:
        if not request.user.is_superuser:
            raise PermissionDenied('Install-wide advisor thresholds are superuser only.')
        row = AdvisorSettings.objects.filter(organization__isnull=True).first() or AdvisorSettings()
    if request.method == 'POST':
        before = row.thresholds()
        errors = _parse_settings(row, request.POST)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            row.updated_by = request.user
            row.save()
            from audit.models import AuditLog
            from core.client_ip import get_client_ip
            AuditLog.log(user=request.user, action='update', organization=client,
                         object_type='advisor.AdvisorSettings', object_id=row.pk, object_repr=str(row)[:255],
                         description='Pricing Advisor thresholds changed.', ip_address=get_client_ip(request),
                         path=request.path, extra_data={'event': 'advisor_settings_changed',
                                                        'before': {k: str(v) for k, v in before.items()},
                                                        'after': {k: str(v) for k, v in row.thresholds().items()}})
            messages.success(request, 'Thresholds saved. They apply from the next advisor run.')
            return redirect(request.path + (f'?client={client.pk}' if client else ''))
    fields = [{'name': n, 'label': AdvisorSettings._meta.get_field(n).verbose_name.capitalize(),
               'help': AdvisorSettings._meta.get_field(n).help_text, 'value': getattr(row, n)}
              for n in AdvisorSettings.THRESHOLD_FIELDS]
    detectors = [{'key': k, 'label': d.label, 'on': k not in (row.disabled_detectors or [])}
                 for k, d in REGISTRY.items()]
    return render(request, 'advisor/settings.html', {
        'banner': BANNER, 'client': client, 'fields': fields, 'detectors': detectors})
