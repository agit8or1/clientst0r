"""What is healthy, and how old the evidence is.

Rule: nothing is "ok" on evidence that is old or missing. A connection whose
last successful contact is stale makes every job under it `stale`; a job that
has never reported is `unknown`. Warning-level runs count as a completed
backup (they produced one) but are shown as warnings.
"""
from datetime import timedelta

from django.utils import timezone

from .models import BackupAlertPolicy

POLL_STALE_AFTER = timedelta(minutes=120)

# Worst first.
RANK = {'failed': 5, 'missed': 4, 'stale': 3, 'warning': 2, 'unknown': 1, 'ok': 0}
LABEL = {'failed': 'Failed', 'missed': 'Missed', 'stale': 'Stale data', 'warning': 'Warning',
         'unknown': 'No data', 'ok': 'Healthy'}
BADGE = {'failed': 'danger', 'missed': 'danger', 'stale': 'warning', 'warning': 'warning',
         'unknown': 'secondary', 'ok': 'success'}


def worst(states):
    states = list(states)
    return max(states, key=lambda s: RANK[s]) if states else 'unknown'


def connection_freshness(connection, now=None):
    """('fresh' | 'stale' | 'never' | 'inactive', last good contact or None)."""
    now = now or timezone.now()
    if not connection.active:
        return 'inactive', connection.last_poll_at
    if connection.last_poll_at is None:
        return 'never', None
    if connection.is_push:
        # Push sources are judged per job (a quiet host shows as missed).
        return 'fresh', connection.last_poll_at
    if connection.last_poll_status == 'error' or now - connection.last_poll_at > POLL_STALE_AFTER:
        return 'stale', connection.last_poll_at
    return 'fresh', connection.last_poll_at


def age_text(moment, now=None):
    if moment is None:
        return 'never'
    delta = (now or timezone.now()) - moment
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return 'just now'
    if minutes < 90:
        return f'{minutes} min ago'
    hours = minutes // 60
    if hours < 48:
        return f'{hours} h ago'
    return f'{hours // 24} d ago'


def job_state(job, freshness, policy=None, now=None):
    now = now or timezone.now()
    policy = policy or BackupAlertPolicy.for_org(job.organization)
    if freshness in ('stale', 'inactive'):
        return 'stale'
    if freshness == 'never' or job.last_run_at is None:
        return 'unknown'
    if job.last_status == 'failed':
        return 'failed'
    threshold = timedelta(hours=job.expected_interval_hours or policy.missed_threshold_hours)
    if job.last_success_at is None or now - job.last_success_at > threshold:
        return 'missed'
    if job.last_status == 'warning':
        return 'warning'
    return 'ok'


def job_rows(jobs, now=None):
    """Annotated rows [{job, state, label, badge, age, ...}] for display."""
    now = now or timezone.now()
    fresh_cache, policy_cache, rows = {}, {}, []
    for job in jobs:
        conn = job.connection
        if conn.pk not in fresh_cache:
            fresh_cache[conn.pk] = connection_freshness(conn, now)
        freshness, contact = fresh_cache[conn.pk]
        if job.organization_id not in policy_cache:
            policy_cache[job.organization_id] = BackupAlertPolicy.for_org(job.organization)
        state = job_state(job, freshness, policy_cache[job.organization_id], now)
        rows.append({'job': job, 'state': state, 'label': LABEL[state], 'badge': BADGE[state],
                     'last_success_age': age_text(job.last_success_at, now),
                     'data_age': age_text(contact, now), 'freshness': freshness})
    return rows


def restore_test_summary(tests, policy, now=None):
    """Latest restore test and whether it is overdue. Independent of backup
    success: a green backup with no restore test is still 'untested'."""
    now = now or timezone.now()
    latest = tests[0] if tests else None
    if latest is None:
        return {'latest': None, 'state': 'none', 'label': 'Never tested', 'badge': 'secondary'}
    days = (now.date() - latest.tested_on).days
    if latest.result == 'failed':
        return {'latest': latest, 'days': days, 'state': 'failed', 'label': f'Failed {days} d ago',
                'badge': 'danger'}
    if days > policy.restore_test_max_age_days:
        return {'latest': latest, 'days': days, 'state': 'overdue', 'label': f'Overdue ({days} d ago)',
                'badge': 'warning'}
    label = f'{latest.get_result_display()} {days} d ago'
    return {'latest': latest, 'days': days, 'state': 'ok', 'label': label,
            'badge': 'success' if latest.result == 'passed' else 'warning'}
