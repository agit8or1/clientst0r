"""Alert evaluation. Run after every poll / on every scheduler tick.

Rules (thresholds from BackupAlertPolicy, per customer or the default):
  missed             no completed backup within the threshold
  failed             the latest run failed
  repeated_failures  the last N runs all failed (critical)
  capacity           repository >= capacity_pct full
  repo_unavailable   the provider reports the repository unreachable
  no_job             a protected system has no backup job
  stale              the connection has no recent good contact

While a connection is stale nothing else is concluded from its old data:
the single `stale` alert is raised, other live alerts are left as they are
(never auto-resolved on stale evidence), and no new job alerts are opened.

Dedup: one live alert per (connection, dedup_key); a re-evaluation updates it.
Resolved alerts are closed automatically when the condition clears.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .health import age_text, connection_freshness
from .models import (ALERT_ACK, ALERT_OPEN, ALERT_RESOLVED, BackupAlert, BackupAlertPolicy, BackupConnection)

logger = logging.getLogger('backup_monitoring')


def _desired_for_connection(conn, now):
    """{dedup_key: dict(alert fields)} for a connection with fresh data."""
    out = {}
    policies = {}

    def policy_for(org):
        key = org.pk if org is not None else None
        if key not in policies:
            policies[key] = BackupAlertPolicy.for_org(org)
        return policies[key]

    for job in conn.jobs.select_related('organization', 'system'):
        policy = policy_for(job.organization)
        base = dict(organization=job.organization, job=job, system=job.system)
        if job.last_run_at is None:
            continue
        threshold = job.expected_interval_hours or policy.missed_threshold_hours
        if job.last_success_at is None or now - job.last_success_at > timedelta(hours=threshold):
            since = age_text(job.last_success_at, now)
            out[f'missed:{job.external_id}'] = dict(
                base, kind='missed', severity='critical',
                title=f'No successful backup: {job.name}',
                detail=f'Last completed backup: {since if job.last_success_at else "none on record"}. '
                       f'Threshold: {threshold} h.')
        if job.last_status == 'failed':
            last = job.runs.order_by('-started_at').first()
            out[f'failed:{job.external_id}'] = dict(
                base, kind='failed', severity='warning', title=f'Backup failed: {job.name}',
                detail=(last.message if last else '') or 'The latest run failed.')
        n = policy.consecutive_failures
        if n and n >= 1:
            recent = list(job.runs.order_by('-started_at').values_list('status', flat=True)[:n])
            if len(recent) == n and all(s == 'failed' for s in recent):
                out[f'repeated:{job.external_id}'] = dict(
                    base, kind='repeated_failures', severity='critical',
                    title=f'{n} consecutive failed backups: {job.name}',
                    detail=f'The last {n} runs of this job all failed.')

    for repo in conn.repositories.select_related('organization'):
        policy = policy_for(repo.organization)
        base = dict(organization=repo.organization, repository=repo)
        if not repo.available:
            out[f'repo_unavailable:{repo.external_id}'] = dict(
                base, kind='repo_unavailable', severity='critical',
                title=f'Backup repository unavailable: {repo.name}', detail=repo.message or 'Reported unavailable.')
        pct = repo.used_pct
        if pct is not None and pct >= policy.capacity_pct:
            out[f'capacity:{repo.external_id}'] = dict(
                base, kind='capacity', severity='critical' if pct >= 95 else 'warning',
                title=f'Backup repository {pct:g}% full: {repo.name}',
                detail=f'Threshold {policy.capacity_pct}%.')

    for system in conn.systems.select_related('customer').filter(jobs__isnull=True):  # unmapped (customer NULL) uses the default policy
        if policy_for(system.customer).alert_missing_protected_device:
            out[f'no_job:{system.external_id}'] = dict(
                organization=system.customer, system=system, kind='no_job', severity='warning',
                title=f'No backup job protects {system.name}',
                detail='This system is registered for backup monitoring but no job reports on it.')
    return out


def _upsert(conn, key, fields, now, user_ticket=True):
    live = BackupAlert.objects.filter(connection=conn, dedup_key=key, status__in=[ALERT_OPEN, ALERT_ACK]).first()
    if live is not None:
        live.last_seen_at = now
        live.occurrences += 1
        live.title, live.detail, live.severity = fields['title'][:300], fields['detail'], fields['severity']
        live.save(update_fields=['last_seen_at', 'occurrences', 'title', 'detail', 'severity'])
        return live, False
    try:
        with transaction.atomic():
            alert = BackupAlert.objects.create(
                connection=conn, dedup_key=key, first_seen_at=now, last_seen_at=now,
                **dict(fields, title=fields['title'][:300]))
    except IntegrityError:  # concurrent evaluation created it first
        return BackupAlert.objects.get(connection=conn, dedup_key=key, status__in=[ALERT_OPEN, ALERT_ACK]), False
    return alert, True


def evaluate_connection(conn: BackupConnection, now=None) -> dict:
    now = now or timezone.now()
    stats = {'opened': 0, 'resolved': 0, 'live': 0}
    if not conn.active:
        return stats
    freshness, contact = connection_freshness(conn, now)
    if freshness == 'never':
        return stats          # nothing has ever been reported: nothing to conclude
    if freshness == 'stale':
        desired = {'stale': dict(
            organization=conn.default_customer, kind='stale', severity='warning',
            title=f'No recent data from {conn.name}',
            detail=f'Last good contact {age_text(contact, now)}. '
                   f'{conn.last_poll_error or "Backup health below is not current."}')}
        resolve_missing = False
    else:
        desired = _desired_for_connection(conn, now)
        resolve_missing = True

    new_alerts = []
    for key, fields in desired.items():
        alert, created = _upsert(conn, key, fields, now)
        stats['live'] += 1
        if created:
            stats['opened'] += 1
            new_alerts.append(alert)
    if resolve_missing:
        stale = BackupAlert.objects.filter(connection=conn, status__in=[ALERT_OPEN, ALERT_ACK]) \
            .exclude(dedup_key__in=list(desired))
        stats['resolved'] = stale.update(status=ALERT_RESOLVED, resolved_at=now)
    for alert in new_alerts:
        _maybe_ticket(alert)
    return stats


def _maybe_ticket(alert):
    if alert.organization_id is None or alert.ticket_id:
        return   # a ticket needs a customer
    if not BackupAlertPolicy.for_org(alert.organization).auto_ticket:
        return
    from .tickets import create_ticket_for_alert
    try:
        create_ticket_for_alert(alert)
    except Exception:
        logger.exception('auto-ticket for backup alert %s failed', alert.pk)


def evaluate_all(now=None) -> dict:
    total = {'opened': 0, 'resolved': 0, 'live': 0}
    for conn in BackupConnection.objects.filter(active=True):
        try:
            s = evaluate_connection(conn, now)
        except Exception:
            logger.exception('backup alert evaluation failed for connection %s', conn.pk)
            continue
        for k in total:
            total[k] += s[k]
    return total
