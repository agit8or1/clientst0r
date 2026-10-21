"""
Phase 9 — Triage UI + webhook receiver for security alerts.
"""
import hashlib
import hmac
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse, JsonResponse, HttpResponseBadRequest, HttpResponseForbidden,
    Http404,
)
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.permission_utils import require_perm, user_has_perm
from .forms import (
    SecurityVendorConnectionForm,
    SecurityAlertRuleForm,
    SIEMWebhookEndpointForm,
)
from .models import (
    RemediationPlaybook,
    RemediationPlaybookStep,
    SecurityAlert,
    SecurityAlertRule,
    SecurityIncident,
    SecurityIncidentEvent,
    SecurityVendorConnection,
    SIEMWebhookEndpoint,
)


def _user_orgs(user):
    """Orgs whose security data the user may see.

    Uses the same rule as the rest of the app: superusers and MSP staff whose
    global role grants `security_alerts_view` (or who have no global role)
    see every organization; anyone else only the organizations, and their
    subsidiaries, where a membership grants it. Before v3.17.619 this read
    raw memberships, so a technician with a global role and no membership
    saw no alerts at all.
    """
    from accounts.permission_utils import orgs_with_perm
    from core.models import Organization
    allowed = orgs_with_perm(user, 'security_alerts_view')
    if allowed is None:
        return Organization.objects.all()
    return Organization.objects.filter(pk__in=allowed)


def _primary_org(user):
    membership = user.memberships.filter(is_active=True).select_related('organization').first()
    return membership.organization if membership else None


# ---------------------------------------------------------------------------
# Alert list / detail / triage actions
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_view')
def alert_list(request):
    orgs = _user_orgs(request.user)
    qs = SecurityAlert.objects.filter(organization__in=orgs).select_related(
        'connection', 'client_org', 'organization', 'auto_ticket',
    )

    severity = request.GET.get('severity')
    status = request.GET.get('status')
    vendor = request.GET.get('vendor')
    client = request.GET.get('client')
    start = request.GET.get('start')
    end = request.GET.get('end')

    if severity:
        qs = qs.filter(severity=severity)
    if status:
        qs = qs.filter(status=status)
    if vendor:
        qs = qs.filter(connection__provider=vendor)
    if client:
        qs = qs.filter(client_org_id=client)
    if start:
        qs = qs.filter(seen_at__date__gte=start)
    if end:
        qs = qs.filter(seen_at__date__lte=end)

    alerts = qs.order_by('-seen_at')[:500]

    context = {
        'alerts': alerts,
        'severity_choices': SecurityAlert.SEVERITY_CHOICES,
        'status_choices': SecurityAlert.STATUS_CHOICES,
        'provider_choices': SecurityVendorConnection.PROVIDER_CHOICES,
        'clients': orgs,
        'filters': {
            'severity': severity or '', 'status': status or '',
            'vendor': vendor or '', 'client': client or '',
            'start': start or '', 'end': end or '',
        },
        'can_acknowledge': user_has_perm(request.user, 'security_alerts_acknowledge'),
        'can_manage_rules': user_has_perm(request.user, 'security_alerts_create_rules'),
        'can_manage_connections': user_has_perm(request.user, 'security_alerts_manage_connections'),
    }
    return render(request, 'security_alerts/alert_list.html', context)


@login_required
@require_perm('security_alerts_view')
def alert_detail(request, pk):
    orgs = _user_orgs(request.user)
    alert = get_object_or_404(
        SecurityAlert.objects.select_related(
            'connection', 'client_org', 'organization',
            'acknowledged_by', 'auto_ticket',
        ),
        pk=pk, organization__in=orgs,
    )
    pretty_payload = json.dumps(alert.raw_payload or {}, indent=2, sort_keys=True)
    return render(request, 'security_alerts/alert_detail.html', {
        'alert': alert,
        'pretty_payload': pretty_payload,
        'can_acknowledge': user_has_perm(request.user, 'security_alerts_acknowledge'),
    })


@login_required
@require_perm('security_alerts_acknowledge')
@require_POST
def alert_decide(request, pk):
    """Acknowledge / dismiss / resolve / convert to ticket."""
    orgs = _user_orgs(request.user)
    alert = get_object_or_404(
        SecurityAlert.objects.select_related('connection'),
        pk=pk, organization__in=orgs,
    )
    decision = (request.POST.get('decision') or '').lower()
    now = timezone.now()
    if decision == 'acknowledge':
        alert.status = 'acknowledged'
        alert.acknowledged_at = now
        alert.acknowledged_by = request.user
        alert.save(update_fields=['status', 'acknowledged_at', 'acknowledged_by'])
        messages.success(request, 'Alert acknowledged.')
    elif decision == 'dismiss':
        alert.status = 'dismissed'
        alert.save(update_fields=['status'])
        messages.info(request, 'Alert dismissed.')
    elif decision == 'resolve':
        alert.status = 'resolved'
        alert.resolved_at = now
        alert.save(update_fields=['status', 'resolved_at'])
        messages.success(request, 'Alert resolved.')
    elif decision == 'convert':
        from .adapters.base import _maybe_auto_ticket
        # Force-create a ticket regardless of rules: synthesize a one-off rule path.
        from psa.models import Ticket, Queue, TicketPriority, TicketStatus, TicketType
        try:
            queue = Queue.objects.filter(is_active=True).first()
            priority_code = {
                'critical': 'P1', 'high': 'P2', 'medium': 'P3',
                'low': 'P4', 'info': 'P5',
            }.get(alert.severity, 'P3')
            priority = (TicketPriority.objects.filter(code=priority_code).first()
                        or TicketPriority.objects.first())
            status = TicketStatus.objects.filter(slug='new').first() or TicketStatus.objects.first()
            ttype = TicketType.objects.first()
            ticket = Ticket.objects.create(
                organization=alert.client_org or alert.organization,
                subject=f'[Security] {alert.title[:200]}',
                description=alert.description or '',
                queue=queue, priority=priority, status=status, ticket_type=ttype,
                source='monitoring',
                created_by=request.user,
            )
            alert.auto_ticket = ticket
            alert.status = 'acknowledged'
            alert.acknowledged_at = now
            alert.acknowledged_by = request.user
            alert.save(update_fields=['auto_ticket', 'status', 'acknowledged_at', 'acknowledged_by'])
            messages.success(request, f'Created ticket {ticket.ticket_number}.')
        except Exception as exc:
            messages.error(request, f'Failed to create ticket: {exc}')
    else:
        messages.error(request, f'Unknown decision: {decision}')
    return redirect(request.POST.get('next') or 'security_alerts:alert_list')


@login_required
@require_perm('security_alerts_acknowledge')
@require_POST
def alert_bulk_decide(request):
    orgs = _user_orgs(request.user)
    decision = (request.POST.get('decision') or '').lower()
    ids = request.POST.getlist('alert_ids')
    qs = SecurityAlert.objects.filter(pk__in=ids, organization__in=orgs)
    now = timezone.now()
    n = 0
    if decision == 'acknowledge':
        n = qs.filter(status='new').update(
            status='acknowledged', acknowledged_at=now, acknowledged_by=request.user,
        )
    elif decision == 'dismiss':
        n = qs.update(status='dismissed')
    elif decision == 'resolve':
        n = qs.update(status='resolved', resolved_at=now)
    else:
        messages.error(request, f'Unknown bulk decision: {decision}')
        return redirect('security_alerts:alert_list')
    messages.success(request, f'{decision.title()}d {n} alert{"s" if n != 1 else ""}.')
    return redirect('security_alerts:alert_list')


# ---------------------------------------------------------------------------
# Connections CRUD
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_view')
def connection_list(request):
    orgs = _user_orgs(request.user)
    conns = SecurityVendorConnection.objects.filter(organization__in=orgs).select_related(
        'organization', 'client_org',
    )
    return render(request, 'security_alerts/connection_list.html', {
        'connections': conns,
        'can_manage': user_has_perm(request.user, 'security_alerts_manage_connections'),
    })


@login_required
@require_perm('security_alerts_manage_connections')
def connection_form(request, pk=None):
    orgs = _user_orgs(request.user)
    instance = None
    if pk is not None:
        instance = get_object_or_404(
            SecurityVendorConnection, pk=pk, organization__in=orgs,
        )
    if request.method == 'POST' and instance and request.POST.get('regenerate_webhook'):
        # Token is stored hashed and the secret encrypted, so the only way
        # to hand them out again is to mint new ones.
        instance.issue_webhook_credentials()
        instance.save(update_fields=['webhook_token_hash', 'webhook_secret', 'updated_at'])
        messages.warning(request, 'New webhook URL and secret issued. The previous ones no longer work.')
        return render(request, 'security_alerts/connection_form.html', {
            'form': SecurityVendorConnectionForm(instance=instance), 'instance': instance,
            'issued_webhook_token': instance.issued_webhook_token,
            'issued_webhook_secret': instance.issued_webhook_secret,
        })
    if request.method == 'POST':
        form = SecurityVendorConnectionForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            if not instance:
                obj.organization = _primary_org(request.user) or orgs.first()
                obj.created_by = request.user
            obj.save()
            issued = getattr(obj, 'issued_webhook_token', None)
            if issued:
                # Shown in this response only — never stored in the session.
                messages.success(request, 'Connection saved. Copy the webhook URL and secret now; they are not shown again.')
                return render(request, 'security_alerts/connection_form.html', {
                    'form': SecurityVendorConnectionForm(instance=obj), 'instance': obj,
                    'issued_webhook_token': issued,
                    'issued_webhook_secret': obj.issued_webhook_secret,
                })
            messages.success(request, 'Connection saved.')
            return redirect('security_alerts:connection_list')
    else:
        form = SecurityVendorConnectionForm(instance=instance)
    return render(request, 'security_alerts/connection_form.html', {
        'form': form, 'instance': instance,
    })


@login_required
@require_perm('security_alerts_manage_connections')
@require_POST
def connection_test(request, pk):
    orgs = _user_orgs(request.user)
    conn = get_object_or_404(SecurityVendorConnection, pk=pk, organization__in=orgs)
    from integrations.sdk.registry import get as get_provider
    adapter = get_provider(f'security_{conn.provider}') or get_provider(conn.provider)
    if not adapter:
        return JsonResponse({'ok': False, 'message': f'No adapter for {conn.provider}'})
    try:
        result = adapter.test_connection(conn)
    except Exception as exc:
        result = {'ok': False, 'message': str(exc)[:200]}
    return JsonResponse(result)


@login_required
@require_perm('security_alerts_manage_connections')
@require_POST
def connection_sync(request, pk):
    orgs = _user_orgs(request.user)
    conn = get_object_or_404(SecurityVendorConnection, pk=pk, organization__in=orgs)
    from integrations.sdk.registry import get as get_provider
    adapter = get_provider(f'security_{conn.provider}') or get_provider(conn.provider)
    if not adapter:
        messages.error(request, f'No adapter for {conn.provider}')
        return redirect('security_alerts:connection_list')
    result = adapter.sync(conn)
    if result.get('ok'):
        messages.success(request, f'Sync ok — imported {result.get("records_imported", 0)} alert(s).')
    else:
        messages.error(request, f'Sync failed: {result.get("errors")}')
    return redirect('security_alerts:connection_list')


# ---------------------------------------------------------------------------
# Rules CRUD
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_view')
def rule_list(request):
    orgs = _user_orgs(request.user)
    rules = SecurityAlertRule.objects.filter(organization__in=orgs)
    return render(request, 'security_alerts/rule_list.html', {
        'rules': rules,
        'can_manage': user_has_perm(request.user, 'security_alerts_create_rules'),
    })


@login_required
@require_perm('security_alerts_create_rules')
def rule_form(request, pk=None):
    orgs = _user_orgs(request.user)
    instance = None
    if pk is not None:
        instance = get_object_or_404(SecurityAlertRule, pk=pk, organization__in=orgs)
    if request.method == 'POST':
        form = SecurityAlertRuleForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            if not instance:
                obj.organization = _primary_org(request.user) or orgs.first()
            obj.save()
            messages.success(request, 'Rule saved.')
            return redirect('security_alerts:rule_list')
    else:
        form = SecurityAlertRuleForm(instance=instance)
    return render(request, 'security_alerts/rule_form.html', {
        'form': form, 'instance': instance,
    })


# ---------------------------------------------------------------------------
# Inbound webhook
# ---------------------------------------------------------------------------

@csrf_exempt
def webhook_receive(request, token):
    """
    Vendor-agnostic inbound webhook. URL contains a per-connection
    token. Optional HMAC signature header for cryptographic auth.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest('POST only')

    conn = SecurityVendorConnection.lookup_by_webhook_token(token, is_active=True)
    if not conn:
        raise Http404('Unknown webhook token')

    body = request.body or b''
    sig_header = request.META.get('HTTP_X_CST0R_SIGNATURE') or ''
    if sig_header:
        expected = hmac.new(
            conn.webhook_secret.encode('utf-8'),
            body, hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            return HttpResponseForbidden('Bad signature')

    # Resolve adapter
    from integrations.sdk.registry import get as get_provider
    adapter = get_provider(f'security_{conn.provider}') or get_provider(conn.provider)

    alerts = []
    if adapter and hasattr(adapter, 'webhook_handler'):
        try:
            alerts = adapter.webhook_handler(conn, request) or []
        except NotImplementedError:
            alerts = []
        except Exception:
            # Adapter doesn't implement (or raised the SDK NotSupported
            # sentinel) — fall through to generic JSON parsing below.
            alerts = []
    if not alerts:
        # Fallback: parse JSON body as a single alert dict
        try:
            data = json.loads(body.decode('utf-8') or '{}')
            if isinstance(data, dict):
                alerts = [data]
            elif isinstance(data, list):
                alerts = data
        except Exception:
            alerts = []

    # Persist alerts via the same code path as sync()
    from .adapters.base import _maybe_auto_ticket
    imported = 0
    for a in alerts:
        ext = a.get('external_id') or a.get('id') or ''
        if not ext:
            continue
        obj, created = SecurityAlert.objects.update_or_create(
            connection=conn, external_id=ext,
            defaults={
                'organization': conn.organization,
                'client_org': conn.client_org,
                'severity': (a.get('severity') or 'medium'),
                'title': (a.get('title') or '')[:300],
                'description': a.get('description') or '',
                'asset_hint': (a.get('asset_hint') or '')[:200],
                'raw_payload': a if isinstance(a, dict) else {},
            },
        )
        if created:
            imported += 1
            _maybe_auto_ticket(obj)
            try:
                from .models import _correlate_alert_to_incident
                _correlate_alert_to_incident(obj)
            except Exception:
                pass

    conn.last_sync_at = timezone.now()
    conn.last_sync_status = 'ok'
    conn.last_error = ''
    conn.save(update_fields=['last_sync_at', 'last_sync_status', 'last_error'])
    return JsonResponse({'ok': True, 'imported': imported})


# ---------------------------------------------------------------------------
# Phase 23 v3.17.337 — SIEM webhook endpoints (CRUD + receiver)
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_view')
def siem_endpoint_list(request):
    orgs = _user_orgs(request.user)
    endpoints = SIEMWebhookEndpoint.objects.filter(
        organization__in=orgs,
    ).select_related('organization', 'client_org')
    return render(request, 'security_alerts/siem_endpoint_list.html', {
        'endpoints': endpoints,
        'can_manage': user_has_perm(request.user, 'security_alerts_manage_connections'),
    })


@login_required
@require_perm('security_alerts_manage_connections')
def siem_endpoint_form(request, pk=None):
    orgs = _user_orgs(request.user)
    instance = None
    if pk is not None:
        instance = get_object_or_404(
            SIEMWebhookEndpoint, pk=pk, organization__in=orgs,
        )
    if request.method == 'POST' and instance and request.POST.get('regenerate_webhook'):
        instance.issue_webhook_credentials()
        instance.save(update_fields=['token_hash', 'hmac_secret', 'updated_at'])
        from audit.models import AuditLog
        AuditLog.log(
            user=request.user,
            action='siem_endpoint_saved',
            organization=instance.organization,
            object_type='security_alerts.SIEMWebhookEndpoint',
            object_id=instance.pk,
            object_repr=instance.name,
            description=f'Issued new webhook URL token and HMAC secret for {instance.name}',
        )
        messages.warning(request, 'New webhook URL and HMAC secret issued. The previous ones no longer work.')
        return render(request, 'security_alerts/siem_endpoint_form.html', {
            'form': SIEMWebhookEndpointForm(instance=instance), 'instance': instance,
            'issued_token': instance.issued_token,
            'issued_hmac_secret': instance.issued_hmac_secret,
        })
    if request.method == 'POST':
        form = SIEMWebhookEndpointForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            if not instance:
                obj.organization = _primary_org(request.user) or orgs.first()
                obj.created_by = request.user
            obj.save()
            from audit.models import AuditLog
            AuditLog.log(
                user=request.user,
                action='siem_endpoint_saved',
                organization=obj.organization,
                object_type='security_alerts.SIEMWebhookEndpoint',
                object_id=obj.pk,
                object_repr=obj.name,
                description=f'Saved SIEM webhook endpoint {obj.name}',
            )
            issued = getattr(obj, 'issued_token', None)
            if issued:
                messages.success(request, 'SIEM webhook endpoint saved. Copy the URL and HMAC secret now; they are not shown again.')
                return render(request, 'security_alerts/siem_endpoint_form.html', {
                    'form': SIEMWebhookEndpointForm(instance=obj), 'instance': obj,
                    'issued_token': issued,
                    'issued_hmac_secret': obj.issued_hmac_secret,
                })
            messages.success(request, 'SIEM webhook endpoint saved.')
            return redirect('security_alerts:siem_endpoint_list')
    else:
        form = SIEMWebhookEndpointForm(instance=instance)
    return render(request, 'security_alerts/siem_endpoint_form.html', {
        'form': form, 'instance': instance,
    })


@csrf_exempt
def siem_webhook_receive(request, token):
    """Phase 23 v3.17.337 — generic CEF/JSON inbound webhook.

    Authenticates with the per-endpoint URL token; optional HMAC-SHA256
    signature in `X-Cst0r-Signature`. Returns 404 for unknown tokens,
    403 for invalid signatures (or missing when `require_hmac=True`).
    """
    from .siem import (
        ingest_payload, parse_inbound, verify_signature,
    )
    if request.method != 'POST':
        return HttpResponseBadRequest('POST only')

    endpoint = SIEMWebhookEndpoint.lookup_by_token(token, is_active=True)
    if not endpoint:
        raise Http404('Unknown SIEM webhook token')

    body = request.body or b''
    sig_header = request.META.get('HTTP_X_CST0R_SIGNATURE') or ''
    if endpoint.require_hmac:
        if not sig_header or not verify_signature(endpoint.hmac_secret, body, sig_header):
            return HttpResponseForbidden('Invalid or missing signature')
    elif sig_header:
        # Signature present — verify it. Don't accept bogus signatures.
        if not verify_signature(endpoint.hmac_secret, body, sig_header):
            return HttpResponseForbidden('Bad signature')

    try:
        alerts = parse_inbound(body, endpoint.expected_format)
    except Exception as exc:
        endpoint.last_error = str(exc)[:500]
        endpoint.save(update_fields=['last_error'])
        return JsonResponse({'ok': False, 'error': 'parse_failed'}, status=400)

    if not alerts:
        endpoint.last_error = 'no_events_parsed'
        endpoint.save(update_fields=['last_error'])
        return JsonResponse(
            {'ok': True, 'imported': 0, 'note': 'no events parsed'},
        )

    imported = ingest_payload(endpoint, alerts)
    endpoint.last_seen_at = timezone.now()
    endpoint.last_error = ''
    endpoint.received_count = (endpoint.received_count or 0) + len(alerts)
    endpoint.save(update_fields=['last_seen_at', 'last_error', 'received_count'])
    return JsonResponse({
        'ok': True,
        'received': len(alerts),
        'imported': imported,
    })


# ---------------------------------------------------------------------------
# Phase 23 v3.17.338 — Security incidents + timelines
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_view')
def incident_list(request):
    orgs = _user_orgs(request.user)
    qs = SecurityIncident.objects.filter(
        organization__in=orgs,
    ).select_related('client_org', 'organization', 'assigned_to')

    severity = request.GET.get('severity')
    status = request.GET.get('status')
    if severity:
        qs = qs.filter(severity=severity)
    if status:
        qs = qs.filter(status=status)

    incidents = qs.order_by('-opened_at')[:300]
    return render(request, 'security_alerts/incident_list.html', {
        'incidents': incidents,
        'severity_choices': SecurityIncident.SEVERITY_CHOICES,
        'status_choices': SecurityIncident.STATUS_CHOICES,
        'filters': {'severity': severity or '', 'status': status or ''},
    })


@login_required
@require_perm('security_alerts_view')
def incident_detail(request, pk):
    orgs = _user_orgs(request.user)
    incident = get_object_or_404(
        SecurityIncident.objects.select_related(
            'organization', 'client_org', 'assigned_to', 'created_by',
        ),
        pk=pk, organization__in=orgs,
    )
    events = incident.events.select_related('actor', 'alert').order_by('occurred_at', 'pk')
    alerts = incident.alerts.select_related('connection', 'siem_endpoint').order_by('-seen_at')
    return render(request, 'security_alerts/incident_detail.html', {
        'incident': incident,
        'events': events,
        'alerts': alerts,
        'can_acknowledge': user_has_perm(request.user, 'security_alerts_acknowledge'),
    })


@login_required
@require_perm('security_alerts_acknowledge')
@require_POST
def incident_decide(request, pk):
    """Status transitions + add note. POST decision=acknowledge|investigate|contain|resolve|close|note."""
    orgs = _user_orgs(request.user)
    incident = get_object_or_404(
        SecurityIncident, pk=pk, organization__in=orgs,
    )
    decision = (request.POST.get('decision') or '').lower()
    note = (request.POST.get('note') or '').strip()
    now = timezone.now()
    transitions = {
        'acknowledge': ('investigating', 'acknowledged_at', 'acknowledged'),
        'investigate': ('investigating', None, 'status_change'),
        'contain': ('contained', 'contained_at', 'contained'),
        'resolve': ('resolved', 'resolved_at', 'resolved'),
        'close': ('closed', 'closed_at', 'closed'),
    }
    if decision == 'note':
        if note:
            incident.add_event(kind='note', message=note, user=request.user)
            messages.success(request, 'Note added.')
        else:
            messages.error(request, 'Note may not be empty.')
    elif decision in transitions:
        new_status, ts_field, evt_kind = transitions[decision]
        incident.status = new_status
        update_fields = ['status']
        if ts_field:
            setattr(incident, ts_field, now)
            update_fields.append(ts_field)
        incident.save(update_fields=update_fields)
        incident.add_event(
            kind=evt_kind,
            message=note or f'Status → {new_status}',
            user=request.user,
        )
        messages.success(request, f'Incident moved to {new_status}.')
    else:
        messages.error(request, f'Unknown decision: {decision}')
    return redirect('security_alerts:incident_detail', pk=incident.pk)


# ---------------------------------------------------------------------------
# Phase 23 v3.17.356 — Remediation playbooks
# ---------------------------------------------------------------------------

@login_required
@require_perm('security_alerts_acknowledge')
@require_POST
def incident_ai_summarize(request, pk):
    """Phase 23 v3.17.362 — **OPTIONAL AI** incident summarization.

    Gated by `SystemSetting.psa_ai_enabled`. When disabled, returns a
    flash-error and redirects to the incident detail page. When
    enabled, calls the pluggable summarizer and stores the summary as a
    timeline note.
    """
    from .ai_summarizer import summarize_incident

    orgs = _user_orgs(request.user)
    incident = get_object_or_404(
        SecurityIncident, pk=pk, organization__in=orgs,
    )
    result = summarize_incident(incident, requested_by=request.user)
    if not result['enabled']:
        messages.error(request, result['reason'])
    elif not result['ok']:
        messages.error(request, f'AI summarization failed: {result["reason"]}')
    else:
        messages.success(request, 'AI summary added to incident timeline.')
    return redirect('security_alerts:incident_detail', pk=incident.pk)


@login_required
@require_perm('security_alerts_view')
def threat_overview(request):
    """Phase 23 v3.17.359 — Threat visibility dashboard.

    Single-pane view for an MSP analyst: open alerts by severity, open
    incidents by severity, top exposed orgs (cached score), in-flight
    playbook activity in the last 24h, and a 7-day-vs-prior-7-day
    week-over-week alert-volume trend.
    """
    from datetime import timedelta
    from django.db.models import Count
    from .models import RemediationPlaybook
    from core.models import Organization

    orgs = _user_orgs(request.user)

    # Open alert counts per severity.
    open_alert_counts = {
        sev: SecurityAlert.objects.filter(
            organization__in=orgs, status__in=['new', 'acknowledged'],
            severity=sev,
        ).count()
        for sev, _ in SecurityAlert.SEVERITY_CHOICES
    }

    # Open incident counts per severity + total.
    open_incidents_qs = SecurityIncident.objects.filter(
        organization__in=orgs,
        status__in=['open', 'investigating', 'contained'],
    )
    open_incident_counts = {
        sev: open_incidents_qs.filter(severity=sev).count()
        for sev, _ in SecurityAlert.SEVERITY_CHOICES
    }
    total_open_incidents = open_incidents_qs.count()

    # Top exposed orgs (cached score).
    top_exposed = Organization.objects.filter(
        pk__in=orgs.values_list('pk', flat=True),
        is_active=True,
    ).order_by('-exposure_score')[:10]

    # In-flight playbook activity (timeline events of kind playbook_action
    # in the last 24h).
    cutoff = timezone.now() - timedelta(hours=24)
    recent_playbook_events = SecurityIncidentEvent.objects.filter(
        kind='playbook_action',
        occurred_at__gte=cutoff,
        incident__organization__in=orgs,
    ).select_related('incident').order_by('-occurred_at')[:20]

    # Configured playbooks count.
    playbook_count = RemediationPlaybook.objects.filter(
        organization__in=orgs, is_active=True,
    ).count()

    # Week-over-week trend.
    now = timezone.now()
    week_a_start = now - timedelta(days=7)
    week_b_start = now - timedelta(days=14)
    week_a_count = SecurityAlert.objects.filter(
        organization__in=orgs, seen_at__gte=week_a_start,
    ).count()
    week_b_count = SecurityAlert.objects.filter(
        organization__in=orgs, seen_at__gte=week_b_start, seen_at__lt=week_a_start,
    ).count()
    if week_b_count > 0:
        wow_pct = round(((week_a_count - week_b_count) / week_b_count) * 100, 1)
    elif week_a_count > 0:
        wow_pct = 100.0
    else:
        wow_pct = 0.0

    return render(request, 'security_alerts/threat_overview.html', {
        'open_alert_counts': open_alert_counts,
        'open_incident_counts': open_incident_counts,
        'total_open_incidents': total_open_incidents,
        'top_exposed': top_exposed,
        'recent_playbook_events': recent_playbook_events,
        'playbook_count': playbook_count,
        'week_a_count': week_a_count,
        'week_b_count': week_b_count,
        'wow_pct': wow_pct,
    })


@login_required
@require_perm('security_alerts_view')
def playbook_list(request):
    orgs = _user_orgs(request.user)
    playbooks = RemediationPlaybook.objects.filter(
        organization__in=orgs,
    ).select_related('match_client_org').prefetch_related('steps')
    return render(request, 'security_alerts/playbook_list.html', {
        'playbooks': playbooks,
        'can_manage': user_has_perm(request.user, 'security_alerts_create_rules'),
    })
