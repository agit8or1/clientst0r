"""Summaries of pulse check answers: response rate, averages, NPS, comments.

Questions are read from each send's snapshot, so a summary across several
sends groups answers by question text and kind.
"""
from __future__ import annotations

from .models import PulseQuestion


def nps(scores):
    """Net Promoter Score: % promoters (9-10) minus % detractors (0-6)."""
    scores = [s for s in scores if isinstance(s, int)]
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return round(100.0 * (promoters - detractors) / len(scores))


def _avg(values):
    return round(sum(values) / len(values), 2) if values else None


def summarize(responses):
    """Summary for an iterable of PulseResponse rows (send preloaded)."""
    responses = list(responses)
    total = len(responses)
    answered = [r for r in responses if r.responded_at]
    questions = {}   # (kind, text) -> stats
    order = []
    for r in responses:
        for q in r.send.questions:
            key = (q.get('kind'), q.get('text'))
            if key not in questions:
                questions[key] = {'kind': key[0], 'text': key[1], 'values': [], 'comments': []}
                order.append(key)
    for r in answered:
        for q in r.send.questions:
            key = (q.get('kind'), q.get('text'))
            value = (r.answers or {}).get(str(q.get('id')))
            if value in (None, ''):
                continue
            if key[0] == PulseQuestion.KIND_TEXT:
                questions[key]['comments'].append({'text': value, 'response': r})
            else:
                questions[key]['values'].append(value)
    rows = []
    for key in order:
        q = questions[key]
        vals = q['values']
        row = {'kind': q['kind'], 'text': q['text'], 'count': len(vals) or len(q['comments']),
               'comments': q['comments']}
        if q['kind'] in (PulseQuestion.KIND_RATING, PulseQuestion.KIND_NPS):
            nums = [v for v in vals if isinstance(v, int)]
            row['average'] = _avg(nums)
            if q['kind'] == PulseQuestion.KIND_NPS:
                row['nps'] = nps(nums)
        elif q['kind'] == PulseQuestion.KIND_YES_NO:
            yes = sum(1 for v in vals if v is True)
            row['yes'] = yes
            row['no'] = len(vals) - yes
            row['yes_pct'] = round(100.0 * yes / len(vals)) if vals else None
        rows.append(row)
    rating_values = [v for k in order if k[0] == PulseQuestion.KIND_RATING
                     for v in questions[k]['values'] if isinstance(v, int)]
    nps_values = [v for k in order if k[0] == PulseQuestion.KIND_NPS
                  for v in questions[k]['values'] if isinstance(v, int)]
    return {
        'total': total,
        'answered': len(answered),
        'rate': round(100.0 * len(answered) / total) if total else None,
        'average_rating': _avg(rating_values),
        'nps': nps(nps_values),
        'questions': rows,
    }


def parse_answers(questions, data):
    """Validate posted answers against a send's question snapshot.

    Returns ``(answers, errors)``; answers are keyed by question id (str):
    rating -> int 1-5, nps -> int 0-10, yes_no -> bool, text -> str.
    """
    answers, errors = {}, []
    for q in questions:
        qid = str(q.get('id'))
        raw = (data.get(f'q_{qid}') or '').strip()
        kind = q.get('kind')
        if raw == '':
            if q.get('required'):
                errors.append(f'Please answer: {q.get("text")}')
            continue
        if kind in (PulseQuestion.KIND_RATING, PulseQuestion.KIND_NPS):
            lo, hi = (1, 5) if kind == PulseQuestion.KIND_RATING else (0, 10)
            try:
                n = int(raw)
            except ValueError:
                n = None
            if n is None or not lo <= n <= hi:
                errors.append(f'Pick a number from {lo} to {hi}: {q.get("text")}')
                continue
            answers[qid] = n
        elif kind == PulseQuestion.KIND_YES_NO:
            if raw not in ('yes', 'no'):
                errors.append(f'Pick yes or no: {q.get("text")}')
                continue
            answers[qid] = raw == 'yes'
        else:
            answers[qid] = raw[:4000]
    return answers, errors
