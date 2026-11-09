"""
Turn a model's answer into the analysis structure, treating it as untrusted.

The model is asked for one JSON object (prompts/system_analysis.md). Whatever
comes back is parsed into a fixed shape and nothing else survives:

  observed_facts       [{text, evidence: [ids]}]  — dropped without a valid
                                                     evidence reference
  likely_causes        [{text, likelihood, evidence}]
  missing_information  [text]
  suggested_checks     [{text}]                    — for a technician to do;
                                                     never executed
  warnings             [text]
  customer_replies     [{label, text}]             — drafts only

Unknown keys (an "actions" or "commands" list, say) are ignored. Every
string is sanitized, length-capped, run through the output filter and
redacted, so a ticket that tries to make the model emit a secret or markup
gets the item removed and a warning instead.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List

from .evidence import redact
from .guardrails import output_passes_filter

LIKELIHOODS = ('low', 'medium', 'high')
_LIMITS = {
    'observed_facts': 10, 'likely_causes': 5, 'missing_information': 8,
    'suggested_checks': 8, 'warnings': 8, 'customer_replies': 3,
}


class InvalidResult(Exception):
    pass


def _json_object(text: str) -> dict:
    text = (text or '').strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise InvalidResult('The model did not return a JSON object.')
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise InvalidResult(f'The model returned malformed JSON ({e.msg}).')
    if not isinstance(data, dict):
        raise InvalidResult('The model did not return a JSON object.')
    return data


def _clean(value, max_chars, notes) -> str:
    if not isinstance(value, str):
        return ''
    text = redact(value.strip(), max_chars=max_chars)
    ok, _ = output_passes_filter(text)
    if not ok:
        notes['filtered'] += 1
        return ''
    return text


def _refs(value, valid_ids) -> List[str]:
    if not isinstance(value, list):
        return []
    return [r for r in value if isinstance(r, str) and r in valid_ids][:6]


def parse(text: str, valid_ids: set) -> Dict:
    data = _json_object(text)
    notes = {'filtered': 0, 'unsupported_facts': 0}
    out = {k: [] for k in _LIMITS}

    for f in (data.get('observed_facts') or [])[:_LIMITS['observed_facts'] * 2]:
        if not isinstance(f, dict):
            continue
        t, refs = _clean(f.get('text'), 500, notes), _refs(f.get('evidence'), valid_ids)
        if t and refs:
            out['observed_facts'].append({'text': t, 'evidence': refs})
        elif t:
            notes['unsupported_facts'] += 1
    for c in data.get('likely_causes') or []:
        if not isinstance(c, dict):
            continue
        t = _clean(c.get('text'), 500, notes)
        if t:
            lk = str(c.get('likelihood') or '').lower()
            out['likely_causes'].append({'text': t, 'likelihood': lk if lk in LIKELIHOODS else 'low',
                                         'evidence': _refs(c.get('evidence'), valid_ids)})
    for key in ('missing_information', 'warnings'):
        for item in data.get(key) or []:
            t = _clean(item, 400, notes)
            if t:
                out[key].append(t)
    for s in data.get('suggested_checks') or []:
        t = _clean(s.get('text') if isinstance(s, dict) else s, 400, notes)
        if t:
            out['suggested_checks'].append({'text': t})
    for r in data.get('customer_replies') or []:
        if not isinstance(r, dict):
            continue
        t = _clean(r.get('text'), 3000, notes)
        if t:
            out['customer_replies'].append({'label': _clean(r.get('label'), 60, notes) or 'Reply',
                                            'text': t})

    for key, limit in _LIMITS.items():
        out[key] = out[key][:limit]
    if notes['filtered']:
        out['warnings'].append(f'{notes["filtered"]} item(s) removed by the safety filter.')
    if notes['unsupported_facts']:
        out['warnings'].append(f'{notes["unsupported_facts"]} statement(s) without evidence were not '
                               'listed as observed facts.')
    if not any(out[k] for k in ('observed_facts', 'likely_causes', 'suggested_checks', 'customer_replies')):
        raise InvalidResult('The model returned nothing usable.')
    return out


_STOP = set('a an the is are was be to of in on for and or with by at from it this that their its '
            'user users device issue problem likely may might could'.split())


def _words(text: str) -> set:
    return {w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in _STOP and len(w) > 2}


def disagreements(runs) -> List[dict]:
    """Where compared models differ: their top likely cause names different
    things (little word overlap), or they rate the same cause far apart."""
    tops = [(r.profile.name, r.result['likely_causes'][0]) for r in runs
            if r.status == 'succeeded' and r.result.get('likely_causes')]
    found = []
    for i in range(len(tops)):
        for j in range(i + 1, len(tops)):
            (na, a), (nb, b) = tops[i], tops[j]
            wa, wb = _words(a['text']), _words(b['text'])
            overlap = len(wa & wb) / max(1, len(wa | wb))
            if overlap < 0.25:
                found.append({'field': 'likely_causes', 'models': [na, nb],
                              'detail': f'{na} and {nb} name different most likely causes.'})
            elif {a['likelihood'], b['likelihood']} == {'low', 'high'}:
                found.append({'field': 'likely_causes', 'models': [na, nb],
                              'detail': f'{na} and {nb} rate the most likely cause very differently.'})
    return found
