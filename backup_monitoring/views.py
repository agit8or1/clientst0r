import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.permission_utils import require_perm_any_org, user_has_org_perm, user_has_perm_any_org
from core.safe_redirect import safe_post_next

from . import ingest as ingest_mod
from .access import MANAGE, VIEW, allowed_orgs, can_act_on, has_global_reach, visible
from .alerts import evaluate_connection
from .forms import (BackupAlertPolicyForm, BackupConnectionForm, ManualSystemForm, ProtectedSystemForm,
                    RestoreTestForm)
from .health import BADGE, LABEL, age_text, connection_freshness, job_rows
from .models import (ALERT_ACK, ALERT_RESOLVED, BackupAlert, BackupAlertPolicy, BackupConnection, BackupJob,
                     ProtectedSystem, RestoreTest)
from .recording import poll_connection
from .summary import customer_summary, customers_with_data

logger = logging.getLogger('backup_monitoring')


def _can_manage_any(user):
    return user_has_perm_any_org(user, MANAGE)


def _ctx(request, **extra):
    extra.setdefault('can_manage', _can_manage_any(request.user))
    return extra


# --------------------------------------------------------------------------
# Dashboard / customer / job
# --------------------------------------------------------------------------

@login_required
@require_perm_any_org(VIEW)
def dashboard(request):
    orgs = allowed_orgs(request.user)
    wanted = request.GET.get('customer') or ''
    current = getattr(request, 'current_organization', None)
    if wanted.isdigit():
        orgs = orgs.filter(pk=int(wanted))
    elif wanted == 'all':
        pass
    elif current is not None:
        orgs = orgs.filter(pk=current.pk)
    summaries = [customer_summary(o) for o in customers_with_data(orgs)]
    if has_global_reach(request.user) and not wanted.isdigit() and (wanted == 'all' or current is None):
        unmapped = customer_summary(None)
        if unmapped['jobs_total'] or unmapped['repos'] or unmapped['open_alerts']:
            summaries.append(unmapped)
    summaries.sort(key=lambda s: -{'failed': 5, 'missed': 4, 'stale': 3, 'warning': 2, 'unknown': 1,
                                   'ok': 0}[s['state']])
    return render(request, 'backup_monitoring/dashboard.html', _ctx(
        request, summaries=summaries, filtered=bool(wanted.isdigit() or current)))


@login_required
@require_perm_any_org(VIEW)
def customer_detail(request, org_id):
    if org_id == 0:
        if not has_global_reach(request.user):
            raise Http404()
        org = None
    else:
        org = get_object_or_404(allowed_orgs(request.user), pk=org_id)
    s = customer_summary(org)
    alerts = BackupAlert.objects.filter(organization=org, status__in=['open', 'acknowledged']) \
        .select_related('connection', 'job')[:50]
    return render(request, 'backup_monitoring/customer_detail.html', _ctx(
        request, s=s, org=org, alerts=alerts, badge=BADGE[s['state']], label=LABEL[s['state']],
        can_manage_here=can_act_on(request.user, org.pk if org else None)))


@login_required
@require_perm_any_org(VIEW)
def job_detail(request, pk):
    job = get_object_or_404(
        BackupJob.objects.select_related('connection', 'organization', 'system').filter(visible(request.user)),
        pk=pk)
    row = job_rows([job])[0]
    runs = job.runs.order_by('-started_at')[:100]
    return render(request, 'backup_monitoring/job_detail.html', _ctx(
        request, job=job, row=row, runs=runs, alerts=job.alerts.filter(status__in=['open', 'acknowledged'])))


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------

@login_required
@require_perm_any_org(VIEW)
def alert_list(request):
    qs = BackupAlert.objects.filter(visible(request.user)).select_related(
        'organization', 'connection', 'job', 'ticket')
    show = request.GET.get('show', 'live')
    if show == 'live':
        qs = qs.filter(status__in=['open', 'acknowledged'])
    manage_ids = set(allowed_orgs(request.user, MANAGE).values_list('pk', flat=True))
    global_manage = has_global_reach(request.user, MANAGE)
    alerts = list(qs.order_by('-last_seen_at')[:300])
    for a in alerts:
        a.can_act = global_manage if a.organization_id is None else a.organization_id in manage_ids
    return render(request, 'backup_monitoring/alert_list.html', _ctx(request, alerts=alerts, show=show))


@login_required
@require_perm_any_org(MANAGE)
@require_POST
def alert_decide(request, pk):
    alert = get_object_or_404(BackupAlert.objects.filter(visible(request.user, MANAGE)), pk=pk)
    decision = request.POST.get('decision')
    now = timezone.now()
    if decision == 'acknowledge' and alert.status == 'open':
        alert.status, alert.acknowledged_by, alert.acknowledged_at = ALERT_ACK, request.user, now
        alert.save(update_fields=['status', 'acknowledged_by', 'acknowledged_at'])
    elif decision == 'resolve' and alert.status != ALERT_RESOLVED:
        alert.status, alert.resolved_at = ALERT_RESOLVED, now
        alert.save(update_fields=['status', 'resolved_at'])
        messages.info(request, 'Resolved. It reopens on the next check if the condition is still present.')
    elif decision == 'ticket':
        from .tickets import create_ticket_for_alert
        if alert.organization_id is None:
            messages.error(request, 'Map this to a customer first: a ticket needs a customer.')
            return redirect(safe_post_next(request, 'backup_monitoring:alert_list'))
        from .tickets import TicketSetupError
        try:
            ticket, created = create_ticket_for_alert(alert, request.user)
        except TicketSetupError as exc:
            messages.error(request, str(exc))
            return redirect(safe_post_next(request, 'backup_monitoring:alert_list'))
        messages.success(request, f"{'Created' if created else 'Already linked to'} ticket {ticket.ticket_number}.")
    return redirect(safe_post_next(request, 'backup_monitoring:alert_list'))


# --------------------------------------------------------------------------
# Restore tests (separate from backup success)
# --------------------------------------------------------------------------

@login_required
@require_perm_any_org(VIEW)
def restore_test_list(request):
    tests = RestoreTest.objects.filter(organization__in=allowed_orgs(request.user)) \
        .select_related('organization', 'system', 'verified_by')[:300]
    return render(request, 'backup_monitoring/restore_test_list.html', _ctx(request, tests=tests))


@login_required
@require_perm_any_org(MANAGE)
def restore_test_form(request):
    orgs = allowed_orgs(request.user, MANAGE)
    systems = ProtectedSystem.objects.filter(customer__in=orgs).select_related('customer')
    if request.method == 'POST':
        form = RestoreTestForm(request.POST, orgs=orgs, systems=systems)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.verified_by = request.user
            if not obj.verified_by_name:
                obj.verified_by_name = request.user.get_full_name() or request.user.get_username()
            obj.save()
            messages.success(request, 'Restore test recorded.')
            return redirect('backup_monitoring:restore_test_list')
    else:
        initial = {}
        current = getattr(request, 'current_organization', None)
        if current is not None and orgs.filter(pk=current.pk).exists():
            initial['organization'] = current
        form = RestoreTestForm(orgs=orgs, systems=systems, initial=initial)
    return render(request, 'backup_monitoring/restore_test_form.html', _ctx(request, form=form))


# --------------------------------------------------------------------------
# Connections
# --------------------------------------------------------------------------

@login_required
@require_perm_any_org(MANAGE)
def connection_list(request):
    conns = BackupConnection.objects.filter(visible(request.user, MANAGE)) \
        .select_related('organization', 'customer')
    rows = []
    for c in conns:
        f, contact = connection_freshness(c)
        rows.append({'c': c, 'freshness': f, 'age': age_text(contact)})
    return render(request, 'backup_monitoring/connection_list.html', _ctx(request, rows=rows))


@login_required
@require_perm_any_org(MANAGE)
def connection_form(request, pk=None):
    orgs = allowed_orgs(request.user, MANAGE)
    instance = get_object_or_404(BackupConnection.objects.filter(visible(request.user, MANAGE)), pk=pk) if pk else None
    if instance and request.method == 'POST' and request.POST.get('regenerate_secret') and instance.is_push:
        instance.issue_ingest_secret()
        instance.save(update_fields=['ingest_secret', 'updated_at'])
        messages.warning(request, 'New signing secret issued. The previous one no longer works.')
        return render(request, 'backup_monitoring/connection_form.html', _ctx(
            request, form=BackupConnectionForm(instance=instance, orgs=orgs, msp_wide=has_global_reach(request.user, MANAGE)), instance=instance,
            issued_secret=instance.issued_ingest_secret,
            ingest_url=request.build_absolute_uri(_ingest_path(instance))))
    if request.method == 'POST':
        form = BackupConnectionForm(request.POST, instance=instance, orgs=orgs, msp_wide=has_global_reach(request.user, MANAGE))
        if form.is_valid():
            obj = form.save(commit=False)
            if not instance:
                obj.created_by = request.user
            obj.save()
            secret = getattr(obj, 'issued_ingest_secret', None)
            if secret:
                messages.success(request, 'Connection saved. Copy the signing secret now; it is not shown again.')
                return render(request, 'backup_monitoring/connection_form.html', _ctx(
                    request, form=BackupConnectionForm(instance=obj, orgs=orgs, msp_wide=has_global_reach(request.user, MANAGE)), instance=obj,
                    issued_secret=secret, ingest_url=request.build_absolute_uri(_ingest_path(obj))))
            messages.success(request, 'Connection saved.')
            return redirect('backup_monitoring:connection_list')
    else:
        initial = {}
        current = getattr(request, 'current_organization', None)
        if not instance and current is not None and orgs.filter(pk=current.pk).exists():
            initial['organization'] = current
        form = BackupConnectionForm(instance=instance, orgs=orgs, initial=initial,
                                  msp_wide=has_global_reach(request.user, MANAGE))
    return render(request, 'backup_monitoring/connection_form.html', _ctx(
        request, form=form, instance=instance,
        ingest_url=request.build_absolute_uri(_ingest_path(instance)) if instance and instance.is_push else ''))


def _ingest_path(conn):
    from django.urls import reverse
    return reverse('backup_monitoring:ingest', args=[conn.ingest_id])


@login_required
@require_perm_any_org(MANAGE)
@require_POST
def connection_test(request, pk):
    from .providers import get_backup_provider
    conn = get_object_or_404(BackupConnection.objects.filter(visible(request.user, MANAGE)), pk=pk)
    try:
        result = get_backup_provider(conn).test_connection()
    except Exception as exc:
        result = {'ok': False, 'message': f'{exc.__class__.__name__}'}
    (messages.success if result['ok'] else messages.error)(request, f"{conn.name}: {result['message']}")
    return redirect('backup_monitoring:connection_list')


@login_required
@require_perm_any_org(MANAGE)
@require_POST
def connection_poll(request, pk):
    conn = get_object_or_404(BackupConnection.objects.filter(visible(request.user, MANAGE)), pk=pk)
    result = poll_connection(conn)
    stats = evaluate_connection(conn)
    if result['ok']:
        messages.success(request, f"{conn.name}: polled, {result['runs']} new run(s), "
                                  f"{stats['opened']} alert(s) opened.")
    else:
        messages.error(request, f"{conn.name}: {result['message']}")
    return redirect('backup_monitoring:connection_list')


@login_required
@require_perm_any_org(MANAGE)
@require_POST
def connection_delete(request, pk):
    conn = get_object_or_404(BackupConnection.objects.filter(visible(request.user, MANAGE)), pk=pk)
    name = conn.name
    conn.delete()
    messages.success(request, f'Deleted connection {name} and the history it collected.')
    return redirect('backup_monitoring:connection_list')


# --------------------------------------------------------------------------
# Systems and policy
# --------------------------------------------------------------------------

@login_required
@require_perm_any_org(MANAGE)
def system_create(request):
    import uuid
    orgs = allowed_orgs(request.user, MANAGE)
    conns = BackupConnection.objects.filter(visible(request.user, MANAGE))
    form = ManualSystemForm(request.POST or None, orgs=orgs, connections=conns)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.external_id = f'manual:{uuid.uuid4().hex[:12]}'
        obj.save()
        messages.success(request, 'Protected system added.')
        return redirect('backup_monitoring:customer_detail', org_id=obj.customer_id)
    return render(request, 'backup_monitoring/system_form.html', _ctx(request, form=form, instance=None))


@login_required
@require_perm_any_org(MANAGE)
def system_edit(request, pk):
    orgs = allowed_orgs(request.user, MANAGE)
    system = get_object_or_404(ProtectedSystem.objects.filter(visible(request.user, MANAGE, 'customer')), pk=pk)
    form = ProtectedSystemForm(request.POST or None, instance=system, orgs=orgs)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        # Jobs follow their system's customer; so do repositories-less alerts.
        # Mapping a system moves its jobs and their alerts to that customer.
        obj.jobs.update(organization=obj.customer)
        obj.alerts.update(organization=obj.customer)
        messages.success(request, 'Saved.')
        return redirect('backup_monitoring:customer_detail', org_id=obj.customer_id)
    return render(request, 'backup_monitoring/system_form.html', _ctx(request, form=form, instance=system))


@login_required
@require_perm_any_org(MANAGE)
def policy_edit(request, org_id):
    org = get_object_or_404(allowed_orgs(request.user, MANAGE), pk=org_id)
    instance = BackupAlertPolicy.objects.filter(organization=org).first()
    base = instance or BackupAlertPolicy.for_org(org)
    form = BackupAlertPolicyForm(request.POST or None, instance=instance,
                                 initial={f: getattr(base, f) for f in BackupAlertPolicy.DEFAULTS})
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.organization = org
        obj.save()
        messages.success(request, f'Alert policy saved for {org.name}.')
        return redirect('backup_monitoring:customer_detail', org_id=org.pk)
    return render(request, 'backup_monitoring/policy_form.html', _ctx(request, form=form, org=org))


# --------------------------------------------------------------------------
# Signed ingest (no login: HMAC over the body)
# --------------------------------------------------------------------------

@csrf_exempt
@require_POST
def ingest(request, ingest_id):
    deny = JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        declared = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        declared = 0
    if declared > ingest_mod.MAX_BODY_BYTES:
        return JsonResponse({'error': 'body too large'}, status=413)
    body = request.body
    if len(body) > ingest_mod.MAX_BODY_BYTES:
        return JsonResponse({'error': 'body too large'}, status=413)
    conn = BackupConnection.objects.filter(ingest_id=ingest_id, active=True).first()
    if conn is None or not conn.is_push:
        return deny
    try:
        ingest_mod.verify_request(conn, request.META.get('HTTP_X_BACKUP_TIMESTAMP', ''),
                                  request.META.get('HTTP_X_BACKUP_SIGNATURE', ''), body)
        try:
            payload = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise ingest_mod.IngestRejected(400, 'body is not valid JSON')
        result = ingest_mod.process_report(conn, payload)
    except ingest_mod.IngestRejected as exc:
        return JsonResponse({'error': exc.message}, status=exc.status)
    try:
        evaluate_connection(conn)
    except Exception:
        logger.exception('alert evaluation after ingest failed')
    return JsonResponse({'status': 'duplicate' if result['run'] == 'duplicate' else 'ok', **result})
