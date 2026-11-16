"""Read-side aggregation for the dashboard, customer page and device workspace."""
from django.db.models import Q
from django.utils import timezone

from core.models import Organization

from .health import BADGE, LABEL, connection_freshness, job_rows, restore_test_summary, worst
from .models import BackupAlert, BackupAlertPolicy, BackupJob, BackupRepository, RestoreTest


def customer_summary(org, now=None):
    now = now or timezone.now()
    jobs = list(BackupJob.objects.filter(organization=org).select_related('connection', 'organization', 'system'))
    rows = job_rows(jobs, now)
    counts = {}
    for r in rows:
        counts[r['state']] = counts.get(r['state'], 0) + 1
    state = worst(r['state'] for r in rows) if rows else 'unknown'
    policy = BackupAlertPolicy.for_org(org)
    repos = list(BackupRepository.objects.filter(organization=org).select_related('connection'))
    for repo in repos:
        _f, _c = connection_freshness(repo.connection, now)
        repo.freshness = _f
        pct = repo.used_pct
        repo.bar_class = ('bg-danger' if (pct or 0) >= max(policy.capacity_pct, 95) or not repo.available
                          else 'bg-warning' if (pct or 0) >= policy.capacity_pct else 'bg-success')
    tests = list(RestoreTest.objects.filter(organization=org).select_related('system')[:50])
    successes = [r['job'].last_success_at for r in rows if r['job'].last_success_at]
    return {
        'org': org, 'org_pk': org.pk if org else 0, 'name': org.name if org else 'Unmapped (MSP-wide)',
        'rows': rows, 'counts': counts, 'state': state, 'badge': BADGE[state], 'label': LABEL[state], 'jobs_total': len(rows),
        'newest_success': max(successes) if successes else None,
        'oldest_success': min(successes) if len(successes) == len(rows) and successes else None,
        'repos': repos, 'restore': restore_test_summary(tests, policy, now), 'tests': tests,
        'open_alerts': BackupAlert.objects.filter(organization=org, status__in=['open', 'acknowledged']).count(),
        'policy': policy,
        'stale_connections': sorted({r['job'].connection.name for r in rows if r['freshness'] != 'fresh'}),
    }


def customers_with_data(orgs):
    return orgs.filter(
        Q(backup_jobs__isnull=False) | Q(backup_repositories__isnull=False) | Q(backup_connections__isnull=False)
        | Q(backup_connections_for_customer__isnull=False) | Q(backup_protected_systems__isnull=False)
    ).distinct().order_by('name')


def asset_backup_panel(asset, user, now=None):
    """The Device Workspace panel: backup state of the systems linked to this
    asset, with source and data age. None when the user may not see backup
    status for the asset's customer or nothing is linked."""
    from accounts.permission_utils import user_has_org_perm
    from .access import VIEW
    if not user_has_org_perm(user, asset.organization_id, VIEW):
        return None
    now = now or timezone.now()
    systems = list(asset.backup_systems.filter(customer_id=asset.organization_id).select_related('connection'))
    if not systems:
        return None
    out = []
    for system in systems:
        rows = job_rows(list(system.jobs.select_related('connection', 'organization')), now)
        out.append({'system': system, 'source': system.connection.get_provider_display(),
                    'connection': system.connection.name,
                    'state': worst(r['state'] for r in rows) if rows else 'unknown', 'rows': rows})
    return out
