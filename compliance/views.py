"""
Compliance evidence packs (Phase 39).

One-click bundle of compliance-relevant data for a single organization.
v3.17.222 ships five sections — 2FA status, user access, password access
history, asset inventory, ticket/SLA history. The remaining four (vuln
scan, SSL/domain expiration, backup, uptime) follow in subsequent
releases.
"""
import csv as _csv
import io
import json
import statistics
import zipfile
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts.models import Membership
from assets.models import Asset
from audit.models import AuditLog
from core.models import Organization
from psa.models import Ticket


def _user_can_access_pack(user, org):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'is_staff_user', None):
        try:
            if profile.is_staff_user():
                return True
        except Exception:
            pass
    return Membership.objects.filter(
        user=user, organization=org, is_active=True,
        role__in=['owner', 'admin'],
    ).exists()


def _section_two_factor(org):
    rows = []
    qs = (Membership.objects
          .filter(organization=org, is_active=True)
          .select_related('user', 'user__profile'))
    for m in qs:
        u = m.user
        profile = getattr(u, 'profile', None)
        rows.append({
            'username': u.username,
            'email': u.email or '',
            'two_factor_enabled': bool(getattr(profile, 'two_factor_enabled', False)),
            'two_factor_method': getattr(profile, 'two_factor_method', '') or '',
            'last_login': u.last_login.isoformat() if u.last_login else '',
        })
    enabled = sum(1 for r in rows if r['two_factor_enabled'])
    return {
        'rows': rows,
        'summary': {
            'total_users': len(rows),
            'two_factor_enabled': enabled,
            'two_factor_coverage_pct': round(100 * enabled / len(rows), 1) if rows else 0,
        },
    }


def _section_user_access(org):
    rows = []
    qs = (Membership.objects
          .filter(organization=org)
          .select_related('user', 'role_template'))
    for m in qs:
        u = m.user
        rows.append({
            'username': u.username,
            'email': u.email or '',
            'role': m.role,
            'role_template': m.role_template.name if m.role_template_id else '',
            'is_active': m.is_active,
            'invited_at': m.invited_at.isoformat() if getattr(m, 'invited_at', None) else '',
            'last_login': u.last_login.isoformat() if u.last_login else '',
        })
    active = sum(1 for r in rows if r['is_active'])
    return {
        'rows': rows,
        'summary': {
            'total_memberships': len(rows),
            'active_memberships': active,
        },
    }


def _section_password_access_history(org, days=90):
    cutoff = timezone.now() - timedelta(days=days)
    qs = (AuditLog.objects
          .filter(organization=org, timestamp__gte=cutoff,
                  object_type__iexact='password')
          .order_by('-timestamp'))
    rows = []
    for log in qs[:1000]:
        rows.append({
            'timestamp': log.timestamp.isoformat(),
            'username': log.username,
            'action': log.action,
            'object_repr': log.object_repr,
            'ip_address': log.ip_address or '',
            'success': log.success,
        })
    counts_by_action = {}
    for r in rows:
        counts_by_action[r['action']] = counts_by_action.get(r['action'], 0) + 1
    return {
        'rows': rows,
        'summary': {
            'window_days': days,
            'total_events': len(rows),
            'by_action': counts_by_action,
        },
    }


def _section_asset_inventory(org):
    rows = []
    qs = Asset.objects.filter(organization=org).order_by('asset_type', 'name')
    for a in qs:
        rows.append({
            'name': a.name,
            'asset_type': a.get_asset_type_display() if hasattr(a, 'get_asset_type_display') else a.asset_type,
            'serial_number': a.serial_number or '',
            'vendor': getattr(a, 'vendor', '') or '',
            'location': getattr(a, 'location', '') or '',
            'purchase_date': a.purchase_date.isoformat() if getattr(a, 'purchase_date', None) else '',
            'warranty_expiry': a.warranty_expiry.isoformat() if getattr(a, 'warranty_expiry', None) else '',
        })
    return {
        'rows': rows,
        'summary': {
            'total_assets': len(rows),
            'with_serial': sum(1 for r in rows if r['serial_number']),
            'with_warranty_date': sum(1 for r in rows if r['warranty_expiry']),
        },
    }


def _section_ticket_sla_history(org, months=12):
    cutoff = timezone.now() - timedelta(days=30 * months)
    qs = (Ticket.objects
          .filter(organization=org, created_at__gte=cutoff)
          .select_related('status', 'priority'))
    total = qs.count()
    by_status = {}
    response_breaches = 0
    resolution_breaches = 0
    response_intervals = []
    resolution_intervals = []
    for t in qs:
        status_name = t.status.name if t.status_id else 'unknown'
        by_status[status_name] = by_status.get(status_name, 0) + 1
        if t.sla_breached_response:
            response_breaches += 1
        if t.sla_breached_resolution:
            resolution_breaches += 1
        if t.first_response_at and t.created_at:
            response_intervals.append((t.first_response_at - t.created_at).total_seconds())
        if t.closed_at and t.created_at:
            resolution_intervals.append((t.closed_at - t.created_at).total_seconds())

    def median_or_none(values):
        return round(statistics.median(values), 1) if values else None

    return {
        'rows': [{'status': k, 'count': v} for k, v in sorted(by_status.items())],
        'summary': {
            'window_months': months,
            'total_tickets': total,
            'sla_response_met_pct': round(100 * (total - response_breaches) / total, 1) if total else 0,
            'sla_resolution_met_pct': round(100 * (total - resolution_breaches) / total, 1) if total else 0,
            'median_first_response_seconds': median_or_none(response_intervals),
            'median_resolution_seconds': median_or_none(resolution_intervals),
        },
    }


def _section_ssl_domain_expiration(org):
    rows = []
    try:
        from monitoring.models import WebsiteMonitor
        qs = WebsiteMonitor.objects.filter(organization=org, is_enabled=True)
        for m in qs.order_by('name'):
            rows.append({
                'monitor_name': m.name,
                'url': m.url,
                'ssl_enabled': m.ssl_enabled,
                'ssl_expires_at': m.ssl_expires_at.isoformat() if m.ssl_expires_at else '',
                'ssl_issuer': m.ssl_issuer or '',
                'domain_expires_at': m.domain_expires_at.isoformat() if m.domain_expires_at else '',
            })
    except Exception:
        pass
    summary = {
        'total_monitors': len(rows),
        'with_ssl': sum(1 for r in rows if r['ssl_enabled']),
        'ssl_with_expiry_tracked': sum(1 for r in rows if r['ssl_expires_at']),
        'domain_with_expiry_tracked': sum(1 for r in rows if r['domain_expires_at']),
    }
    return {'rows': rows, 'summary': summary}


def _section_uptime(org):
    rows = []
    counts = {'active': 0, 'warning': 0, 'down': 0, 'unknown': 0, 'error': 0}
    try:
        from monitoring.models import WebsiteMonitor
        qs = WebsiteMonitor.objects.filter(organization=org, is_enabled=True)
        for m in qs.order_by('name'):
            counts[m.status] = counts.get(m.status, 0) + 1
            rows.append({
                'monitor_name': m.name,
                'url': m.url,
                'status': m.status,
                'last_checked_at': m.last_checked_at.isoformat() if m.last_checked_at else '',
                'last_status_code': m.last_status_code or '',
                'last_response_time_ms': m.last_response_time_ms or '',
            })
    except Exception:
        pass
    total = len(rows)
    healthy = counts.get('active', 0)
    summary = {
        'total_monitors': total,
        'active': healthy,
        'warning': counts.get('warning', 0),
        'down': counts.get('down', 0) + counts.get('error', 0),
        'unknown': counts.get('unknown', 0),
        'healthy_pct': round(100 * healthy / total, 1) if total else 0,
    }
    return {'rows': rows, 'summary': summary}


def _section_vulnerability_summary(org, days=90):
    rows = []
    counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
    open_count = 0
    try:
        from security_alerts.models import SecurityAlert
        cutoff = timezone.now() - timedelta(days=days)
        qs = SecurityAlert.objects.filter(client_org=org, seen_at__gte=cutoff)
        open_qs = qs.filter(status='new')
        for a in open_qs.order_by('-seen_at')[:200]:
            rows.append({
                'seen_at': a.seen_at.isoformat(),
                'severity': a.severity,
                'title': (a.title or '')[:200],
                'status': a.status,
            })
        for sev in counts:
            counts[sev] = open_qs.filter(severity=sev).count()
        open_count = open_qs.count()
    except Exception:
        pass
    summary = {
        'window_days': days,
        'open_count': open_count,
        'by_severity': counts,
    }
    return {'rows': rows, 'summary': summary}


def _section_backup_evidence(org):
    # v3.17.226 Phase 39 v2: backup status placeholder. No first-party
    # backup-job tracking model ships with the project today, so this
    # section currently only records "no backup integration configured"
    # as evidence — auditors get a documented absence rather than a
    # blank page. When a backup model is added (future), enrich here.
    return {
        'rows': [],
        'summary': {
            'note': 'No backup-job integration is configured for this organization.',
            'backup_jobs_tracked': 0,
        },
    }


def _build_pack(org):
    return {
        'organization': org,
        'generated_at': timezone.now(),
        'two_factor': _section_two_factor(org),
        'user_access': _section_user_access(org),
        'password_history': _section_password_access_history(org),
        'asset_inventory': _section_asset_inventory(org),
        'ticket_sla': _section_ticket_sla_history(org),
        'ssl_domain': _section_ssl_domain_expiration(org),
        'uptime': _section_uptime(org),
        'vulnerabilities': _section_vulnerability_summary(org),
        'backups': _section_backup_evidence(org),
    }


def _client_ip(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request)


@login_required
def evidence_pack(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_access_pack(request.user, org):
        raise Http404('Evidence pack not available')

    pack = _build_pack(org)

    AuditLog.log(
        user=request.user, action='create',
        organization=org,
        object_type='compliance.EvidencePack', object_id=org.pk,
        object_repr=f'Evidence pack for {org.name}',
        description='Generated compliance evidence pack',
        ip_address=_client_ip(request), path=request.path,
    )

    if request.GET.get('format') == 'zip':
        return _zip_response(pack)
    return render(request, 'compliance/evidence_pack.html', pack)


def _zip_response(pack):
    buf = io.BytesIO()
    org = pack['organization']
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        section_keys = (
            'two_factor', 'user_access', 'password_history',
            'asset_inventory', 'ticket_sla',
            'ssl_domain', 'uptime', 'vulnerabilities', 'backups',
        )
        manifest = {
            'organization': org.name,
            'organization_id': org.pk,
            'generated_at': pack['generated_at'].isoformat(),
            'sections': list(section_keys),
            'summaries': {k: pack[k]['summary'] for k in section_keys},
        }
        zf.writestr('manifest.json', json.dumps(manifest, indent=2, default=str))
        for key in section_keys:
            section = pack[key]
            csv_buf = io.StringIO()
            rows = section['rows']
            if rows:
                writer = _csv.DictWriter(csv_buf, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            zf.writestr(f'{key}.csv', csv_buf.getvalue())

    response = HttpResponse(buf.getvalue(), content_type='application/zip')
    safe_org = ''.join(c if c.isalnum() else '_' for c in org.name)[:60]
    stamp = pack['generated_at'].strftime('%Y%m%d-%H%M%S')
    response['Content-Disposition'] = (
        f'attachment; filename="evidence-pack-{safe_org}-{stamp}.zip"'
    )
    return response


# ---------------------------------------------------------------------------
# Phase 41 — Compliance Frameworks & Recertification (v3.17.439+)
# Per-org dashboard + enrollment.
# ---------------------------------------------------------------------------

from django.contrib import messages as _messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST


def _user_can_manage_compliance(user, org):
    """Same gate as evidence pack — owner/admin of the org or staff."""
    return _user_can_access_pack(user, org)


@login_required
def org_compliance_dashboard(request, org_id):
    """List every framework + the org's enrollment status."""
    from .models import (
        ComplianceFramework, OrganizationCompliance,
    )

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    frameworks = []
    for fw in ComplianceFramework.objects.filter(active=True).order_by('name'):
        try:
            oc = OrganizationCompliance.objects.get(
                organization=org, framework=fw,
            )
            counts = oc.status_counts()
            pct = oc.percent_compliant()
            days_left = oc.days_until_recertification
        except OrganizationCompliance.DoesNotExist:
            oc = None
            counts = None
            pct = None
            days_left = None

        frameworks.append({
            'framework': fw,
            'enrollment': oc,
            'counts': counts,
            'percent_compliant': pct,
            'days_until_recertification': days_left,
        })

    return render(request, 'compliance/org_dashboard.html', {
        'organization': org,
        'frameworks': frameworks,
    })


@login_required
@require_POST
def enroll_framework(request, org_id, framework_slug):
    """Enroll the org in a framework. Creates OrganizationCompliance +
    one OrganizationComplianceItem per check item (status=unanswered)."""
    from .models import (
        ComplianceCheckItem, ComplianceFramework, OrganizationCompliance,
        OrganizationComplianceItem,
    )

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug, active=True)

    oc, created = OrganizationCompliance.objects.get_or_create(
        organization=org, framework=fw,
        defaults={
            'enrolled_by': request.user,
            'recertification_interval_days': fw.recertification_default_days,
        },
    )
    if created:
        items = ComplianceCheckItem.objects.filter(category__framework=fw)
        OrganizationComplianceItem.objects.bulk_create([
            OrganizationComplianceItem(org_compliance=oc, item=item)
            for item in items
        ])
        AuditLog.log(
            user=request.user, action='create',
            organization=org,
            object_type='compliance.OrganizationCompliance',
            object_id=oc.pk,
            object_repr=f'{org.name} :: {fw.name}',
            description=f'Enrolled in {fw.name} {fw.version}',
            ip_address=_client_ip(request), path=request.path,
        )
        _messages.success(
            request,
            f'Enrolled {org.name} in {fw.name}. '
            f'Open the checklist below to start the attestation.'
        )
    else:
        _messages.info(
            request,
            f'{org.name} is already enrolled in {fw.name}.'
        )

    return redirect('compliance:org_dashboard', org_id=org.pk)


# ---------------------------------------------------------------------------
# Phase 41 v3.17.440 — checklist view + per-row attestation save
# ---------------------------------------------------------------------------

@login_required
def checklist_view(request, org_id, framework_slug):
    """Show the full checklist for a framework, grouped by category."""
    from .models import (
        ComplianceFramework, OrganizationCompliance,
        OrganizationComplianceItem,
    )

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug)
    oc = get_object_or_404(
        OrganizationCompliance, organization=org, framework=fw,
    )

    categories = []
    for cat in fw.categories.order_by('order', 'slug'):
        item_rows = []
        for item in cat.items.order_by('order', 'slug'):
            attest = OrganizationComplianceItem.objects.filter(
                org_compliance=oc, item=item,
            ).first()
            item_rows.append({
                'item': item,
                'attestation': attest,
                'status': attest.status if attest else 'unanswered',
                'notes': attest.notes if attest else '',
                'evidence_link': attest.evidence_link if attest else '',
            })
        categories.append({
            'category': cat,
            'items': item_rows,
        })

    return render(request, 'compliance/checklist.html', {
        'organization': org,
        'framework': fw,
        'enrollment': oc,
        'categories': categories,
        'percent_compliant': oc.percent_compliant(),
        'counts': oc.status_counts(),
        'STATUS_CHOICES': OrganizationComplianceItem.STATUS_CHOICES,
    })


@login_required
@require_POST
def checklist_save(request, org_id, framework_slug):
    """Save one item's attestation. POST fields: item_id, status, notes, evidence_link."""
    from .models import (
        ComplianceFramework, OrganizationCompliance,
        OrganizationComplianceItem,
    )

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug)
    oc = get_object_or_404(OrganizationCompliance, organization=org, framework=fw)

    try:
        item_id = int(request.POST.get('item_id', '0'))
    except (TypeError, ValueError):
        item_id = 0
    attest = get_object_or_404(
        OrganizationComplianceItem,
        org_compliance=oc, item_id=item_id,
    )

    new_status = request.POST.get('status', '').strip() or 'unanswered'
    valid_statuses = {s for s, _ in OrganizationComplianceItem.STATUS_CHOICES}
    if new_status not in valid_statuses:
        new_status = 'unanswered'

    old_status = attest.status
    attest.status = new_status
    attest.notes = request.POST.get('notes', '').strip()
    attest.evidence_link = request.POST.get('evidence_link', '').strip()
    attest.last_reviewed_at = timezone.now()
    attest.last_reviewed_by = request.user
    attest.save()

    if old_status != new_status:
        AuditLog.log(
            user=request.user, action='update',
            organization=org,
            object_type='compliance.OrganizationComplianceItem',
            object_id=attest.pk,
            object_repr=f'{attest.item.slug}',
            description=f'Status: {old_status} -> {new_status}',
            ip_address=_client_ip(request), path=request.path,
        )

    return redirect(
        reverse(
            'compliance:checklist',
            kwargs={'org_id': org.pk, 'framework_slug': fw.slug},
        ) + f'#item-{attest.item_id}'
    )


# ---------------------------------------------------------------------------
# Phase 41 v3.17.441 — customer-facing PDF report
# ---------------------------------------------------------------------------

@login_required
def compliance_report_pdf(request, org_id, framework_slug):
    """Render the compliance attestation as a PDF for a customer auditor."""
    from .models import (
        ComplianceFramework, OrganizationCompliance,
        OrganizationComplianceItem,
    )
    from reports.pdf_export import render_pdf

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug)
    oc = get_object_or_404(
        OrganizationCompliance, organization=org, framework=fw,
    )

    counts = oc.status_counts()
    pct = oc.percent_compliant()

    # KPI summary across the top
    kpis = [
        {'label': 'Compliance', 'value': f'{pct}%'},
        {'label': 'Compliant', 'value': str(counts.get('compliant', 0))},
        {'label': 'Partial',   'value': str(counts.get('partial', 0))},
        {'label': 'Non-compliant', 'value': str(counts.get('non_compliant', 0))},
        {'label': 'N/A',        'value': str(counts.get('not_applicable', 0))},
        {'label': 'Unanswered', 'value': str(counts.get('unanswered', 0))},
        {'label': 'Total controls', 'value': str(counts.get('total', 0))},
        {'label': 'Recertify in',
         'value': f"{oc.days_until_recertification} days"},
    ]

    # One table per category. Rows: control name / status / evidence / notes.
    tables = []
    status_label = dict(OrganizationComplianceItem.STATUS_CHOICES)
    for cat in fw.categories.order_by('order', 'slug'):
        body_rows = []
        for item in cat.items.order_by('order', 'slug'):
            attest = OrganizationComplianceItem.objects.filter(
                org_compliance=oc, item=item,
            ).first()
            status_str = status_label.get(
                attest.status if attest else 'unanswered',
                'Unanswered',
            )
            evidence = (attest.evidence_link if attest else '') or '—'
            notes = (attest.notes if attest else '') or ''
            # Trim long notes to keep the PDF readable.
            if len(notes) > 280:
                notes = notes[:277] + '…'
            body_rows.append([
                item.name,
                status_str,
                evidence,
                notes,
            ])
        tables.append({
            'heading': cat.name,
            'header_row': ['Control', 'Status', 'Evidence', 'Notes'],
            'body_rows': body_rows,
        })

    AuditLog.log(
        user=request.user, action='view',
        organization=org,
        object_type='compliance.OrganizationCompliance',
        object_id=oc.pk,
        object_repr=f'{org.name} :: {fw.name}',
        description=f'Generated PDF compliance report for {fw.name}',
        ip_address=_client_ip(request), path=request.path,
    )

    safe_org = ''.join(c if c.isalnum() else '_' for c in org.name)[:60]
    stamp = timezone.now().strftime('%Y%m%d')
    return render_pdf(
        title=f'{fw.name} Compliance Report',
        subtitle=(
            f'{org.name} — {fw.name} {fw.version}. '
            f'Generated {timezone.now():%Y-%m-%d %H:%M UTC}. '
            f'Last recertified: {oc.last_recertified_at:%Y-%m-%d}'
            if oc.last_recertified_at else
            f'{org.name} — {fw.name} {fw.version}. '
            f'Generated {timezone.now():%Y-%m-%d %H:%M UTC}. '
            f'Never recertified.'
        ),
        kpis=kpis,
        tables=tables,
        filename=f'{safe_org}-{framework_slug}-{stamp}.pdf',
    )


# ---------------------------------------------------------------------------
# Phase 41 v3.17.443 — recertification settings + mark-recertified
# ---------------------------------------------------------------------------

VALID_INTERVAL_DAYS = {30, 60, 90, 180, 365}


@login_required
@require_POST
def recert_settings(request, org_id, framework_slug):
    """Update recertification toggle + interval for an enrollment."""
    from .models import ComplianceFramework, OrganizationCompliance

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug)
    oc = get_object_or_404(OrganizationCompliance, organization=org, framework=fw)

    # Toggle: present if user ticked, absent if unticked.
    new_enabled = request.POST.get('emails_enabled') == 'on'

    # Interval: validate against the canonical set; default to current value
    # if the POST contains garbage.
    try:
        new_interval = int(request.POST.get('interval_days', oc.recertification_interval_days))
    except (TypeError, ValueError):
        new_interval = oc.recertification_interval_days
    if new_interval not in VALID_INTERVAL_DAYS:
        new_interval = oc.recertification_interval_days

    new_email = (request.POST.get('notify_email') or '').strip()

    changed = []
    if oc.recertification_emails_enabled != new_enabled:
        changed.append(f'emails_enabled: {oc.recertification_emails_enabled} -> {new_enabled}')
        oc.recertification_emails_enabled = new_enabled
    if oc.recertification_interval_days != new_interval:
        changed.append(f'interval_days: {oc.recertification_interval_days} -> {new_interval}')
        oc.recertification_interval_days = new_interval
    if oc.notify_email != new_email:
        changed.append(f'notify_email: {oc.notify_email!r} -> {new_email!r}')
        oc.notify_email = new_email

    oc.save()

    if changed:
        AuditLog.log(
            user=request.user, action='update',
            organization=org,
            object_type='compliance.OrganizationCompliance',
            object_id=oc.pk,
            object_repr=f'{org.name} :: {fw.name}',
            description='Recert settings: ' + '; '.join(changed),
            ip_address=_client_ip(request), path=request.path,
        )
        _messages.success(request, 'Recertification settings updated.')
    else:
        _messages.info(request, 'No changes.')

    return redirect('compliance:checklist', org_id=org.pk, framework_slug=fw.slug)


@login_required
@require_POST
def mark_recertified(request, org_id, framework_slug):
    """Stamp last_recertified_at = now(). User affirms they've reviewed the
    full checklist and the attestation is current."""
    from .models import ComplianceFramework, OrganizationCompliance

    org = get_object_or_404(Organization, pk=org_id)
    if not _user_can_manage_compliance(request.user, org):
        raise Http404('Not allowed')

    fw = get_object_or_404(ComplianceFramework, slug=framework_slug)
    oc = get_object_or_404(OrganizationCompliance, organization=org, framework=fw)

    oc.last_recertified_at = timezone.now()
    oc.save(update_fields=['last_recertified_at'])

    AuditLog.log(
        user=request.user, action='update',
        organization=org,
        object_type='compliance.OrganizationCompliance',
        object_id=oc.pk,
        object_repr=f'{org.name} :: {fw.name}',
        description=(
            f'Marked recertified. Next reminder due in '
            f'{oc.recertification_interval_days} days.'
        ),
        ip_address=_client_ip(request), path=request.path,
    )
    _messages.success(
        request,
        f'Marked {fw.name} recertified for {org.name}. '
        f'Next reminder due in {oc.recertification_interval_days} days.'
    )

    return redirect('compliance:checklist', org_id=org.pk, framework_slug=fw.slug)
