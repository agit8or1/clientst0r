"""Redacted reconciliation report for a rehearsal.

Contains counts and per-record outcomes with source IDs - never field values.
Free text (names, reasons, error messages) is passed through ``redact_text``
with every staged secret of the plan, so a secret that leaked into a title or
an error message is still removed.
"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict

from django.utils import timezone

from .normalize import KINDS
from .planner import CATEGORIES, mapped_target, mapping_for
from .redact import redact_text
from .targets import SPECS

RECORD_COLUMNS = ['source_type', 'source_id', 'name', 'target_kind', 'category', 'action', 'outcome',
                  'target_model', 'target_id', 'broken_links', 'detail']
SUMMARY_COLUMNS = ['kind', 'source_records', *CATEGORIES, 'broken_links', 'applied', 'skipped', 'failed',
                   'pending', 'reconciled_in_clientst0r', 'not_reconciled', 'customer_total']


def _secrets(plan):
    out = []
    for rec in plan.staged.exclude(secret_data={}).only('secret_data'):
        out.extend(str(v) for v in (rec.secret_data or {}).values() if v)
    return out


def build_report(plan):
    secrets = _secrets(plan)
    org = plan.organization
    per_kind = defaultdict(Counter)
    records = []
    for item in plan.items.all().order_by('order', 'id'):
        c = per_kind[item.target_kind]
        c['source_records'] += 1
        c[item.category] += 1
        c['broken_links'] += 1 if item.broken_links else 0
        c[item.outcome if item.outcome != 'pending' else 'pending'] += 1
        kind, obj = mapped_target(plan, mapping_for(plan, item.source_type, item.source_id))
        reconciled = obj is not None and kind == item.target_kind
        c['reconciled_in_clientst0r'] += 1 if reconciled else 0
        detail = item.outcome_message or item.reason
        broken = [f"{l['role']} -> {l['source_type']} {l['source_id']}: {l.get('reason', '')}"
                  for l in item.links if l.get('status') == 'broken']
        if broken:
            detail = (detail + '; ' if detail else '') + 'broken links: ' + ' | '.join(broken)
        records.append({
            'source_type': item.source_type,
            'source_id': item.source_id,
            'name': redact_text(item.display_name, secrets),
            'target_kind': item.target_kind,
            'category': item.category,
            'action': item.action,
            'outcome': item.outcome,
            'target_model': SPECS[item.target_kind].model_name,
            'target_id': item.result_target_id or (obj.pk if reconciled else None) or item.target_id,
            'broken_links': item.broken_links,
            'detail': redact_text(detail, secrets),
        })
    summary = []
    for kind in KINDS:
        if kind not in per_kind:
            continue
        c = per_kind[kind]
        expected = c['source_records'] - c['unavailable']
        row = {'kind': kind, **{k: c.get(k, 0) for k in SUMMARY_COLUMNS if k not in ('kind',)}}
        row['not_reconciled'] = max(expected - c['reconciled_in_clientst0r'], 0)
        row['customer_total'] = SPECS[kind].scoped(org).count() if org else 0
        summary.append(row)
    changes = Counter((c.op, c.rolled_back) for c in plan.changes.all().only('op', 'rolled_back'))
    return {
        'generated_at': timezone.now().isoformat(),
        'rehearsal_id': plan.pk,
        'import_job_id': plan.import_job_id,
        'customer': {'id': org.pk if org else None, 'name': org.name if org else ''},
        'source': {'system': plan.source_system, 'account': plan.source_account,
                   'organization_id': plan.source_organization_id,
                   'organization_name': redact_text(plan.source_organization_name, secrets)},
        'status': plan.status,
        'reviewed_at': plan.reviewed_at.isoformat() if plan.reviewed_at else None,
        'applied_at': plan.applied_at.isoformat() if plan.applied_at else None,
        'plan_hash': plan.reviewed_plan_hash,
        'staging_hash': plan.reviewed_staging_hash or plan.staging_hash,
        'summary': summary,
        'unavailable_endpoints': [
            {k: (redact_text(v, secrets) if isinstance(v, str) else v) for k, v in e.items()}
            for e in (plan.unavailable or [])],
        'changes': {f'{op}{" (rolled back)" if rb else ""}': n for (op, rb), n in sorted(changes.items())},
        'records': records,
        'redaction': 'Field values are not included. Passwords, OTP secrets, API keys, tokens and '
                     'confidential fields are never part of this report.',
    }


def records_csv(report):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=RECORD_COLUMNS)
    writer.writeheader()
    for row in report['records']:
        writer.writerow(row)
    return buf.getvalue()


def summary_csv(report):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SUMMARY_COLUMNS)
    writer.writeheader()
    for row in report['summary']:
        writer.writerow({k: row.get(k, '') for k in SUMMARY_COLUMNS})
    return buf.getvalue()
