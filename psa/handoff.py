"""Technician handoff summary (roadmap 52.22), non-AI part.

``build_handoff(ticket, user)`` returns a plain dict built only from data
already on the ticket: status, priority, assignee, age, SLA state, the last
few actions, open checklist items and the devices the ticket is about.
``render_text(summary)`` turns it into compact plain text for pasting into a
shift-change message. The dict is the input an optional AI wording can use
later; nothing here calls an AI.

Technicians only: it includes internal notes, so ``build_handoff`` returns
None for anyone who is not MSP staff. It never reads vault entries or any
secret field; devices are listed by name, type and hostname only.
"""
from __future__ import annotations

from django.utils import timezone

MAX_ACTIONS = 8
MAX_ITEMS = 25
SNIPPET = 160


def _name(user, fallback=''):
    if user is None:
        return fallback or ''
    return user.get_full_name() or user.get_username()


def _snippet(text):
    text = ' '.join((text or '').split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + '…'


def _age(delta):
    mins = int(max(0, delta.total_seconds()) // 60)
    days, rem = divmod(mins, 1440)
    hours = rem // 60
    if days:
        return f'{days}d {hours}h'
    if hours:
        return f'{hours}h {rem % 60}m'
    return f'{mins}m'


def _actions(ticket, limit):
    rows = []
    for c in ticket.comments.select_related('author').order_by('-created_at', '-pk')[:limit]:
        if c.is_system:
            kind = 'update'
        elif c.is_internal:
            kind = 'internal note'
        else:
            kind = 'reply'
        rows.append({'at': c.created_at, 'kind': kind, 'by': _name(c.author, c.author_name),
                     'text': _snippet(c.body)})
    for t in ticket.time_entries.select_related('user').order_by('-started_at', '-pk')[:limit]:
        mins = t.duration_minutes
        text = f'{mins} min' + (f': {_snippet(t.notes)}' if t.notes else '')
        rows.append({'at': t.ended_at or t.started_at, 'kind': 'time entry', 'by': _name(t.user), 'text': text})
    rows.sort(key=lambda r: r['at'], reverse=True)
    return rows[:limit]


def build_handoff(ticket, user, now=None):
    from .visibility import is_msp_staff
    if user is None or not is_msp_staff(user):
        return None
    from .affected import ticket_assets
    from .sla import status_chip
    now = now or timezone.now()
    sla = status_chip(ticket, now=now)
    open_items = [{'label': i.label, 'required': i.is_required}
                  for i in ticket.checklist_items.filter(is_completed=False)[:MAX_ITEMS]]
    devices = [{'name': a.name, 'type': getattr(a, 'asset_type', '') or '',
                'hostname': getattr(a, 'hostname', '') or ''}
               for a in ticket_assets(ticket)[:MAX_ITEMS]]
    return {
        'number': ticket.ticket_number,
        'subject': ticket.subject,
        'customer': ticket.organization.name,
        'status': ticket.status.name if ticket.status_id else '',
        'priority': ticket.priority.name if ticket.priority_id else '',
        'assignee': _name(ticket.assigned_to) or 'Unassigned',
        'age': _age(now - ticket.created_at),
        'sla': sla.get('label', ''),
        'actions': _actions(ticket, MAX_ACTIONS),
        'open_items': open_items,
        'devices': devices,
    }


def render_text(s):
    lines = [f"Handoff: {s['number']} {s['subject']}",
             f"Customer: {s['customer']}",
             f"Status: {s['status']} | Priority: {s['priority']} | Assigned to: {s['assignee']}",
             f"Age: {s['age']} | SLA: {s['sla']}"]
    lines.append('Last actions:')
    if s['actions']:
        for a in s['actions']:
            who = f" by {a['by']}" if a['by'] else ''
            lines.append(f"- {a['at']:%Y-%m-%d %H:%M} {a['kind']}{who}: {a['text']}")
    else:
        lines.append('- none yet')
    lines.append('Open tasks:')
    if s['open_items']:
        for i in s['open_items']:
            lines.append(f"- [ ] {i['label']}" + ('' if i['required'] else ' (optional)'))
    else:
        lines.append('- none')
    lines.append('Devices:')
    if s['devices']:
        for d in s['devices']:
            extra = ' / '.join(x for x in (d['type'], d['hostname']) if x)
            lines.append(f"- {d['name']}" + (f' ({extra})' if extra else ''))
    else:
        lines.append('- none')
    return '\n'.join(lines)
