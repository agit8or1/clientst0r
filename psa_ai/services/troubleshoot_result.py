"""
Turn a model's troubleshooting answer into a fixed structure, treating it as
untrusted (prompts/system_troubleshoot.md asks for one JSON object).

  technician_summary   text
  likely_causes        [{text, likelihood, evidence: [observation ids]}]
  diagnostic_steps     [{text, command, evidence}] — read-only only; a step
                       or command that looks like it changes the system is
                       dropped with a warning. When the installation sets a
                       command allowlist (AIInstallationSettings
                       .command_allowlist), a command must also match one of
                       its patterns; the denylist applies either way.
                       Commands are text for a person to read; nothing here
                       or anywhere else runs them.
  alert_summary        text
  runbooks             [{id, why}]  — only IDs from the runbook list sent
  recommended_actions  [{id, why}]  — only IDs from the action list sent
                       (what the device advertises and the technician may
                       request, at the time the session started)
  risk                 {level, service_impact}
  customer_response    text (shown only to technicians who may draft)
  missing_information  [text]
  warnings             [text]

Unknown keys are ignored. Every string is sanitized, length-capped, run
through the output filter and redacted.
"""
from __future__ import annotations

import fnmatch
import logging
import re
from typing import Dict, List, Optional

from .analysis_result import InvalidResult, LIKELIHOODS, _json_object, _words
from .evidence import redact
from .guardrails import output_passes_filter

__all__ = ['InvalidResult', 'parse', 'compare', 'is_read_only', 'parse_allowlist', 'allowlisted',
           'allowlist_errors']

logger = logging.getLogger('psa_ai')

MAX_ALLOWLIST_PATTERNS = 200
MAX_PATTERN_CHARS = 200

LIMITS = {'likely_causes': 5, 'diagnostic_steps': 8, 'runbooks': 5, 'recommended_actions': 4,
          'missing_information': 8, 'warnings': 8}

# A command or step matching any of these changes the system (or runs
# arbitrary code), so it is not a read-only diagnostic.
_MUTATING_COMMAND = re.compile(
    r'(?ix)'
    r'(^|[\s;&|`(])(rm|rmdir|del|erase|rd|format|mkfs\S*|dd|shutdown|reboot|halt|poweroff|kill|pkill|killall|'
    r'taskkill|chmod|chown|chattr|icacls|takeown|cacls|bcdedit|diskpart|fdisk|parted|wipefs|cipher|'
    r'iex|msiexec|regsvr32|rundll32|schtasks|at|crontab|useradd|userdel|usermod|passwd|net\s+user|'
    r'mv|move|ren|rename|cp|copy|xcopy|robocopy|truncate|tee|sed\s+-i|apt(-get)?|yum|dnf|zypper|pacman|'
    r'brew|choco|winget|pip3?|npm|gem|curl|wget|bitsadmin|certutil)(\s|$)'
    r'|\b(Set|Remove|Stop|Restart|Start|New|Add|Install|Uninstall|Disable|Enable|Clear|Reset|Rename|Move|'
    r'Copy|Invoke|Update|Suspend|Resume|Initialize|Mount|Dismount|Register|Unregister|Grant|Revoke|'
    r'Import|Export|Push|Publish|Send)-[A-Za-z]+|\bFormat-Volume\b|\bOut-File\b'
    r'|\breg(\.exe)?\s+(add|delete|import|load|unload|copy|restore)\b'
    r'|\bsc(\.exe)?\s+(stop|start|delete|config|create|failure|pause|continue)\b'
    r'|\bnet\s+(stop|start|share|use|localgroup)\b'
    r'|\bsystemctl\s+(start|stop|restart|reload|enable|disable|mask|kill|isolate)\b'
    r'|\bservice\s+\S+\s+(start|stop|restart|reload)\b'
    r'|\bwmic\b.*\b(delete|call|set|create)\b'
    r'|\bvssadmin\s+(delete|resize)\b'
    r'|\bgpupdate\b|\bipconfig\s+/(release|renew|flushdns)\b|\bnetsh\b.*\b(set|add|delete|reset)\b'
    r'|-enc(odedcommand)?\b|\bpowershell\b.*-c(ommand)?\s'
    r'|\|\s*(sh|bash|zsh|iex|powershell|pwsh|cmd)\b|>\s*\S|\bsudo\b|\brunas\b|\bsu\s'
)
_MUTATING_TEXT = re.compile(
    r'(?i)\b(restart|reboot|re-?install|uninstall|delete|remove|wipe|erase|format|kill|stop the|disable|'
    r'reset|re-?image|roll ?back|overwrite|modify|change the|edit the registry|flush)\b')


def is_read_only(command: str) -> bool:
    """True if `command` looks read-only. Conservative: when in doubt, no."""
    command = (command or '').strip()
    if not command:
        return True
    if '\n' in command or len(command) > 300:
        return False
    return not _MUTATING_COMMAND.search(command)


def parse_allowlist(text) -> List[str]:
    """The allowlist patterns in `text`: one per line, blank lines and lines
    starting with # ignored, whitespace collapsed, lower-cased."""
    out = []
    for line in (text or '').splitlines():
        line = ' '.join(line.split()).lower()
        if line and not line.startswith('#') and len(line) <= MAX_PATTERN_CHARS:
            out.append(line)
    return list(dict.fromkeys(out))[:MAX_ALLOWLIST_PATTERNS]


def allowlist_errors(text) -> List[str]:
    """Problems with an allowlist an administrator typed; empty = fine."""
    errors = []
    lines = [' '.join(x.split()) for x in (text or '').splitlines()]
    lines = [x for x in lines if x and not x.startswith('#')]
    if len(lines) > MAX_ALLOWLIST_PATTERNS:
        errors.append(f'At most {MAX_ALLOWLIST_PATTERNS} patterns.')
    for x in lines:
        if len(x) > MAX_PATTERN_CHARS:
            errors.append(f'Patterns are limited to {MAX_PATTERN_CHARS} characters: "{x[:40]}…"')
        elif x.strip('*? ') == '':
            errors.append(f'"{x}" would allow every command; name the command it allows.')
        elif not is_read_only(x.replace('*', 'x').replace('?', 'x')):
            errors.append(f'"{x}" matches a command the built-in denylist treats as changing the system, '
                          'so it would never be shown anyway.')
    return errors


def allowlisted(command: str, patterns) -> bool:
    """True if `command` matches one of the allowlist `patterns` (shell-style
    wildcards over the whole command, case-insensitive, whitespace collapsed)."""
    command = ' '.join((command or '').split()).lower()
    return any(fnmatch.fnmatchcase(command, p) for p in patterns or ())


def installation_allowlist() -> List[str]:
    """The installation's command allowlist (empty = denylist only)."""
    from psa_ai.models import AIInstallationSettings
    try:
        text = AIInstallationSettings.objects.filter(pk=1).values_list('command_allowlist', flat=True).first()
    except Exception:  # an unreadable setting falls back to the denylist alone
        logger.exception('troubleshoot: could not read the command allowlist')
        return []
    return parse_allowlist(text)


def _clean(value, max_chars, notes) -> str:
    if not isinstance(value, str):
        return ''
    text = redact(value.strip(), max_chars=max_chars)
    ok, _ = output_passes_filter(text)
    if not ok:
        notes['filtered'] += 1
        return ''
    return text


def _refs(value, valid) -> List[str]:
    if not isinstance(value, list):
        return []
    return [r for r in value if isinstance(r, str) and r in valid][:6]


def _picked(items, valid, notes, key):
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ref = item.get('id')
        if not isinstance(ref, str) or ref not in valid:
            notes[key] += 1
            continue
        if ref in seen:
            continue
        seen.add(ref)
        out.append({'id': ref, 'why': _clean(item.get('why'), 300, notes)})
    return out


def parse(text: str, observation_ids: set, runbook_ids: set, action_ids: set,
          allowlist: Optional[List[str]] = None) -> Dict:
    """`allowlist`: command patterns (parse_allowlist); None = the
    installation's setting, [] = the denylist alone."""
    data = _json_object(text)
    if allowlist is None:
        allowlist = installation_allowlist()
    notes = {'filtered': 0, 'not_read_only': 0, 'not_allowlisted': 0, 'unknown_runbooks': 0,
             'unknown_actions': 0}
    out = {
        'technician_summary': _clean(data.get('technician_summary'), 1200, notes),
        'likely_causes': [], 'diagnostic_steps': [],
        'alert_summary': _clean(data.get('alert_summary'), 600, notes),
        'runbooks': _picked(data.get('runbooks'), runbook_ids, notes, 'unknown_runbooks'),
        'recommended_actions': _picked(data.get('recommended_actions'), action_ids, notes, 'unknown_actions'),
        'risk': {'level': 'medium', 'service_impact': ''},
        'customer_response': _clean(data.get('customer_response'), 3000, notes),
        'missing_information': [], 'warnings': [],
    }
    for c in data.get('likely_causes') or []:
        if not isinstance(c, dict):
            continue
        t = _clean(c.get('text'), 500, notes)
        if t:
            lk = str(c.get('likelihood') or '').lower()
            out['likely_causes'].append({'text': t, 'likelihood': lk if lk in LIKELIHOODS else 'low',
                                         'evidence': _refs(c.get('evidence'), observation_ids)})
    for s in data.get('diagnostic_steps') or []:
        if isinstance(s, str):
            s = {'text': s}
        if not isinstance(s, dict):
            continue
        t = _clean(s.get('text'), 400, notes)
        raw_cmd = s.get('command') if isinstance(s.get('command'), str) else ''
        if raw_cmd and not is_read_only(raw_cmd):
            notes['not_read_only'] += 1
            continue
        if raw_cmd.strip() and allowlist and not allowlisted(raw_cmd, allowlist):
            notes['not_allowlisted'] += 1
            continue
        cmd = _clean(raw_cmd, 300, notes)
        if not t or _MUTATING_TEXT.search(t):
            if t:
                notes['not_read_only'] += 1
            continue
        out['diagnostic_steps'].append({'text': t, 'command': cmd,
                                        'evidence': _refs(s.get('evidence'), observation_ids)})
    risk = data.get('risk') if isinstance(data.get('risk'), dict) else {}
    level = str(risk.get('level') or '').lower()
    out['risk'] = {'level': level if level in LIKELIHOODS else 'medium',
                   'service_impact': _clean(risk.get('service_impact'), 500, notes)}
    for key in ('missing_information', 'warnings'):
        for item in data.get(key) or []:
            t = _clean(item, 400, notes)
            if t:
                out[key].append(t)
    for key, limit in LIMITS.items():
        out[key] = out[key][:limit]
    if notes['filtered']:
        out['warnings'].append(f'{notes["filtered"]} item(s) removed by the safety filter.')
    if notes['not_read_only']:
        out['warnings'].append(f'{notes["not_read_only"]} diagnostic step(s) removed: they would change the '
                               'system, and only read-only checks are suggested.')
    if notes['not_allowlisted']:
        out['warnings'].append(f'{notes["not_allowlisted"]} diagnostic step(s) removed: their command is not on '
                               "this installation's read-only command allowlist.")
    if notes['unknown_runbooks']:
        out['warnings'].append(f'{notes["unknown_runbooks"]} runbook reference(s) removed: not in the runbook list.')
    if notes['unknown_actions']:
        out['warnings'].append(f'{notes["unknown_actions"]} action suggestion(s) removed: not an action this '
                               'device offers and you may request.')
    if not (out['technician_summary'] or out['likely_causes'] or out['diagnostic_steps']):
        raise InvalidResult('The model returned nothing usable.')
    return out


def compare(named_results) -> Dict:
    """Agreements and disagreements between models. `named_results` is
    [(model label, result dict)] for succeeded runs only."""
    agreements, disagreements = [], []
    if len(named_results) < 2:
        return {'agreements': agreements, 'disagreements': disagreements}
    names = [n for n, _ in named_results]

    def top(res):
        causes = res.get('likely_causes') or []
        return causes[0] if causes else None

    for i in range(len(named_results)):
        for j in range(i + 1, len(named_results)):
            (na, a), (nb, b) = named_results[i], named_results[j]
            ta, tb = top(a), top(b)
            if ta and tb:
                wa, wb = _words(ta['text']), _words(tb['text'])
                overlap = len(wa & wb) / max(1, len(wa | wb))
                if overlap >= 0.25:
                    agreements.append(f'{na} and {nb} name the same most likely cause.')
                    if {ta['likelihood'], tb['likelihood']} == {'low', 'high'}:
                        disagreements.append({'field': 'likely_causes', 'models': [na, nb],
                                              'detail': f'{na} and {nb} rate that cause very differently.'})
                else:
                    disagreements.append({'field': 'likely_causes', 'models': [na, nb],
                                          'detail': f'{na} and {nb} name different most likely causes.'})
            ra, rb = (a.get('risk') or {}).get('level'), (b.get('risk') or {}).get('level')
            if ra and rb:
                if ra == rb:
                    agreements.append(f'{na} and {nb} both rate the risk {ra}.')
                else:
                    disagreements.append({'field': 'risk', 'models': [na, nb],
                                          'detail': f'{na} rates the risk {ra}; {nb} rates it {rb}.'})
    for field, label in (('recommended_actions', 'action'), ('runbooks', 'runbook')):
        sets = [{x['id'] for x in (res.get(field) or [])} for _, res in named_results]
        common = set.intersection(*sets) if sets else set()
        for ref in sorted(common):
            agreements.append(f'All models suggest {label} {ref}.')
        for ref in sorted(set.union(*sets) - common):
            who = [names[k] for k, s in enumerate(sets) if ref in s]
            disagreements.append({'field': field, 'models': who,
                                  'detail': f'Only {", ".join(who)} suggest{"s" if len(who) == 1 else ""} '
                                            f'{label} {ref}.', 'ref': ref})
    return {'agreements': agreements, 'disagreements': disagreements}
