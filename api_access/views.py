"""Settings → Security → API Access Control (superusers, like the other
security settings pages)."""
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.models import AuditLog

from . import policy as P
from .forms import ImportForm, LimitsForm, ModeForm, RuleForm, TestAddressForm
from .groups import ENDPOINT_GROUPS, INTEGRATIONS
from .models import ApiAccessDecision, ApiAccessRule, ApiAccessSettings, normalize_network
from .preview import build_policy_for_rule, explain_client_address, impact, row_for, rule_rows, settings_row
from .enforce import client_ip_text


def _superuser(user):
    return user.is_superuser


guard = [login_required, user_passes_test(_superuser)]


def _guarded(view):
    for deco in reversed(guard):
        view = deco(view)
    return view


def _audit(request, action, rule=None, description='', extra=None):
    AuditLog.log(user=request.user, action=action, object_type='ApiAccessRule' if rule else 'ApiAccessSettings',
                 object_id=getattr(rule, 'pk', None), object_repr=str(rule or 'API access settings')[:200],
                 description=description, ip_address=client_ip_text(request) or None,
                 path=request.path, extra_data=extra or {})


def _changed(request):
    ApiAccessSettings.bump(request.user)
    P.reset_cache()


@_guarded
def index(request):
    s = ApiAccessSettings.get()
    rules = ApiAccessRule.objects.select_related('organization', 'api_key', 'created_by', 'updated_by')
    q = (request.GET.get('q') or '').strip()
    f_action = request.GET.get('action', '')
    f_scope = request.GET.get('scope', '')
    f_status = request.GET.get('status', '')
    if q:
        rules = rules.filter(Q(name__icontains=q) | Q(network__icontains=q) | Q(description__icontains=q))
    if f_action in dict(ApiAccessRule.ACTIONS):
        rules = rules.filter(action=f_action)
    if f_scope in dict(ApiAccessRule.SCOPES):
        rules = rules.filter(scope=f_scope)
    rules = list(rules)
    if f_status in ('active', 'disabled', 'expired'):
        rules = [r for r in rules if r.status == f_status]
    since = timezone.now() - timedelta(hours=24)
    recent = ApiAccessDecision.objects.filter(created_at__gte=since)
    stats = recent.aggregate(rows=Count('id'), total=Sum('count'))
    top_sources = (recent.values('source_ip').annotate(total=Sum('count'))
                   .order_by('-total')[:5])
    return render(request, 'api_access/index.html', {
        'settings_obj': s, 'rules': rules, 'mode_form': ModeForm(initial={
            'api_mode': s.api_mode, 'webhook_mode': s.webhook_mode}),
        'q': q, 'f_action': f_action, 'f_scope': f_scope, 'f_status': f_status,
        'scopes': ApiAccessRule.SCOPES, 'actions': ApiAccessRule.ACTIONS,
        'denied_24h': stats['total'] or 0, 'top_sources': top_sources,
        'recent': ApiAccessDecision.objects.select_related('rule')[:8],
        'your_ip': client_ip_text(request), 'reasons': P.REASONS,
        'mode_help': ApiAccessSettings.MODE_HELP, 'mode_choices': ApiAccessSettings.MODES,
        'limits_form': LimitsForm(initial={f: getattr(s, f) for f in LimitsForm.base_fields}),
    })


@_guarded
@require_POST
def limits_update(request):
    form = LimitsForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Limits must be whole numbers (0 turns a limit off).')
        return redirect('api_access:index')
    s = ApiAccessSettings.get()
    before = {f: getattr(s, f) for f in LimitsForm.base_fields}
    after = dict(form.cleaned_data)
    if before == after:
        messages.info(request, 'Nothing changed.')
        return redirect('api_access:index')
    ApiAccessSettings.objects.filter(pk=1).update(**after)
    _changed(request)
    _audit(request, 'update', description='API access limits changed', extra={'before': before, 'after': after})
    messages.success(request, 'Limits saved.')
    return redirect('api_access:index')


@_guarded
@require_POST
def mode_update(request):
    s = ApiAccessSettings.get()
    form = ModeForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Choose a mode for each surface.')
        return redirect('api_access:index')
    new = {'api_mode': form.cleaned_data['api_mode'], 'webhook_mode': form.cleaned_data['webhook_mode']}
    if new == {'api_mode': s.api_mode, 'webhook_mode': s.webhook_mode}:
        messages.info(request, 'Nothing changed.')
        return redirect('api_access:index')
    proposed = P.build_policy(settings_row(**new), rule_rows())
    preview = impact(proposed, client_ip_text(request))
    if preview['high_impact'] and not form.cleaned_data['confirm']:
        modes = dict(ApiAccessSettings.MODES)
        return render(request, 'api_access/confirm_mode.html', {
            'new': new, 'preview': preview,
            'labels': {'api': modes[new['api_mode']], 'webhook': modes[new['webhook_mode']]}})
    old = {'api_mode': s.api_mode, 'webhook_mode': s.webhook_mode}
    ApiAccessSettings.objects.filter(pk=1).update(**new)
    _changed(request)
    _audit(request, 'update', description='API access mode changed',
           extra={'before': old, 'after': new, 'refused_keys': [k['prefix'] for k in preview['keys']]})
    messages.success(request, 'API access mode saved. It applies from the next request.')
    return redirect('api_access:index')


def _rule_form_page(request, rule):
    creating = rule.pk is None
    form = RuleForm(request.POST or None, instance=rule)
    preview = None
    if request.method == 'POST' and form.is_valid():
        candidate = form.save(commit=False)
        candidate.clean()
        proposed = build_policy_for_rule(candidate, exclude_id=rule.pk)
        preview = impact(proposed, client_ip_text(request))
        if preview['high_impact'] and request.POST.get('confirm') != '1':
            return render(request, 'api_access/rule_form.html', {
                'form': form, 'rule': rule, 'creating': creating, 'preview': preview,
                'history': _history(rule)})
        with transaction.atomic():
            if creating:
                candidate.created_by = request.user
            candidate.updated_by = request.user
            candidate.save()
        _changed(request)
        _audit(request, 'create' if creating else 'update', candidate,
               description=f'API access rule {"created" if creating else "updated"}: {candidate}',
               extra={'network': candidate.network, 'action': candidate.action,
                      'scope': candidate.scope, 'surface': candidate.surface,
                      'active': candidate.is_active,
                      'expires_at': candidate.expires_at.isoformat() if candidate.expires_at else None})
        messages.success(request, f'Rule "{candidate.name}" saved.')
        return redirect('api_access:index')
    return render(request, 'api_access/rule_form.html', {
        'form': form, 'rule': rule, 'creating': creating, 'preview': preview,
        'history': _history(rule)})


def _history(rule):
    if not rule.pk:
        return []
    return AuditLog.objects.filter(object_type='ApiAccessRule', object_id=rule.pk).order_by('-timestamp')[:20]


@_guarded
def rule_create(request):
    return _rule_form_page(request, ApiAccessRule())


@_guarded
def rule_edit(request, pk):
    return _rule_form_page(request, get_object_or_404(ApiAccessRule, pk=pk))


@_guarded
@require_POST
def rule_toggle(request, pk):
    rule = get_object_or_404(ApiAccessRule, pk=pk)
    rule.is_active = not rule.is_active
    if rule.is_active:
        proposed = build_policy_for_rule(rule, exclude_id=rule.pk)
        preview = impact(proposed, client_ip_text(request))
        if preview['high_impact'] and request.POST.get('confirm') != '1':
            messages.warning(request, f'Enabling "{rule.name}" would refuse current API traffic. '
                                      'Open the rule to review the impact and confirm.')
            return redirect('api_access:rule_edit', pk=rule.pk)
    rule.updated_by = request.user
    rule.save(update_fields=['is_active', 'updated_by', 'updated_at'])
    _changed(request)
    _audit(request, 'update', rule, description=f'API access rule {"enabled" if rule.is_active else "disabled"}: {rule}')
    messages.success(request, f'Rule "{rule.name}" {"enabled" if rule.is_active else "disabled"}.')
    return redirect('api_access:index')


@_guarded
@require_POST
def rule_delete(request, pk):
    rule = get_object_or_404(ApiAccessRule, pk=pk)
    desc = str(rule)
    _audit(request, 'delete', rule, description=f'API access rule deleted: {desc}',
           extra={'network': rule.network, 'action': rule.action, 'scope': rule.scope})
    rule.delete()
    _changed(request)
    messages.success(request, 'Rule deleted.')
    return redirect('api_access:index')


@_guarded
def test_address(request):
    form = TestAddressForm(request.GET or None)
    result = None
    if request.GET and form.is_valid():
        key = form.cleaned_data['api_key']
        group = form.cleaned_data['group']
        label, surface = ENDPOINT_GROUPS[group]
        integration = next((i for p, g, i in _routes() if g == group and i), '')
        ctx = P.Context(ip=form.cleaned_data['ip'], surface=surface, group=group,
                        integration=integration,
                        organization_id=getattr(key, 'organization_id', None),
                        api_key_id=getattr(key, 'pk', None))
        policy = P.build_policy(settings_row(), rule_rows())
        decision = P.evaluate(policy, ctx)
        now = timezone.now()
        mode = policy.mode_for(surface)
        applicable = [{'rule': r, 'contains': r.contains(ctx.ip),
                       'expired': bool(r.expires_at and r.expires_at <= now),
                       'ignored': r.scope == ApiAccessRule.SCOPE_GLOBAL and (
                           (r.action == ApiAccessRule.ACTION_ALLOW and mode not in (
                               ApiAccessSettings.MODE_ALLOWLIST, ApiAccessSettings.MODE_COMBINED))
                           or (r.action == ApiAccessRule.ACTION_DENY and mode not in (
                               ApiAccessSettings.MODE_DENYLIST, ApiAccessSettings.MODE_COMBINED)))}
                      for r in policy.rules if r.applies_to(ctx)]
        result = {'decision': decision, 'reason': P.REASONS.get(decision.reason, ''),
                  'applicable': applicable, 'surface': surface, 'group_label': label,
                  'mode': policy.mode_for(surface), 'ip': str(ctx.ip)}
    return render(request, 'api_access/test.html', {'form': form, 'result': result,
                                                    'your_ip': client_ip_text(request)})


def _routes():
    from .groups import _ROUTES
    return _ROUTES


@_guarded
def decisions(request):
    qs = ApiAccessDecision.objects.select_related('rule', 'api_key', 'organization')
    ip = (request.GET.get('ip') or '').strip()
    reason = request.GET.get('reason', '')
    if ip:
        parsed = P.parse_ip(ip)
        qs = qs.filter(source_ip=str(parsed)) if parsed else qs.none()
    if reason in P.REASONS:
        qs = qs.filter(reason=reason)
    page = Paginator(qs, 50).get_page(request.GET.get('page'))
    for d in page:
        d.group_label = ENDPOINT_GROUPS.get(d.endpoint_group, (d.endpoint_group,))[0]
        d.integration_label = INTEGRATIONS.get(d.integration, d.integration)
        d.reason_label = P.REASONS.get(d.reason, d.reason)
    since = timezone.now() - timedelta(days=7)
    repeat = (ApiAccessDecision.objects.filter(created_at__gte=since).values('source_ip')
              .annotate(total=Sum('count'), rows=Count('id')).order_by('-total')[:10])
    by_key = (ApiAccessDecision.objects.filter(created_at__gte=since).exclude(api_key_prefix='')
              .values('api_key_prefix').annotate(total=Sum('count')).order_by('-total')[:10])
    by_group = [dict(row, label=ENDPOINT_GROUPS.get(row['endpoint_group'], (row['endpoint_group'],))[0])
                for row in ApiAccessDecision.objects.filter(created_at__gte=since).values('endpoint_group')
                .annotate(total=Sum('count')).order_by('-total')]
    return render(request, 'api_access/decisions.html', {
        'page': page, 'ip': ip, 'reason': reason, 'reasons': P.REASONS, 'repeat': repeat,
        'by_key': by_key, 'by_group': by_group, 'groups': ENDPOINT_GROUPS})


@_guarded
def diagnostics(request):
    return render(request, 'api_access/diagnostics.html', {'info': explain_client_address(request)})


EXPORT_FIELDS = ('name', 'network', 'action', 'surface', 'scope', 'target', 'description',
                 'is_active', 'expires_at')


@_guarded
def export_rules(request):
    rows = []
    for r in ApiAccessRule.objects.select_related('organization', 'api_key').order_by('pk'):
        row = {f: getattr(r, f) for f in EXPORT_FIELDS}
        row['expires_at'] = r.expires_at.isoformat() if r.expires_at else None
        row['customer'] = r.organization.name if r.organization_id else None
        row['api_key_prefix'] = r.api_key.key_prefix if r.api_key_id else None
        rows.append(row)
    body = json.dumps({'format': 'clientst0r-api-access-rules', 'version': 1, 'rules': rows}, indent=2)
    _audit(request, 'export', description=f'API access rules exported ({len(rows)})')
    resp = HttpResponse(body, content_type='application/json')
    resp['Content-Disposition'] = 'attachment; filename="api-access-rules.json"'
    return resp


MAX_IMPORT_BYTES = 512 * 1024
MAX_IMPORT_RULES = 1000


def _parse_import(upload):
    """Validate an export file. Returns (rules, errors); nothing is saved."""
    from django.utils.dateparse import parse_datetime
    from api.models import APIKey
    from core.models import Organization
    if upload.size > MAX_IMPORT_BYTES:
        return [], ['The file is larger than 512 KB.']
    try:
        data = json.loads(upload.read().decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return [], ['The file is not valid JSON.']
    if not isinstance(data, dict) or data.get('format') != 'clientst0r-api-access-rules':
        return [], ['This is not an API access rules export.']
    items = data.get('rules')
    if not isinstance(items, list):
        return [], ['The file has no rules list.']
    if len(items) > MAX_IMPORT_RULES:
        return [], [f'At most {MAX_IMPORT_RULES} rules per import.']
    rules, errors = [], []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append(f'Rule {n}: not an object.')
            continue
        rule = ApiAccessRule(
            name=str(item.get('name') or '')[:120] or f'Imported rule {n}',
            network=str(item.get('network') or ''), action=item.get('action'),
            surface=item.get('surface'), scope=item.get('scope'),
            target=str(item.get('target') or '')[:40],
            description=str(item.get('description') or '')[:255],
            is_active=bool(item.get('is_active', True)))
        if item.get('expires_at'):
            rule.expires_at = parse_datetime(str(item['expires_at']))
            if rule.expires_at is None:
                errors.append(f'Rule {n}: unreadable expiry date.')
                continue
        if rule.action not in dict(ApiAccessRule.ACTIONS) or \
                rule.surface not in dict(ApiAccessRule.RULE_SURFACES) or \
                rule.scope not in dict(ApiAccessRule.SCOPES):
            errors.append(f'Rule {n}: unknown action, surface or scope.')
            continue
        if rule.scope == ApiAccessRule.SCOPE_CUSTOMER:
            rule.organization = Organization.objects.filter(name=item.get('customer')).first()
        if rule.scope == ApiAccessRule.SCOPE_API_KEY:
            rule.api_key = APIKey.objects.filter(key_prefix=item.get('api_key_prefix') or '-').first()
        try:
            rule.clean()
        except Exception as exc:  # ValidationError: report which rule and why
            msgs = getattr(exc, 'messages', None) or ['invalid']
            errors.append(f'Rule {n} ({rule.name}): {"; ".join(msgs)}')
            continue
        rules.append(rule)
    return rules, errors


@_guarded
def import_rules(request):
    """Step 1: upload and validate (nothing saved) and show the preview.
    Step 2: apply the validated rules kept in the session."""
    if request.method == 'POST' and request.POST.get('apply_saved') == '1':
        return _apply_saved_import(request)
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        rules, errors = _parse_import(form.cleaned_data['file'])
        if errors:
            return render(request, 'api_access/import.html', {'form': ImportForm(), 'errors': errors})
        request.session['api_access_import'] = [_serialize(r) for r in rules]
        return render(request, 'api_access/import.html', {
            'form': ImportForm(), 'parsed': {'rules': rules, 'preview': _import_impact(request, rules)}})
    return render(request, 'api_access/import.html', {'form': form})


def _serialize(rule):
    row = {f: getattr(rule, f) for f in EXPORT_FIELDS}
    row['expires_at'] = rule.expires_at.isoformat() if rule.expires_at else None
    row['organization_id'] = rule.organization_id
    row['api_key_id'] = rule.api_key_id
    return row


def _deserialize(item):
    from django.utils.dateparse import parse_datetime
    rule = ApiAccessRule(**{f: item[f] for f in EXPORT_FIELDS if f != 'expires_at'},
                         organization_id=item['organization_id'], api_key_id=item['api_key_id'],
                         expires_at=parse_datetime(item['expires_at']) if item['expires_at'] else None)
    rule.clean()  # re-validate: the session copy is ours, but rules may have changed since
    return rule


def _import_impact(request, rules):
    rows = rule_rows() + [r for r in (row_for(x) for x in rules) if r]
    return impact(P.build_policy(settings_row(), rows), client_ip_text(request))


def _apply_saved_import(request):
    saved = request.session.get('api_access_import')
    if not saved:
        messages.error(request, 'Nothing to import — upload the file again.')
        return redirect('api_access:import')
    try:
        rules = [_deserialize(item) for item in saved]
    except Exception:
        request.session.pop('api_access_import', None)
        messages.error(request, 'The uploaded rules no longer validate — upload the file again.')
        return redirect('api_access:import')
    preview = _import_impact(request, rules)
    if preview['high_impact'] and request.POST.get('confirm') != '1':
        messages.warning(request, 'This import would refuse current traffic. Tick the confirmation to apply it.')
        return render(request, 'api_access/import.html', {
            'form': ImportForm(), 'parsed': {'rules': rules, 'preview': preview}})
    with transaction.atomic():
        for rule in rules:
            rule.created_by = rule.updated_by = request.user
            rule.save()
    request.session.pop('api_access_import', None)
    _changed(request)
    _audit(request, 'import', description=f'API access rules imported ({len(rules)})',
           extra={'rule_ids': [r.pk for r in rules]})
    messages.success(request, f'Imported {len(rules)} rules.')
    return redirect('api_access:index')
