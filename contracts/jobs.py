"""Background jobs with retries and idempotency.

Each job has a unique idempotency key, so enqueueing the same thing twice
(a double click, two scheduler runs) yields one job. A job is claimed with a
conditional UPDATE before it runs, so two workers never run the same job.
Failures are retried with back-off up to `max_attempts`; a job that is no
longer applicable (the contract was signed, the invitation revoked) is
cancelled instead of sent.

Invitation e-mails mint their link token at send time: tokens are stored
only as hashes, so a retried e-mail gets a fresh token and the token of a
failed attempt is revoked. Job payloads never hold tokens or codes.

Runs from the scheduler task "Contract Jobs" (every minute), and inline right
after the action that queued it so a sent contract does not wait a minute.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ContractInvitation, ContractJob

logger = logging.getLogger('contracts')

BACKOFF_MINUTES = (1, 5, 15, 60, 180, 360)
LOCK_MINUTES = 10


class Skip(Exception):
    """The job is no longer applicable: cancel it."""


class RetryLater(Exception):
    """Not an error: try again later (e.g. finalization not done yet)."""


def enqueue(kind, key, *, contract=None, version=None, invitation=None, payload=None, run_at=None,
            max_attempts=None):
    try:
        with transaction.atomic():
            job = ContractJob.objects.create(
                kind=kind, idempotency_key=key[:200], contract=contract, version=version, invitation=invitation,
                payload=payload or {}, next_attempt_at=run_at or timezone.now(),
                **({'max_attempts': max_attempts} if max_attempts else {}))
        return job, True
    except IntegrityError:
        return ContractJob.objects.get(idempotency_key=key[:200]), False


def cancel_for(*, contract=None, invitation=None, kinds=None, reason=''):
    qs = ContractJob.objects.filter(status__in=[ContractJob.PENDING])
    if contract is not None:
        qs = qs.filter(contract=contract)
    if invitation is not None:
        qs = qs.filter(invitation=invitation)
    if kinds:
        qs = qs.filter(kind__in=kinds)
    return qs.update(status=ContractJob.CANCELLED, last_error=reason[:500], completed_at=timezone.now())


def _claim(job, now) -> bool:
    return bool(ContractJob.objects.filter(
        pk=job.pk, status__in=[ContractJob.PENDING, ContractJob.RUNNING], next_attempt_at__lte=now,
    ).filter(models_q_unlocked(now)).update(status=ContractJob.RUNNING, locked_until=now + timedelta(minutes=LOCK_MINUTES),
                                            attempts=job.attempts + 1))


def models_q_unlocked(now):
    from django.db.models import Q
    return Q(status=ContractJob.PENDING) | Q(locked_until__lt=now)


def run_job(job, now=None):
    now = now or timezone.now()
    if not _claim(job, now):
        return None
    job.refresh_from_db()
    try:
        HANDLERS[job.kind](job)
    except Skip as exc:
        ContractJob.objects.filter(pk=job.pk).update(status=ContractJob.CANCELLED, last_error=str(exc)[:500],
                                                     completed_at=timezone.now(), locked_until=None)
        return 'cancelled'
    except RetryLater as exc:
        ContractJob.objects.filter(pk=job.pk).update(
            status=ContractJob.PENDING, last_error=str(exc)[:500], locked_until=None,
            attempts=max(0, job.attempts - 1), next_attempt_at=timezone.now() + timedelta(minutes=1))
        return 'later'
    except Exception as exc:  # noqa: BLE001 — recorded on the job and retried
        logger.warning('contract job %s (%s) failed: %s', job.pk, job.kind, exc)
        if job.attempts >= job.max_attempts:
            ContractJob.objects.filter(pk=job.pk).update(status=ContractJob.FAILED, last_error=str(exc)[:500],
                                                         completed_at=timezone.now(), locked_until=None)
            _gave_up(job, exc)
            return 'failed'
        delay = BACKOFF_MINUTES[min(job.attempts - 1, len(BACKOFF_MINUTES) - 1)]
        ContractJob.objects.filter(pk=job.pk).update(status=ContractJob.PENDING, last_error=str(exc)[:500],
                                                     locked_until=None,
                                                     next_attempt_at=timezone.now() + timedelta(minutes=delay))
        return 'retry'
    ContractJob.objects.filter(pk=job.pk).update(status=ContractJob.DONE, completed_at=timezone.now(),
                                                 locked_until=None, last_error='')
    return 'done'


def run_now(jobs):
    """Run freshly queued jobs inline; failures stay queued for the scheduler."""
    out = []
    for job in jobs:
        if job is None:
            continue
        try:
            out.append(run_job(job))
        except Exception:  # noqa: BLE001
            logger.exception('inline contract job %s failed', getattr(job, 'pk', None))
    return out


def run_due(limit=100, now=None) -> dict:
    now = now or timezone.now()
    counts = {}
    from django.db.models import Q
    due = ContractJob.objects.filter(next_attempt_at__lte=now).filter(
        Q(status=ContractJob.PENDING) | Q(status=ContractJob.RUNNING, locked_until__lt=now)).order_by(
        'next_attempt_at')[:limit]
    for job in list(due):
        result = run_job(job, now)
        if result:
            counts[result] = counts.get(result, 0) + 1
    return counts


def _gave_up(job, exc):
    from . import events
    if job.kind in ('invitation_email', 'reminder_email') and job.invitation_id:
        ContractInvitation.objects.filter(pk=job.invitation_id).update(delivery_status='failed',
                                                                       delivery_error=str(exc)[:300])
    if job.contract_id:
        events.record(job.contract, 'email_failed' if job.kind != 'finalize' else 'finalization_failed',
                      version=job.version, invitation=job.invitation, actor_label='Background job',
                      message=f'Gave up after {job.attempts} attempts: {str(exc)[:200]}')


# --- handlers ------------------------------------------------------------------

def _invitation_email(job, reminder=False):
    from . import events, mail, signing
    inv = ContractInvitation.objects.select_related('contract', 'version').get(pk=job.invitation_id)
    contract = inv.contract
    if inv.status != ContractInvitation.ACTIVE or inv.is_expired():
        raise Skip(f'invitation is {inv.get_status_display().lower()}')
    if contract.status not in contract.OPEN_FOR_SIGNING:
        raise Skip(f'contract is {contract.get_status_display().lower()}')
    if contract.current_version_id != inv.version_id:
        raise Skip('a newer version replaced this one')
    if reminder and not signing.reminders_apply(inv):
        raise Skip('reminders no longer apply')
    raw, token = signing.mint_token(inv, 'reminder' if reminder else 'email', None)
    try:
        mail.send_invitation(inv, raw, reminder=reminder)
    except Exception:
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])
        ContractInvitation.objects.filter(pk=inv.pk).update(delivery_status='failed')
        raise
    now = timezone.now()
    updates = {'delivery_status': 'accepted', 'delivery_error': '', 'last_sent_at': now}
    if reminder:
        ContractInvitation.objects.filter(pk=inv.pk).update(reminders_sent=inv.reminders_sent + 1,
                                                            last_reminder_at=now, **updates)
    else:
        ContractInvitation.objects.filter(pk=inv.pk).update(send_count=inv.send_count + 1, **updates)
    events.record(contract, 'email_accepted', version=inv.version, invitation=inv, actor_label='Mail server',
                  message=f'{"Reminder" if reminder else "Invitation"} to {inv.email} accepted by the mail server '
                          '(this does not prove delivery)')


def _staff_email(job):
    from . import mail
    p = job.payload
    mail.send_staff(p['to'], p['subject'], p['body'], p.get('link_path', ''))


def _finalize(job):
    from . import signing
    signing.finalize_version(job.version)


def _completed_copy(job):
    from . import mail
    inv = ContractInvitation.objects.select_related('version', 'contract').get(pk=job.invitation_id)
    if inv.version.finalization_status != 'done':
        raise RetryLater('the final PDF is not ready yet')
    mail.send_completed_copy(inv)


HANDLERS = {
    'invitation_email': _invitation_email,
    'reminder_email': lambda job: _invitation_email(job, reminder=True),
    'staff_email': _staff_email,
    'finalize': _finalize,
    'completed_copy': _completed_copy,
}
