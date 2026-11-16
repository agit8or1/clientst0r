"""
"Explain in plain English" — OPTIONAL AI, gated by `psa_ai_enabled`.

The advisor works fully without it: every finding already carries a
deterministic summary and the full calculation. When AI is on and the
technician holds the AI capability at the customer (technician access, the
same check as "Analyze ticket"), this sends ONLY the computed finding to the
customer's configured model through the existing multi-LLM layer
(psa_ai.services.policy_call: the customer's AI policy and exclusion,
model profile, budget, fixed provider hosts):

  * structured JSON of the facts, each labelled verified / estimate /
    unknown, the recommendations and their calculation; no tickets, no
    notes, and the customer's and contracts' names replaced by placeholders;
  * a system prompt that forbids inventing figures or assuming missing costs.

The answer is then checked: every currency amount and percentage in it must
be one of the figures it was given (`validate`). If any is not, the answer is
rejected and the page shows the deterministic summary instead. The AI never
creates drafts or changes anything. Narratives are cached per finding version.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from .models import Narrative

SYSTEM_PROMPT = (
    'You explain a profitability finding to an MSP account manager in plain English, in at most 150 words. '
    'You are given JSON computed by a deterministic system. Rules:\n'
    '1. Use ONLY figures that appear in the JSON, copied exactly. Never compute, estimate, round differently '
    'or invent any amount, rate or percentage.\n'
    '2. Facts have a "status": say clearly which figures are verified (recorded amounts), which are '
    'estimates (derived from rates), and which are unknown.\n'
    '3. Never assume a value for a missing or unknown cost. If inputs are missing, say the result is '
    'incomplete and name what is missing.\n'
    '4. Do not recommend anything that is not in "recommendations". Do not promise outcomes.\n'
    '5. These are operational estimates, not an accounting P&L.\n'
    'Answer in plain prose without headings.'
)

MONEY_RE = re.compile(r'(?:\$|USD\s?)\s?(-?\d[\d,]*(?:\.\d+)?)', re.I)
PCT_RE = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)\s?(?:%|percent\b)', re.I)
NUM_RE = re.compile(r'-?\d[\d,]*(?:\.\d+)?')


class NarrativeRefused(Exception):
    pass


def _names(finding):
    names = {finding.client_org.name: 'the customer'}
    from psa.models import Contract
    for c in Contract.objects.filter(client_org=finding.client_org).only('name'):
        if c.name:
            names[c.name] = 'the contract'
    return names


def _redact(value, names):
    if isinstance(value, str):
        for name in sorted(names, key=len, reverse=True):
            if name and len(name) > 1:
                value = value.replace(name, names[name])
        return value
    if isinstance(value, list):
        return [_redact(v, names) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, names) for k, v in value.items() if k not in ('records', 'url')}
    return value


STATUS = {'verified': 'verified', 'estimate': 'estimate', 'unknown': 'unknown',
          'not_applicable': 'not applicable'}


def build_payload(finding):
    """The only data sent to the model."""
    facts = []
    for f in (finding.facts or {}).values():
        facts.append({
            'label': f.get('label'), 'unit': f.get('unit'), 'value': f.get('value'),
            'status': STATUS.get(f.get('basis'), 'unknown') if f.get('value') is not None else 'unknown',
            'known_part_only': f.get('lower') if f.get('value') is None else None,
            'upper_bound': f.get('upper') if f.get('value') is None else None,
            'missing': f.get('missing') or [], 'note': f.get('note') or '',
        })
    recs = []
    for r in finding.recommendations.all():
        w = r.work or {}
        recs.append({'type': r.get_rec_type_display(), 'title': r.title, 'status': r.status,
                     'proposed': r.proposed, 'formula': w.get('formula'), 'steps': w.get('steps', []),
                     'assumptions': w.get('assumptions', []), 'unknown': w.get('unknown', [])})
    payload = {
        'finding': {'type': finding.get_detector_label(), 'severity': finding.severity,
                    'period': f'{finding.period_start:%Y-%m-%d} to {finding.period_end:%Y-%m-%d}',
                    'title': finding.title, 'summary': finding.summary,
                    'complete': finding.is_complete, 'missing_inputs': finding.missing_inputs or []},
        'facts': facts, 'recommendations': recs, 'thresholds': finding.evidence or {},
    }
    return _redact(payload, _names(finding))


def _to_dec(text):
    try:
        return Decimal(text.replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def allowed_numbers(payload):
    out = set()
    scan = dict(payload)
    scan['finding'] = {k: v for k, v in payload.get('finding', {}).items() if k != 'period'}
    for m in NUM_RE.finditer(json.dumps(scan, default=str)):
        d = _to_dec(m.group(0))
        if d is not None:
            out.add(abs(d))
    return out


def _matches(figure_text, allowed):
    d = _to_dec(figure_text)
    if d is None:
        return False
    d = abs(d)
    places = -d.as_tuple().exponent if d.as_tuple().exponent < 0 else 0
    q = Decimal(1).scaleb(-places)
    return any(a.quantize(q) == d for a in allowed if a.adjusted() < 20)


def validate(text, payload):
    """(ok, figures not found in the input)."""
    allowed = allowed_numbers(payload)
    bad = []
    for rx in (MONEY_RE, PCT_RE):
        for m in rx.finditer(text or ''):
            if not _matches(m.group(1), allowed):
                bad.append(m.group(0).strip())
    return (not bad), bad


def _call_model(finding, user, payload):
    """(text, model label) through the existing AI layer, or NarrativeRefused."""
    from psa_ai.services import policy_call
    try:
        policy, profile = policy_call.prepare_for_org(finding.client_org, user)
        text, _t_in, _t_out = policy_call.complete_for_org(
            finding.client_org, policy, profile, SYSTEM_PROMPT,
            'Finding (JSON):\n' + json.dumps(payload, indent=1, default=str))
    except (policy_call.PolicyRefused, policy_call.ProviderFailed) as e:
        raise NarrativeRefused(str(e))
    return text, policy_call.model_label(profile)


def cached(finding):
    return Narrative.objects.filter(finding=finding, finding_version=finding.version).first()


def explain(finding, user, request=None):
    """The narrative for this finding version (cached), or NarrativeRefused."""
    from .actions import audit
    from .permissions import can_use_ai
    if not can_use_ai(user, finding.client_org):
        raise NarrativeRefused('AI explanations are off, or you do not have the AI capability for this customer.')
    existing = cached(finding)
    if existing is not None:
        return existing
    payload = build_payload(finding)
    text, label = _call_model(finding, user, payload)
    ok, bad = validate(text, payload)
    narrative = Narrative.objects.create(
        finding=finding, finding_version=finding.version, status='accepted' if ok else 'rejected',
        text=text if ok else '', rejected_figures=bad[:50], model_label=label[:100],
        payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
        created_by=user)
    audit(user, 'create', finding,
          'AI explanation generated.' if ok else f'AI explanation rejected: figures not in the facts ({", ".join(bad[:5])}).',
          request, event='advisor_narrative_' + narrative.status, model=label)
    return narrative
