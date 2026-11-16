"""
The advisor run: compute facts, run every detector, store findings.

Idempotent: a finding is keyed by customer + detector + period (+ subject,
e.g. one contract) and at most one is open per key (database constraint);
a later run updates it in place and bumps its version only when its content
changed. Findings a run no longer raises are closed: "resolved" in the same
period, "superseded" once a new period starts. Recommendations are updated
only while open; accepted, dismissed and implemented ones are never touched.
"""
from __future__ import annotations

import hashlib
import json
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import inputs
from .detectors import REGISTRY, Context
from .facts import CustomerFacts, last_full_month_end, window_ending
from .models import AdvisorRun, AdvisorSettings, Finding, Recommendation

logger = logging.getLogger('advisor')


def coverage():
    out = {}
    for key, det in REGISTRY.items():
        ok, reason = det.availability()
        out[key] = {'label': det.label, 'evaluated': ok, 'reason': reason, 'description': det.description}
    return out


def candidate_clients(start, end):
    """Customers with contracts, invoices or time in [start, end]."""
    from core.models import Organization
    from psa.models import Contract, Invoice, TicketTimeEntry
    ids = set(Contract.objects.exclude(status='draft').filter(start_date__lte=end)
              .filter(Q(end_date__isnull=True) | Q(end_date__gte=start)).values_list('client_org_id', flat=True))
    ids |= set(Invoice.objects.filter(invoice_date__gte=start, invoice_date__lte=end)
               .values_list('client_org_id', flat=True))
    ids |= set(TicketTimeEntry.objects.filter(started_at__date__gte=start, started_at__date__lte=end)
               .values_list('ticket__organization_id', flat=True))
    ids.discard(None)
    return Organization.objects.filter(pk__in=ids, is_active=True).order_by('name')


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def store(client, detector_key, window, raised, now):
    """Create or update the open finding for one detector result. Returns
    (finding, created, changed)."""
    facts_json = {f.key: f.as_json() for f in raised.facts}
    recs_json = [{'key': r.key, 'type': r.rec_type, 'title': r.title, 'proposed': r.proposed, 'work': r.work}
                 for r in raised.recommendations]
    digest = _hash({'title': raised.title, 'summary': raised.summary, 'facts': facts_json,
                    'evidence': raised.evidence, 'recs': recs_json, 'severity': raised.severity,
                    'assessment': raised.assessment, 'missing': raised.missing})
    finding = (Finding.objects.select_for_update()
               .filter(client_org=client, detector=detector_key, period_key=window.key,
                       subject_key=raised.subject_key, status='open').first())
    created = finding is None
    changed = created or finding.facts_hash != digest
    if created:
        finding = Finding(client_org=client, detector=detector_key, period_key=window.key,
                          subject_key=raised.subject_key, first_seen_at=now)
    elif changed:
        finding.version += 1
    finding.period_start, finding.period_end = window.start, window.end
    finding.severity = raised.severity
    finding.assessment = raised.assessment
    finding.title = raised.title[:300]
    finding.summary = raised.summary
    finding.is_complete = raised.is_complete
    finding.missing_inputs = list(raised.missing)
    finding.facts = facts_json
    finding.evidence = raised.evidence
    finding.facts_hash = digest
    finding.last_evaluated_at = now
    finding.save()
    for spec in raised.recommendations:
        rec = Recommendation.objects.filter(finding=finding, key=spec.key).first()
        if rec is not None and rec.status != 'open':
            continue
        if rec is None:
            rec = Recommendation(finding=finding, key=spec.key)
        rec.rec_type = spec.rec_type
        rec.title = spec.title[:300]
        rec.rationale = spec.rationale
        rec.contract = spec.contract
        rec.proposed = spec.proposed
        rec.work = spec.work
        rec.save()
    keep = {s.key for s in raised.recommendations}
    Recommendation.objects.filter(finding=finding, status='open').exclude(key__in=keep).delete()
    return finding, created, changed


def run_for_client(client, *, today, as_of, rates, cov, run):
    settings = AdvisorSettings.for_client(client)
    window = window_ending(as_of, settings.lookback_months)
    facts = CustomerFacts(client, window, rates, settings, today)
    prior = CustomerFacts(client, window.prior(), rates, settings, today)
    ctx = Context(client=client, settings=settings, window=window, facts=facts, prior=prior, today=today)
    now = timezone.now()
    disabled = set(settings.disabled_detectors or [])
    for key, det in REGISTRY.items():
        if not cov[key]['evaluated'] or key in disabled:
            continue
        try:
            results = det.evaluate(ctx)
        except Exception:
            logger.exception('advisor detector %s failed for customer %s', key, client.pk)
            run.error += f'{key} failed for customer {client.pk}\n'
            continue
        with transaction.atomic():
            seen = set()
            for raised in results:
                finding, created, changed = store(client, key, window, raised, now)
                seen.add(finding.pk)
                if created:
                    run.raised += 1
                elif changed:
                    run.updated += 1
            stale = Finding.objects.filter(client_org=client, detector=key, status='open').exclude(pk__in=seen)
            for f in stale:
                f.status = 'resolved' if f.period_key == window.key else 'superseded'
                f.resolved_at = now
                f.save(update_fields=['status', 'resolved_at', 'updated_at'])
                run.resolved += 1


def run(today=None, clients=None):
    """Run every available detector for every candidate customer."""
    from .actions import sync_implemented
    today = today or timezone.localdate()
    as_of = last_full_month_end(today)
    cov = coverage()
    run = AdvisorRun.objects.create(period_end=as_of, coverage=cov)
    rates = inputs.Rates()
    if clients is None:
        earliest = window_ending(as_of, 12).prior().start
        clients = candidate_clients(earliest, today)
    count = 0
    for client in clients:
        count += 1
        run_for_client(client, today=today, as_of=as_of, rates=rates, cov=cov, run=run)
    sync_implemented()
    run.customers = count
    run.finished_at = timezone.now()
    run.save()
    return run
