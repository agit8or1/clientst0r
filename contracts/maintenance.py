"""Periodic contract work (scheduler task "Contract Reminders and Expirations",
hourly): expire links and contracts past their deadline, queue reminders,
raise renewal / expiration alerts, retry stuck finalization, and apply the
access-log retention."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from . import events, jobs, notify, services, signing
from .models import (ContractDocument, ContractEvent, ContractInvitation, ContractSettings, ContractVersion)

D = ContractDocument


def expire(now=None) -> dict:
    now = now or timezone.now()
    counts = {'invitations': 0, 'contracts': 0}
    for inv in ContractInvitation.objects.filter(status__in=ContractInvitation.OPEN, expires_at__lte=now) \
            .select_related('contract', 'version'):
        if services.revoke(inv, None, reason='Link expired', status=ContractInvitation.EXPIRED):
            counts['invitations'] += 1
    today = timezone.localdate(now)
    for c in D.objects.filter(status__in=D.OPEN_FOR_SIGNING, acceptance_deadline__lt=today):
        try:
            services.transition(c, D.EXPIRED, only_from=D.OPEN_FOR_SIGNING, expired_at=now)
        except services.InvalidTransition:
            continue
        v = c.current_version
        if v is not None:
            for inv in v.invitations.filter(status__in=ContractInvitation.OPEN):
                services.revoke(inv, None, reason='Acceptance deadline passed', status=ContractInvitation.EXPIRED,
                                record=False)
            if v.status == ContractVersion.SENT:
                v.status = ContractVersion.EXPIRED
                v.save(update_fields=['status'])
        jobs.cancel_for(contract=c, kinds=['invitation_email', 'reminder_email'], reason='expired')
        events.record(c, 'expired', version=v, actor_label='System',
                      message=f'Not signed by the acceptance deadline {c.acceptance_deadline:%Y-%m-%d}')
        notify.notify(c, 'expired', f'{c.reference} "{c.title}" for {c.client_name} expired unsigned '
                      f'(deadline {c.acceptance_deadline:%Y-%m-%d}).', f'expired:{c.pk}:{v.pk if v else 0}')
        counts['contracts'] += 1
    return counts


def queue_reminders(now=None) -> int:
    now = now or timezone.now()
    queued = 0
    qs = ContractInvitation.objects.filter(status=ContractInvitation.ACTIVE, activated_at__isnull=False,
                                           contract__status__in=D.OPEN_FOR_SIGNING).select_related('contract')
    for inv in qs:
        if inv.contract.current_version_id != inv.version_id or not signing.reminders_apply(inv):
            continue
        s = ContractSettings.for_organization(inv.contract.organization)
        last = inv.last_reminder_at or inv.activated_at
        wait = s.reminder_first_after_days if inv.reminders_sent == 0 else s.reminder_interval_days
        if now < last + timedelta(days=max(1, wait)):
            continue
        n = inv.reminders_sent + 1
        job, created = jobs.enqueue('reminder_email', f'reminder:{inv.pk}:{n}', contract=inv.contract,
                                    version=inv.version, invitation=inv)
        if created:
            events.record(inv.contract, 'reminder_queued', version=inv.version, invitation=inv, actor_label='System',
                          message=f'Reminder {n} to {inv.email} queued')
            queued += 1
    return queued


def term_alerts(now=None) -> int:
    today = timezone.localdate(now or timezone.now())
    raised = 0
    for c in D.objects.filter(status=D.SIGNED, expiration_date__isnull=False, expiration_date__gte=today
                              - timedelta(days=1)):
        s = ContractSettings.for_organization(c.organization)
        days = (c.expiration_date - today).days
        if s.renewal_alert_days and days <= s.renewal_alert_days and \
                notify.raise_alert(c, f'renewal:{c.pk}:{c.expiration_date}', 'renewal'):
            notify.notify(c, 'renewal', f'{c.reference} "{c.title}" for {c.client_name} ends on '
                          f'{c.expiration_date:%Y-%m-%d} ({days} days). Time to prepare the renewal'
                          + (' (it renews automatically).' if c.auto_renew else '.'),
                          f'renewal:{c.pk}:{c.expiration_date}')
            raised += 1
        if s.expiration_alert_days and days <= s.expiration_alert_days and \
                notify.raise_alert(c, f'expiring:{c.pk}:{c.expiration_date}', 'expiring'):
            notify.notify(c, 'expiring', f'{c.reference} "{c.title}" for {c.client_name} ends in {days} days '
                          f'({c.expiration_date:%Y-%m-%d}).', f'expiring:{c.pk}:{c.expiration_date}')
            raised += 1
    return raised


def retry_finalization() -> int:
    n = 0
    for v in ContractVersion.objects.filter(status=ContractVersion.SIGNED).exclude(finalization_status='done'):
        job, created = jobs.enqueue('finalize', f'finalize:{v.pk}', contract=v.contract, version=v, max_attempts=10)
        if not created and job.status in ('failed', 'cancelled'):
            type(job).objects.filter(pk=job.pk).update(status='pending', attempts=0, next_attempt_at=timezone.now())
            n += 1
    return n


def apply_retention(now=None) -> int:
    """Blank IP address and browser on link/view/code events older than the
    retention period. Signatures keep theirs (they are part of the evidence)."""
    now = now or timezone.now()
    total = 0
    kinds = ['link_requested', 'human_view', 'verified_view', 'code_sent', 'code_failed', 'code_verified',
             'downloaded']
    for s in ContractSettings.objects.all():
        if not s.access_log_retention_days:
            continue
        cutoff = now - timedelta(days=s.access_log_retention_days)
        qs = ContractEvent.objects.filter(kind__in=kinds, at__lt=cutoff).filter(
            Q(ip_address__isnull=False) | ~Q(user_agent=''))
        if s.organization_id is None:
            overridden = ContractSettings.objects.filter(organization__isnull=False).values('organization_id')
            qs = qs.exclude(contract__organization_id__in=overridden)
        else:
            qs = qs.filter(contract__organization_id=s.organization_id)
        # The one sanctioned change to history: privacy retention.
        total += qs.update(ip_address=None, user_agent='')
    return total


def run(now=None) -> dict:
    now = now or timezone.now()
    out = {'expired': expire(now), 'reminders_queued': queue_reminders(now), 'term_alerts': term_alerts(now),
           'finalization_retries': retry_finalization(), 'retention_cleared': apply_retention(now)}
    out['jobs'] = jobs.run_due(now=now)
    return out
