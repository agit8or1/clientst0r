"""Support workflows: evidence → likely causes → an advertised, approved
remediation → outcome confirmed by monitoring.

Guarantees:

  * Evidence is read-only: ClientSt0r's own records (the alert, the synced
    device), and — when the technician holds "read-only diagnostics" for the
    customer — Rem0te's current alert state (GET /alerts/{id}, a
    service-level read that changes nothing) and the RMM's own read-only
    diagnostics through the existing request flow. Every item carries when it
    was observed and whether that is fresh.
  * Causes are rules over those facts (builtins.py), not AI.
  * A remediation is offered only when it is a Rem0te catalog action that
    ClientSt0r knows (pairing.KNOWN_ACTIONS) AND the paired Rem0te currently
    advertises it AND the ticket reaches the computer through a verified,
    same-customer link AND the technician may refer fixes there. It is sent
    through psa_ai.services.rmm_actions.refer_fix — the existing fix
    referral: Rem0te answers "awaiting approval" and its approvers approve on
    Rem0te's signer. Nothing here approves, dispatches or runs anything.
  * The outcome is confirmed only by monitoring: the alert recovering
    (psa.routing.alert_policy.alert_recovered) within the workflow's window.
    Rem0te saying the job succeeded is recorded, not taken as the fix.
  * Notes are staff-only. No customer message, no ticket closure.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from .builtins import BUILTINS
from .models import SupportWorkflowDefinition, WorkflowRun

logger = logging.getLogger('psa.support_workflows')

EVIDENCE = {
    'alert': 'The alert as monitoring reported it',
    'alert_now': "The alert's current state, read from Rem0te",
    'device_status': 'Device status from the RMM sync',
    'device_inventory': 'Device inventory from the RMM sync',
    'disk': 'Disk free space',
    'metric': 'Reported utilisation',
    'patch': 'Patch summary from Rem0te',
    'site_peers': 'Other computers at the same site',
    'repeat_history': 'This issue on this computer in the last 30 days',
}
OPS = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'truthy', 'falsy', 'missing'}
FACTS = {'category', 'severity', 'occurrences', 'alert_state', 'device_online', 'evidence_stale',
         'site_offline_count', 'repeat_count_30d', 'service_name', 'disk_free_pct', 'disk_free_gb',
         'metric_pct', 'reboot_required', 'pending_updates', 'failed_updates', 'patch_freshness',
         'device_type', 'os_type'}
CATEGORIES = {'offline', 'disk', 'service', 'windows_update', 'cpu', 'memory', 'reboot_pending', 'application',
              'network', 'unresponsive_app', 'security', 'backup', 'site_outage', 'other'}
MAX_TEXT = 600
# Run states from which a (new) action may be proposed / manual steps recorded.
PROPOSABLE_FROM = {'ready', 'rejected', 'failed', 'approval_expired', 'unavailable', 'not_verified'}
MANUAL_FROM = PROPOSABLE_FROM | {'manual'}
INVENTORY_KEY = re.compile(r'(disk|storage|volume|drive|cpu|processor|memory|ram|uptime|boot|antivirus|backup)', re.I)


class WorkflowRefused(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message, self.status = message, status


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

def _cond_errors(cond, where) -> List[str]:
    if cond in (None, {}):
        return []
    if not isinstance(cond, dict):
        return [f'{where}: a condition must be an object']
    if 'all' in cond or 'any' in cond:
        items = cond.get('all', cond.get('any'))
        if not isinstance(items, list) or len(cond) != 1:
            return [f'{where}: "all"/"any" takes a list and nothing else']
        out = []
        for i, c in enumerate(items[:20]):
            out += _cond_errors(c, f'{where}[{i}]')
        return out
    out = []
    if cond.get('fact') not in FACTS:
        out.append(f'{where}: unknown fact "{cond.get("fact")}"')
    if cond.get('op') not in OPS:
        out.append(f'{where}: unknown op "{cond.get("op")}"')
    if set(cond) - {'fact', 'op', 'value'}:
        out.append(f'{where}: unexpected keys {sorted(set(cond) - {"fact", "op", "value"})}')
    return out


def validate_definition(d) -> List[str]:
    """Plain-language problems with a definition; empty = usable. A
    remediation may name only an action ClientSt0r knows from Rem0te's
    catalog — never a command, script or URL."""
    from integrations.rem0te.pairing import KNOWN_ACTIONS
    if not isinstance(d, dict):
        return ['The definition must be a JSON object.']
    out = []
    if not str(d.get('name') or '').strip():
        out.append('name is required')
    cats = d.get('categories')
    if not isinstance(cats, list) or not cats or set(cats) - CATEGORIES:
        out.append(f'categories must be a non-empty list from {sorted(CATEGORIES)}')
    ev = d.get('evidence') or []
    if not isinstance(ev, list) or set(ev) - set(EVIDENCE):
        out.append(f'evidence must be a list from {sorted(EVIDENCE)}')
    for key in ('freshness_minutes', 'verify_within_minutes'):
        v = d.get(key)
        if not isinstance(v, int) or not 1 <= v <= 14 * 24 * 60:
            out.append(f'{key} must be minutes between 1 and 20160')
    for i, c in enumerate(d.get('causes') or []):
        if not isinstance(c, dict) or not str(c.get('text') or '').strip():
            out.append(f'causes[{i}]: needs text')
            continue
        out += _cond_errors(c.get('when'), f'causes[{i}].when')
    for i, r in enumerate(d.get('remediations') or []):
        if not isinstance(r, dict) or r.get('action') not in KNOWN_ACTIONS:
            out.append(f'remediations[{i}]: action must be one of {sorted(KNOWN_ACTIONS)}')
            continue
        if set(r) - {'action', 'when', 'impact'}:
            out.append(f'remediations[{i}]: only action, when and impact are allowed')
        out += _cond_errors(r.get('when'), f'remediations[{i}].when')
    steps = d.get('manual_steps') or []
    if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
        out.append('manual_steps must be a list of text')
    if d.get('requires_integration') not in (None, '', 'backup'):
        out.append('requires_integration may only be "backup"')
    for text in [str(c.get('text', '')) for c in d.get('causes') or [] if isinstance(c, dict)] + \
            [str(s) for s in steps if isinstance(s, str)]:
        if len(text) > MAX_TEXT:
            out.append(f'texts are limited to {MAX_TEXT} characters')
            break
    return out


def builtin(slug) -> Optional[dict]:
    return next((dict(b) for b in BUILTINS if b['slug'] == slug), None)


def definitions(include_inactive=False) -> List[dict]:
    """Built-ins, each replaced by an administrator's copy with the same
    slug, plus administrators' own workflows. Invalid copies are skipped."""
    rows = {r.slug: r for r in SupportWorkflowDefinition.objects.all()}
    out = []
    for b in BUILTINS:
        row = rows.pop(b['slug'], None)
        if row is None:
            out.append(dict(b, builtin=True, customised=False, is_active=True))
        elif (row.is_active or include_inactive) and not validate_definition(row.definition):
            out.append(dict(row.definition, slug=row.slug, builtin=True, customised=True, is_active=row.is_active))
    for row in rows.values():
        if (row.is_active or include_inactive) and not validate_definition(row.definition):
            out.append(dict(row.definition, slug=row.slug, builtin=False, customised=True, is_active=row.is_active))
    return sorted(out, key=lambda d: d['name'].lower())


def definition(slug) -> Optional[dict]:
    return next((d for d in definitions() if d['slug'] == slug), None)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def can_view(user, ticket) -> bool:
    from accounts.permission_utils import has_perm_for_org
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user) and has_perm_for_org(user, ticket.organization, 'tickets_view'))


def can_run(user, ticket) -> bool:
    from accounts.permission_utils import has_perm_for_org
    return can_view(user, ticket) and has_perm_for_org(user, ticket.organization, 'tickets_edit')


def _may_read_device(user, ticket) -> bool:
    from tech_access.resolver import decide
    return decide(user, ticket.organization, 'diagnostics_readonly', ticket=ticket,
                  asset=ticket.related_asset).allowed


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def _age_minutes(when, now):
    if when is None:
        return None
    return max(0, int((now - when).total_seconds() // 60))


def _item(key, label, value, observed_at, now, freshness, source):
    age = _age_minutes(observed_at, now)
    return {'key': key, 'label': label, 'value': value, 'source': source,
            'observed_at': observed_at.isoformat() if observed_at else '',
            'age_minutes': age, 'fresh': (age is not None and age <= freshness)}


_PCT = re.compile(r'(\d{1,3}(?:\.\d+)?)\s*%')
_SIZE = re.compile(r'(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b', re.I)


def _metrics_from_text(text, category):
    """Numbers an alert title carries (e.g. 'C: 4% free (3.2 GB)')."""
    out = {}
    t = text or ''
    pct = _PCT.search(t)
    if pct:
        value = float(pct.group(1))
        if category == 'disk':
            # "92% used" vs "8% free"
            out['disk_free_pct'] = 100 - value if re.search(r'used|full', t, re.I) and 'free' not in t.lower() else value
        else:
            out['metric_pct'] = value
    size = _SIZE.search(t)
    if size and category == 'disk':
        n, unit = float(size.group(1)), size.group(2).upper()
        out['disk_free_gb'] = n * 1024 if unit == 'TB' else (n / 1024 if unit == 'MB' else n)
    return out


def _rem0te_alert_now(link):
    """Rem0te's current state of the alert (read only). (dict or None, note)."""
    from integrations.rem0te import client, pairing, schema
    conn = link.connection
    if conn.provider_type != 'rem0te' or not pairing.is_processor(conn):
        return None, 'Rem0te is not paired for this customer.'
    try:
        r = client.request(conn, 'GET', f'/alerts/{link.external_id}',
                           query={'organization_id': pairing.organization_id(conn)})
    except client.NotSent as e:
        return None, f'Not read: {e.message}'
    if not r.ok or not isinstance(r.data, dict):
        return None, f'Rem0te did not return the alert ({r.code or r.status}).'
    if schema.errors('alert', r.data) or r.data.get('alert_id') != link.external_id:
        return None, 'Rem0te answered with something that is not this alert; ignored.'
    return r.data, ''


def gather(run, user, ticket, link, now=None):
    """(evidence items, facts). Read only."""
    from integrations.rem0te.client import safe_text
    from psa.routing.models import AlertTicketLink
    now = now or timezone.now()
    d = run.definition
    fresh = int(d.get('freshness_minutes') or 30)
    wanted = list(d.get('evidence') or [])
    items, facts = [], {}
    device = link.device if link is not None else None
    if device is None and ticket.related_asset_id:
        device = run.device
    facts['category'] = link.category if link else (d.get('categories') or ['other'])[0]
    facts['device_type'] = getattr(device, 'device_type', '') or ''
    facts['os_type'] = getattr(device, 'os_type', '') or ''

    if link is not None:
        from psa.routing.alert_policy import service_name
        facts.update(severity=link.severity, occurrences=link.occurrences, alert_state=link.state,
                     service_name=service_name(link.title))
        if 'alert' in wanted:
            items.append(_item('alert', EVIDENCE['alert'], {
                'title': link.title, 'severity': link.severity, 'state': link.state,
                'occurrences': link.occurrences, 'first_seen': link.first_seen_at.isoformat()
                if link.first_seen_at else ''}, link.last_seen_at or link.updated_at, now, fresh,
                f'{link.get_source_display()} ({link.connection.name})'))
        nums = _metrics_from_text(link.title, link.category)
        facts.update(nums)
        if 'disk' in wanted and link.category == 'disk':
            value = {k: round(v, 1) for k, v in nums.items()} or {'note': 'The alert did not carry a number.'}
            items.append(_item('disk', EVIDENCE['disk'], value, link.last_seen_at, now, fresh, 'the alert'))
        if 'metric' in wanted and 'metric_pct' in nums:
            items.append(_item('metric', EVIDENCE['metric'], {'percent': nums['metric_pct']}, link.last_seen_at,
                               now, fresh, 'the alert'))
        patch = (link.evidence or {}).get('patch_summary')
        if isinstance(patch, dict):
            facts.update(reboot_required=patch.get('reboot_required'),
                         pending_updates=patch.get('pending_count'),
                         failed_updates=len(patch.get('failed_kbs') or []),
                         patch_freshness=patch.get('freshness'))
            if 'patch' in wanted:
                when = None
                try:
                    from django.utils.dateparse import parse_datetime
                    when = parse_datetime(str(patch.get('evidence_at') or '').replace('Z', '+00:00'))
                except (TypeError, ValueError):
                    pass
                items.append(_item('patch', EVIDENCE['patch'], patch, when, now, fresh, 'Rem0te (with the alert)'))
        if 'alert_now' in wanted and link.source == AlertTicketLink.SOURCE_REM0TE:
            if _may_read_device(user, ticket):
                data, why = _rem0te_alert_now(link)
                if data is not None:
                    from psa.routing.alert_policy import _dt
                    items.append(_item('alert_now', EVIDENCE['alert_now'], {
                        'state': data.get('state'), 'severity': data.get('severity'),
                        'title': safe_text(data.get('title') or '', 300), 'occurrences': data.get('occurrences'),
                        'last_seen': data.get('last_seen_at')}, _dt(data.get('last_seen_at')) or now, now, fresh,
                        'Rem0te, read just now'))
                    facts['alert_state_rem0te'] = data.get('state')
                    nums_now = _metrics_from_text(data.get('title') or '', link.category)
                    facts.update(nums_now)
                else:
                    items.append({'key': 'alert_now', 'label': EVIDENCE['alert_now'], 'value': {'note': why},
                                  'source': 'Rem0te', 'observed_at': '', 'age_minutes': None, 'fresh': False})
            else:
                items.append({'key': 'alert_now', 'label': EVIDENCE['alert_now'],
                              'value': {'note': 'Not read: you do not hold read-only diagnostics for this customer.'},
                              'source': 'Rem0te', 'observed_at': '', 'age_minutes': None, 'fresh': False})
        if 'site_peers' in wanted and link.site_key:
            since = now - timedelta(hours=2)
            n = (AlertTicketLink.objects.filter(organization_id=link.organization_id, site_key=link.site_key,
                                                category='offline', created_at__gte=since)
                 .exclude(state='resolved').exclude(pk=link.pk).values('issue_key').distinct().count())
            facts['site_offline_count'] = n
            items.append(_item('site_peers', EVIDENCE['site_peers'], {'site': link.site_name,
                                                                       'other_computers_offline': n},
                               now, now, fresh, 'alert policy records'))
        if 'repeat_history' in wanted:
            n = (AlertTicketLink.objects.filter(organization_id=link.organization_id, issue_key=link.issue_key,
                                                created_at__gte=now - timedelta(days=30))
                 .exclude(pk=link.pk).count())
            facts['repeat_count_30d'] = n
            items.append(_item('repeat_history', EVIDENCE['repeat_history'], {'earlier_alerts': n}, now, now,
                               fresh, 'alert policy records'))
    if device is not None:
        if 'device_status' in wanted:
            facts['device_online'] = bool(device.is_online)
            items.append(_item('device_status', EVIDENCE['device_status'], {
                'online': device.is_online, 'last_seen': device.last_seen.isoformat() if device.last_seen else '',
                'site': device.site_name, 'os': f'{device.get_os_type_display()} {device.os_version}'.strip()},
                device.data_refreshed_at or device.last_synced_at, now, fresh, device.connection.name))
        if 'device_inventory' in wanted:
            raw = device.raw_data if isinstance(device.raw_data, dict) else {}
            inv = {}
            for k, v in list(raw.items())[:200]:
                if INVENTORY_KEY.search(str(k)) and isinstance(v, (str, int, float, bool)):
                    inv[safe_text(k, 40)] = safe_text(v, 80) if isinstance(v, str) else v
                if len(inv) >= 12:
                    break
            if inv:
                items.append(_item('device_inventory', EVIDENCE['device_inventory'], inv,
                                   device.data_refreshed_at, now, fresh, device.connection.name))
    facts['evidence_stale'] = any(not i['fresh'] for i in items if i.get('observed_at'))
    return items, facts


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def holds(cond, facts) -> bool:
    if not cond:
        return True
    if 'all' in cond:
        return all(holds(c, facts) for c in cond['all'])
    if 'any' in cond:
        return any(holds(c, facts) for c in cond['any'])
    op, value = cond.get('op'), cond.get('value')
    have = facts.get(cond.get('fact'))
    if op == 'missing':
        return have is None
    if op == 'truthy':
        return bool(have)
    if op == 'falsy':
        return not have
    if have is None:
        return False
    try:
        if op == 'eq':
            return str(have).lower() == str(value).lower() if isinstance(have, str) else have == value
        if op == 'ne':
            return have != value
        if op == 'in':
            return have in (value or [])
        have_n, value_n = float(have), float(value)
    except (TypeError, ValueError):
        return False
    return {'gt': have_n > value_n, 'gte': have_n >= value_n, 'lt': have_n < value_n,
            'lte': have_n <= value_n}.get(op, False)


def likely_causes(d, facts):
    return [{'text': c['text']} for c in d.get('causes') or [] if holds(c.get('when'), facts)]


def _target(ticket, device):
    from psa_ai.services import rmm_actions
    if device is None:
        return None
    return next((t for t in rmm_actions.targets(ticket) if t.device.pk == device.pk), None)


def remediations(d, facts, user, ticket, device):
    """Every remediation in the definition, each with whether it is offered
    now and, when not, why."""
    from integrations.rem0te import pairing
    from psa_ai.services import rmm_actions
    target = _target(ticket, device)
    out = []
    for r in d.get('remediations') or []:
        key = r.get('action')
        known = pairing.KNOWN_ACTIONS.get(key)
        row = {'action': key, 'label': known['label'] if known else key, 'risk': known.get('risk', 'high')
               if known else 'high', 'impact': r.get('impact') or '', 'offered': False, 'why_not': ''}
        if known is None:
            row['why_not'] = 'ClientSt0r does not know this action.'
        elif target is None:
            row['why_not'] = 'The ticket does not reach this computer through a paired Rem0te of this customer.'
        elif target.connection.provider_type != 'rem0te':
            row['why_not'] = f'{target.connection.name} takes fix referrals, not Rem0te catalog actions.'
        elif key not in {a['key'] for a in pairing.proposable_actions(target.connection)} \
                or not pairing.is_processor(target.connection):
            row['why_not'] = f'{target.connection.name} does not advertise this action.'
        elif not holds(r.get('when'), facts):
            row['why_not'] = 'Does not fit this alert (for example a different service).'
        else:
            ok, reason, _ = rmm_actions.action_state(user, ticket, target,
                                                     'fix_high' if row['risk'] == 'high' else 'fix_low')
            row['offered'], row['why_not'] = ok, ('' if ok else reason)
        out.append(row)
    return out


def read_only_diagnostics(user, ticket, device) -> List[dict]:
    """The RMM's own advertised read-only diagnostics (HMAC providers)."""
    from psa_ai.services import rmm_actions
    target = _target(ticket, device)
    if target is None:
        return []
    ok, _reason, _ = rmm_actions.action_state(user, ticket, target, 'diagnostic')
    if not ok:
        return []
    return [{'key': x['key'], 'label': x['label']} for x in rmm_actions.diagnostics_for(target)][:20]


# ---------------------------------------------------------------------------
# Availability on a ticket
# ---------------------------------------------------------------------------

def _backup_integration(ticket) -> bool:
    """A connected integration that can report backup jobs: a paired RMM
    advertising a read-only backup diagnostic for this ticket's device."""
    from psa_ai.services import rmm_actions
    for t in rmm_actions.targets(ticket):
        if any('backup' in (x.get('key', '') + x.get('label', '')).lower() for x in rmm_actions.diagnostics_for(t)):
            return True
    return False


def for_ticket(ticket):
    """[(definition, alert link or None, available, why_not)] for the ticket:
    workflows matching its alerts first, then the rest."""
    from psa.routing.alert_policy import links_for_ticket
    links = [l for l in links_for_ticket(ticket) if l.ticket_id == ticket.pk]
    out, seen = [], set()
    for link in links:
        for d in definitions():
            if link.category in d['categories'] and d['slug'] not in seen:
                seen.add(d['slug'])
                out.append(_avail(d, link, ticket))
    for d in definitions():
        if d['slug'] not in seen:
            out.append(_avail(d, None, ticket))
    return out


def _avail(d, link, ticket):
    if d.get('requires_integration') == 'backup' and not _backup_integration(ticket):
        return d, link, False, 'No connected integration reports backup jobs for this device.'
    return d, link, True, ''


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def _log(run, text):
    run.history = (run.history or []) + [{'at': timezone.now().isoformat(), 'text': text[:500]}]


def _note(ticket, body, author=None):
    from psa.routing.alert_policy import note
    return note(ticket, body, author=author)


def _audit(user, run, text, request=None):
    from audit.models import AuditLog
    AuditLog.log(user=user, action='update', organization=run.organization, object_type='support_workflows.WorkflowRun',
                 object_repr=f'{run.workflow_name} on {run.ticket.ticket_number}'[:255], description=text[:1000],
                 path=request.path if request is not None else '',
                 extra_data={'run': str(run.pk), 'ticket': run.ticket_id})


def start(user, ticket, slug, link_id=None, request=None) -> WorkflowRun:
    """Gather evidence and work out causes and remediations. Read only on
    the computer's side; records the run and a staff note."""
    from psa.routing.models import AlertTicketLink
    if not can_run(user, ticket):
        raise WorkflowRefused('You may not work on this ticket.')
    d = definition(slug)
    if d is None:
        raise WorkflowRefused('No such workflow.', 404)
    link = None
    if link_id:
        link = AlertTicketLink.objects.filter(pk=link_id, ticket=ticket).select_related('connection', 'device').first()
        if link is None:
            raise WorkflowRefused('That alert is not on this ticket.', 404)
    else:
        link = (AlertTicketLink.objects.filter(ticket=ticket, category__in=d['categories'])
                .select_related('connection', 'device').order_by('-created_at').first())
    _d, _l, ok, why = _avail(d, link, ticket)
    if not ok:
        raise WorkflowRefused(why, 400)
    device = link.device if link is not None and link.device and link.device.organization_id == ticket.organization_id \
        else None
    if device is None:
        t = next(iter(_targets_safe(ticket)), None)
        device = t.device if t is not None else None
    run = WorkflowRun(organization=ticket.organization, ticket=ticket, alert_link=link, device=device,
                      workflow_slug=d['slug'], workflow_name=d['name'][:120],
                      definition={k: v for k, v in d.items() if k not in ('builtin', 'customised', 'is_active')},
                      actor=user)
    evidence, facts = gather(run, user, ticket, link)
    run.evidence, run.facts = evidence, facts
    run.causes = likely_causes(run.definition, facts)
    run.remediations = remediations(run.definition, facts, user, ticket, device)
    run.diagnostics = read_only_diagnostics(user, ticket, device)
    _log(run, f'Started by {user.get_username()}; {len(evidence)} evidence item(s), '
              f'{len(run.causes)} likely cause(s), {sum(r["offered"] for r in run.remediations)} action(s) offered.')
    run.save()
    stale = [i['label'] for i in evidence if i.get('observed_at') and not i['fresh']]
    lines = [f'Support workflow "{run.workflow_name}" started.']
    for i in evidence:
        age = f'{i["age_minutes"]} min old' if i['age_minutes'] is not None else 'age unknown'
        lines.append(f'- {i["label"]}: {_brief(i["value"])} ({age}{"" if i["fresh"] else ", stale"})')
    if run.causes:
        lines.append('Likely causes: ' + ' / '.join(c['text'] for c in run.causes))
    if stale:
        lines.append('Stale evidence: ' + ', '.join(stale) + '.')
    _note(ticket, '\n'.join(lines), author=user)
    _audit(user, run, f'Support workflow "{run.workflow_name}" started on {ticket.ticket_number}', request)
    return run


def _targets_safe(ticket):
    try:
        from psa_ai.services import rmm_actions
        return rmm_actions.targets(ticket)
    except Exception:  # noqa: BLE001
        return []


def _brief(value):
    if isinstance(value, dict):
        return ', '.join(f'{k}={v}' for k, v in list(value.items())[:8])[:300]
    return str(value)[:300]


def propose(user, run, action_key, key, request=None):
    """Send one offered remediation through the existing fix referral. It
    becomes a Rem0te plan awaiting approval; nothing runs until Rem0te's
    approvers approve it there."""
    from psa_ai.services import rmm_actions
    if not can_run(user, run.ticket):
        raise WorkflowRefused('You may not work on this ticket.')
    if run.status not in PROPOSABLE_FROM:
        raise WorkflowRefused('This workflow already has an action in progress.', 409)
    facts = dict(run.facts or {})
    offered = {r['action'] for r in remediations(run.definition, facts, user, run.ticket, run.device) if r['offered']}
    if action_key not in offered:
        raise WorkflowRefused('That action is not offered for this ticket now.', 400)
    reason = (f'Support workflow "{run.workflow_name}": '
              + (run.alert_link.title if run.alert_link else run.ticket.subject))[:400]
    try:
        req, _repeat = rmm_actions.refer_fix(user, run.ticket, run.device.pk, key, description=reason,
                                             action_key=action_key, request=request)
    except rmm_actions.ActionRefused as e:
        raise WorkflowRefused(e.message, e.status)
    run.rmm_request = req
    run.chosen_action = action_key
    run.status, run.finished_at, run.outcome_note = 'awaiting_approval', None, ''
    _log(run, f'{user.get_username()} asked Rem0te for {action_key}; approval happens in Rem0te.')
    run.save()
    _note(run.ticket, f'Support workflow "{run.workflow_name}": requested {action_key} through Rem0te. It runs '
                      'only after Rem0te\'s approvers approve it' + (f' at {req.approval_url}' if req.approval_url else '')
          + '.', author=user)
    refresh(run, force=False, fetch=False)
    return run


def manual_done(user, run, text='', request=None):
    """The technician did the manual steps; monitoring now has to confirm."""
    if not can_run(user, run.ticket):
        raise WorkflowRefused('You may not work on this ticket.')
    if run.status not in MANUAL_FROM:
        raise WorkflowRefused('This workflow is not waiting for manual steps.', 409)
    text = (text or '').strip()[:2000]
    run.status = 'verifying'
    run.verify_by = timezone.now() + timedelta(minutes=int(run.definition.get('verify_within_minutes') or 60))
    _log(run, f'{user.get_username()} recorded the manual steps as done.')
    run.save()
    _note(run.ticket, f'Support workflow "{run.workflow_name}": manual steps done.'
          + (f' {text}' if text else '') + ' Waiting for monitoring to confirm.', author=user)
    _check_already_recovered(run)
    return run


def request_diagnostic(user, run, diagnostic_key, key, request=None):
    """Ask the RMM for one of its own advertised read-only diagnostics,
    through the existing request flow (staff-only result on the request)."""
    from psa_ai.services import rmm_actions
    if not can_run(user, run.ticket):
        raise WorkflowRefused('You may not work on this ticket.')
    if run.device is None or diagnostic_key not in {d['key'] for d in run.diagnostics or []}:
        raise WorkflowRefused('That diagnostic is not offered for this device.', 400)
    try:
        req, _repeat = rmm_actions.diagnostic(user, run.ticket, run.device.pk, diagnostic_key, key, request=request)
    except rmm_actions.ActionRefused as e:
        raise WorkflowRefused(e.message, e.status)
    _log(run, f'{user.get_username()} requested the read-only diagnostic "{diagnostic_key}".')
    run.save(update_fields=['history', 'updated_at'])
    return req


def cancel(user, run):
    if not can_run(user, run.ticket):
        raise WorkflowRefused('You may not work on this ticket.')
    if not run.is_open:
        return run
    run.status, run.finished_at = 'cancelled', timezone.now()
    _log(run, f'Cancelled by {user.get_username()}.')
    run.save()
    return run


REQUEST_STATUS = {'received': 'awaiting_approval', 'pending': 'awaiting_approval', 'created': 'awaiting_approval',
                  'approved': 'approved', 'running': 'running', 'succeeded': 'verifying', 'failed': 'failed',
                  'rejected': 'rejected', 'expired': 'approval_expired', 'unavailable': 'unavailable'}


def refresh(run, force=False, fetch=True, now=None):
    """Track the proposal and the verification window."""
    now = now or timezone.now()
    with transaction.atomic():
        run = WorkflowRun.objects.select_for_update().select_related('rmm_request', 'ticket', 'alert_link').get(pk=run.pk)
        before = run.status
        req = run.rmm_request
        if req is not None and run.status in ('awaiting_approval', 'approved', 'running', 'ready'):
            if fetch:
                try:
                    from integrations.rem0te import actions as rem0te_actions
                    if req.connection.provider_type == 'rem0te':
                        rem0te_actions.refresh(req, force=force)
                        req.refresh_from_db()
                except Exception:  # noqa: BLE001
                    logger.exception('refreshing proposal %s failed', req.pk)
            status = REQUEST_STATUS.get(req.status, run.status)
            if status == 'awaiting_approval' and req.approval_expires_at and req.approval_expires_at <= now:
                status = 'approval_expired'
            run.status = status
            if status != before:
                _on_status(run, req, now)
        if run.status == 'verifying':
            _check_already_recovered(run, save=False)
            if run.status == 'verifying' and run.verify_by and run.verify_by <= now:
                run.status, run.finished_at = 'not_verified', now
                _log(run, 'Monitoring did not confirm the fix within the window.')
                run.outcome_note = 'Not confirmed: the alert was still open when the verification window ended.'
                _note(run.ticket, f'Support workflow "{run.workflow_name}": not confirmed. The alert is still open '
                                  'after the verification window; the ticket stays open.')
        run.save()
    return run


def _on_status(run, req, now):
    t = run.ticket
    label = run.get_status_display()
    if run.status == 'verifying':
        run.verify_by = now + timedelta(minutes=int(run.definition.get('verify_within_minutes') or 60))
        observed = ', '.join(f'{k}={v}' for k, v in (req.observed or {}).items())
        _log(run, f'Rem0te reports the job succeeded{": " + observed if observed else ""}. Waiting for monitoring.')
        _note(t, f'Support workflow "{run.workflow_name}": Rem0te reports {run.chosen_action} succeeded'
                 f'{" (" + observed + ")" if observed else ""}. Waiting for monitoring to confirm the fix.')
    elif run.status in ('failed', 'rejected', 'approval_expired', 'unavailable'):
        run.finished_at = now
        why = req.error or req.status_note or req.remote_status or ''
        run.outcome_note = f'{label}. {why}'.strip()[:2000]
        _log(run, run.outcome_note)
        _note(t, f'Support workflow "{run.workflow_name}": {label.lower()}'
                 f'{" — " + why if why else ""}. Nothing was changed by ClientSt0r; the ticket stays open.')
    else:
        _log(run, label)


def _check_already_recovered(run, save=True):
    link = run.alert_link
    if run.status == 'verifying' and link is not None and link.state == 'resolved' and link.recovered_at \
            and link.recovered_at >= run.created_at:
        _verified(run, link, save=save)


def _verified(run, link, save=True):
    now = timezone.now()
    run.status, run.finished_at = 'verified', now
    when = timezone.localtime(link.recovered_at or now).strftime('%Y-%m-%d %H:%M')
    run.outcome_note = f'Confirmed by monitoring: the alert recovered at {when}.'
    _log(run, run.outcome_note)
    if save:
        run.save()
    did = (f'requested {run.chosen_action} through Rem0te ({run.rmm_request.remote_outcome or run.rmm_request.status})'
           if run.rmm_request_id else 'did the manual steps')
    causes = '; '.join(c['text'] for c in run.causes[:3]) or '—'
    _note(run.ticket, f'Technician note — {run.workflow_name}: {run.actor.get_username()} {did}. Likely cause: '
                      f'{causes}. {run.outcome_note}', author=run.actor)
    t = run.ticket
    cf = dict(t.custom_fields or {})
    done = dict(cf.get('support_workflows') or {})
    done[run.workflow_slug] = {'run': str(run.pk), 'status': 'verified', 'at': now.isoformat()}
    cf['support_workflows'] = done
    type(t).objects.filter(pk=t.pk).update(custom_fields=cf)


def on_alert_recovered(link, ticket):
    """Monitoring says the alert recovered: confirm runs waiting for it."""
    if link is None:
        return 0
    n = 0
    for run in WorkflowRun.objects.filter(alert_link=link, status__in=list(WorkflowRun.OPEN)).select_related(
            'ticket', 'actor', 'rmm_request'):
        if run.status == 'verifying':
            _verified(run, link)
            n += 1
        else:
            _log(run, 'Monitoring reports the alert recovered before any fix was confirmed.')
            run.save(update_fields=['history', 'updated_at'])
    return n


def tick(limit=200) -> int:
    n = 0
    for run in (WorkflowRun.objects.filter(status__in=['awaiting_approval', 'approved', 'running', 'verifying'])
                .order_by('updated_at')[:limit]):
        try:
            refresh(run)
            n += 1
        except Exception:  # noqa: BLE001
            logger.exception('refreshing workflow run %s failed', run.pk)
    return n
