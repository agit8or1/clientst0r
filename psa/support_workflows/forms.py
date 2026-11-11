"""The structured support workflow editor: definition dict <-> form rows.

The editor saves exactly the JSON format builtins.py documents, and the
result goes through engine.validate_definition like the JSON view's does.
No JavaScript is needed: the page renders every existing row plus a few
blank ones, and "More rows" re-renders with extra blanks without saving.

Conditions: "always" ({}), "all of" / "any of" one level of
{fact, op, value} rules — what every built-in uses. Anything deeper is kept
as JSON in the condition's own field ("Advanced (JSON)"), so nothing an
administrator wrote in the JSON view is lost by the form.
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

EXTRA_CAUSES = 2
EXTRA_REMEDIATIONS = 1
EXTRA_RULES = 1
MAX_ROWS = 40
MAX_RULES = 20
VALUE_OPS = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in'}
MANAGED_KEYS = ('name', 'description', 'categories', 'freshness_minutes', 'evidence', 'causes', 'remediations',
                'manual_steps', 'verify_within_minutes', 'requires_integration')


# --- definition -> rows --------------------------------------------------------

def _value_text(value) -> str:
    """How a rule's value is shown: plain text for a string that wouldn't
    read back as something else, JSON otherwise (numbers, lists, booleans)."""
    if value is None:
        return ''
    if isinstance(value, str):
        try:
            json.loads(value)
        except ValueError:
            return value
    return json.dumps(value)


def _simple_rule(c) -> bool:
    return isinstance(c, dict) and 'all' not in c and 'any' not in c and set(c) <= {'fact', 'op', 'value'}


def condition_rows(cond, extra=EXTRA_RULES) -> dict:
    """{mode, rules: [{fact, op, value}], json} for one condition."""
    blank = [{'fact': '', 'op': '', 'value': ''} for _ in range(extra)]
    if not cond:
        return {'mode': 'always', 'rules': blank, 'json': ''}
    if _simple_rule(cond):
        items, mode = [cond], 'all'
    elif (isinstance(cond, dict) and len(cond) == 1 and isinstance(cond.get('all', cond.get('any')), list)
          and all(_simple_rule(c) for c in cond.get('all', cond.get('any')))):
        mode = 'all' if 'all' in cond else 'any'
        items = cond[mode]
    else:
        return {'mode': 'json', 'rules': blank, 'json': json.dumps(cond, indent=1)}
    rules = [{'fact': c.get('fact', ''), 'op': c.get('op', ''), 'value': _value_text(c.get('value'))}
             for c in items]
    return {'mode': mode, 'rules': rules + blank, 'json': ''}


def to_rows(d: dict, more: int = 0) -> dict:
    """The editor's context for definition `d` (blank rows added; `more`
    adds that many extra blank causes/remediations/rules)."""
    d = d or {}
    causes = [dict(text=c.get('text', ''), when=condition_rows(c.get('when'), EXTRA_RULES + more))
              for c in d.get('causes') or [] if isinstance(c, dict)]
    causes += [dict(text='', when=condition_rows({}, EXTRA_RULES + more)) for _ in range(EXTRA_CAUSES + more)]
    rems = [dict(action=r.get('action', ''), impact=r.get('impact', ''),
                 when=condition_rows(r.get('when'), EXTRA_RULES + more))
            for r in d.get('remediations') or [] if isinstance(r, dict)]
    rems += [dict(action='', impact='', when=condition_rows({}, EXTRA_RULES + more))
             for _ in range(EXTRA_REMEDIATIONS + more)]
    return {
        'name': d.get('name', ''), 'description': d.get('description', ''),
        'categories': list(d.get('categories') or []), 'evidence': list(d.get('evidence') or []),
        'freshness_minutes': d.get('freshness_minutes', 30), 'verify_within_minutes': d.get('verify_within_minutes', 60),
        'requires_integration': d.get('requires_integration') or '',
        'manual_steps': '\n'.join(s for s in d.get('manual_steps') or [] if isinstance(s, str)),
        'causes': causes[:MAX_ROWS], 'remediations': rems[:MAX_ROWS],
    }


# --- post -> definition --------------------------------------------------------

def _int(text, label, errors) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        errors.append(f'{label} must be a whole number of minutes')
        return None


def _parse_value(text, op):
    text = (text or '').strip()
    if op not in VALUE_OPS:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = text
    if op == 'in' and isinstance(value, str):
        value = [v.strip() for v in value.split(',') if v.strip()]
    return value


def condition_from_post(post, prefix, where, errors):
    mode = post.get(f'{prefix}-mode') or 'always'
    if mode == 'always':
        return {}
    if mode == 'json':
        text = (post.get(f'{prefix}-json') or '').strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError as e:
            errors.append(f'{where}: the advanced condition is not valid JSON ({e})')
            return {}
    if mode not in ('all', 'any'):
        errors.append(f'{where}: unknown condition mode')
        return {}
    rules = []
    for i in range(MAX_RULES):
        fact = (post.get(f'{prefix}-r{i}-fact') or '').strip()
        op = (post.get(f'{prefix}-r{i}-op') or '').strip()
        if not fact and not op:
            continue
        rule = {'fact': fact, 'op': op}
        if op in VALUE_OPS:
            rule['value'] = _parse_value(post.get(f'{prefix}-r{i}-value'), op)
        rules.append(rule)
    if not rules:
        return {}
    if len(rules) == 1 and mode == 'all':
        return rules[0]
    return {mode: rules}


def from_post(post, base: Optional[dict] = None) -> Tuple[dict, List[str]]:
    """(definition, form errors) from the structured editor's POST. Keys the
    form doesn't manage are kept from `base`. Run validate_definition on the
    result as well — this only reports what the form itself can't read."""
    errors: List[str] = []
    d = {k: v for k, v in (base or {}).items() if k not in MANAGED_KEYS and k != 'slug'}
    d['name'] = (post.get('name') or '').strip()
    d['description'] = (post.get('description') or '').strip()[:300]
    d['categories'] = [c for c in post.getlist('categories') if c]
    d['evidence'] = [e for e in post.getlist('evidence') if e]
    d['freshness_minutes'] = _int(post.get('freshness_minutes'), 'freshness_minutes', errors)
    d['verify_within_minutes'] = _int(post.get('verify_within_minutes'), 'verify_within_minutes', errors)
    req = (post.get('requires_integration') or '').strip()
    if req:
        d['requires_integration'] = req
    d['manual_steps'] = [line.strip() for line in (post.get('manual_steps') or '').splitlines() if line.strip()]
    causes = []
    for i in range(MAX_ROWS):
        text = (post.get(f'cause{i}-text') or '').strip()
        if not text or post.get(f'cause{i}-delete'):
            continue
        causes.append({'text': text, 'when': condition_from_post(post, f'cause{i}', f'causes[{len(causes)}]', errors)})
    d['causes'] = causes
    rems = []
    for i in range(MAX_ROWS):
        action = (post.get(f'rem{i}-action') or '').strip()
        if not action or post.get(f'rem{i}-delete'):
            continue
        r = {'action': action, 'when': condition_from_post(post, f'rem{i}', f'remediations[{len(rems)}]', errors)}
        impact = (post.get(f'rem{i}-impact') or '').strip()
        if impact:
            r['impact'] = impact[:300]
        rems.append(r)
    d['remediations'] = rems
    return d, errors
