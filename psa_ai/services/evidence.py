"""
The evidence a ticket analysis may see, exactly as it is sent.

The technician previews this before submitting, the job stores it, the
gateway builds the prompt from the stored copy only, and its SHA-256 digest
binds all three together (services/gateway.py).

Included: the ticket's subject and description, its public conversation, and
a summary of its asset with the status of each RMM that manages it. Asset and
RMM data come only from a verified association inside the ticket's own
customer (integrations.rmm_association.exposed_devices). Nothing is ever
matched by hostname here.

Never included: attachments, vault data, internal-note bodies, raw RMM
payloads, session or remote-access data. What was left out is counted, so
the preview can say so.

Every string is redacted before it leaves this module, so redacted text is
what gets transmitted, logged and stored.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Dict, List, Tuple

from .guardrails import sanitize_input

SCHEMA = 'ticket-rmm-v1/evidence'
MAX_COMMENTS = 20

_REDACTIONS: List[Tuple[str, re.Pattern, str]] = [
    ('private_key', re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)',
                               re.S), '[REDACTED PRIVATE KEY]'),
    ('secret', re.compile(r'\b(?:sk-ant-|sk-|rk_|ghp_|gho_|xox[abpr]-)[A-Za-z0-9_-]{16,}\b'), '[REDACTED KEY]'),
    ('secret', re.compile(r'\bAKIA[0-9A-Z]{16}\b'), '[REDACTED KEY]'),
    ('secret', re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{10,}\b'), '[REDACTED TOKEN]'),
    ('secret', re.compile(r'(?i)\b(authorization:\s*(?:bearer|basic))\s+\S+'), r'\1 [REDACTED]'),
    ('password', re.compile(r'(?i)\b(pass(?:word|wd|code)?|pwd|pin|secret|api[ _-]?key|token)\b(\s*(?:is|[:=])\s*)(\S+)'),
     r'\1\2[REDACTED]'),
    ('card', re.compile(r'\b(?:\d[ -]?){13,16}\b'), '[REDACTED NUMBER]'),
    ('email', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '[email]'),
    ('phone', re.compile(r'(?<![\w.])(?:\+?\d{1,3}[\s.-])?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w.])'), '[phone]'),
]


def redact(text: str, counts: Dict[str, int] | None = None, max_chars: int = 4000) -> str:
    """Sanitize and redact one string. `counts` collects what was removed."""
    text = sanitize_input(text or '', max_chars=max_chars)
    for kind, pattern, replacement in _REDACTIONS:
        text, n = pattern.subn(replacement, text)
        if n and counts is not None:
            counts[kind] = counts.get(kind, 0) + n
    return text


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def digest(data) -> str:
    return hashlib.sha256(canonical(data).encode('utf-8')).hexdigest()


def ticket_revision(ticket) -> str:
    """Changes whenever anything the evidence is built from changes."""
    last = ticket.comments.order_by('-pk').values_list('pk', flat=True).first()
    parts = [ticket.pk, ticket.organization_id, ticket.updated_at.isoformat() if ticket.updated_at else '',
             ticket.subject, ticket.description, ticket.status_id, ticket.priority_id,
             ticket.related_asset_id, last]
    return hashlib.sha256(canonical(parts).encode('utf-8')).hexdigest()


def _author_role(comment) -> str:
    from psa.visibility import is_msp_staff
    if comment.is_system:
        return 'system'
    return 'technician' if comment.author_id and is_msp_staff(comment.author) else 'customer'


def _asset_items(ticket, counts) -> Tuple[List[dict], dict]:
    """The ticket's asset and its verified RMM devices, summarised."""
    asset = ticket.related_asset
    if asset is None or asset.organization_id != ticket.organization_id:
        return [], {'linked': False}
    from integrations.rmm_association import summaries_for_asset
    items = [{
        'id': 'A1', 'kind': 'asset',
        'text': redact(f'Asset "{asset.name}" ({asset.asset_type or "asset"}); '
                       f'hostname {asset.hostname or "unknown"}', counts, 300),
    }]
    devices = []
    for n, s in enumerate(summaries_for_asset(asset), start=1):
        d = s['device']
        devices.append(d.pk)
        seen = d.last_seen.isoformat() if d.last_seen else 'never'
        items.append({
            'id': f'D{n}', 'kind': 'rmm_status',
            'text': redact(f'{s["provider"]} reports {d.device_name}: status {s["status"]["state"]}; '
                           f'last check-in {seen}; OS {d.os_type or "unknown"} {d.os_version or ""}'.strip(),
                           counts, 400),
        })
    return items, {'linked': True, 'asset_id': asset.pk, 'device_ids': devices}


def build_evidence(ticket) -> dict:
    """The evidence document for `ticket`. Deterministic for a given ticket
    revision, so a preview and the submit it leads to digest the same."""
    counts: Dict[str, int] = {}
    items: List[dict] = []
    items.append({'id': 'E1', 'kind': 'ticket.subject', 'role': 'customer',
                  'text': redact(ticket.subject, counts, 300)})
    if ticket.description:
        items.append({'id': 'E2', 'kind': 'ticket.description', 'role': 'customer',
                      'at': ticket.created_at.isoformat() if ticket.created_at else '',
                      'text': redact(ticket.description, counts, 4000)})

    comments = ticket.comments.select_related('author', 'author__profile').order_by('created_at', 'pk')
    internal = comments.filter(is_internal=True).count()
    public = list(comments.filter(is_internal=False, is_system=False))
    omitted_old = max(0, len(public) - MAX_COMMENTS)
    for n, c in enumerate(public[-MAX_COMMENTS:], start=1):
        items.append({'id': f'C{n}', 'kind': 'comment', 'role': _author_role(c),
                      'at': c.created_at.isoformat() if c.created_at else '',
                      'text': redact(c.body, counts, 1500)})

    asset_items, asset_info = _asset_items(ticket, counts)
    items.extend(asset_items)

    attachments = ticket.attachments.count() if hasattr(ticket, 'attachments') else 0
    return {
        'schema': SCHEMA,
        'ticket': {
            'ref': ticket.ticket_number,
            'status': ticket.status.name if ticket.status_id else '',
            'priority': ticket.priority.name if ticket.priority_id else '',
        },
        'items': items,
        'asset': asset_info,
        'excluded': {
            'internal_notes': internal,
            'attachments': attachments,
            'older_comments': omitted_old,
            'vault_data': 'never included',
            'raw_rmm_payloads': 'never included',
            'remote_session_data': 'never included',
        },
        'redactions': counts,
    }


def evidence_ids(evidence: dict) -> set:
    return {i['id'] for i in evidence.get('items') or []}


def prompt_text(evidence: dict) -> str:
    """The evidence as the model reads it: every item labelled with its ID."""
    lines = [f'Ticket {evidence["ticket"]["ref"]} — status {evidence["ticket"]["status"] or "unknown"}, '
             f'priority {evidence["ticket"]["priority"] or "unknown"}.']
    for item in evidence.get('items') or []:
        who = f' ({item["role"]})' if item.get('role') else ''
        when = f' {item["at"]}' if item.get('at') else ''
        lines.append(f'[{item["id"]}] {item["kind"]}{who}{when}: {item["text"]}')
    if not evidence.get('asset', {}).get('linked'):
        lines.append('No device is linked to this ticket. Work from the ticket alone.')
    return '\n'.join(lines)
