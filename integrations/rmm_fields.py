"""
Per-provider field maps for the device facts the Device Workspace shows
(assets/device_workspace.py): agent version, last boot, logged-in user,
disks, network adapters and IPs, restart pending and patch fields.

Each map reads the raw payload a sync stored (RMMDevice.raw_data) by the
field names the provider actually returns, taken from the provider's own
API reference or source and from what our client fetches. A fact a
provider doesn't put in the payload our client reads is listed in
UNSUPPORTED with the reason, instead of being guessed from another
provider's key names.

Sources (checked 2026-11):

  tactical_rmm  GET /agents/ (AgentTableSerializer) and GET /agents/{agent_id}/
                (AgentSerializer) in amidaware/tacticalrmm api/tacticalrmm/agents/
                serializers.py + models.py; Disk / service shapes from
                amidaware/rmmagent shared/types.go and trmm-shared.
  ninjaone      GET /v2/devices-detailed and GET /v2/device/{id}, NinjaOne
                Public API 2.0 reference (os.lastBootTime epoch seconds,
                os.needsReboot, lastLoggedInUser, volumes, ipAddresses,
                macAddresses, publicIP).
  datto_rmm     GET /api/v2/account/devices and GET /api/v2/device/{deviceUid},
                Datto RMM API v2 OpenAPI (lastReboot epoch ms, rebootRequired,
                lastLoggedInUser, displayVersion / cagVersion, intIpAddress,
                extIpAddress, patchManagement{...}).
  atera         GET /v3/agents (AgentID, AgentVersion, LastRebootTime,
                CurrentLoggedUsers, LastLoginUser, HardwareDisks[{Drive, Free,
                Used, Total} in MB], IpAddresses, MacAddresses, ReportFromIP,
                LastPatchManagementReceived).
  connectwise_automate
                GET /cwa/api/v1/Computers (RemoteAgentVersion, SystemUptime in
                seconds, LoggedInUsers[].LoggedInUserName, LastUserName,
                IsRebootNeeded, WindowsUpdateDate, LocalIPAddress, MacAddress).
  rem0te        GET /api/v1/pub/v1/computers (docs/PUBLIC-API.md in the Rem0te
                repository): id, hostname, ipAddress, macAddress, osVersion,
                isOnline, lastSeenAt only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime

FACTS = ('agent_version', 'last_boot', 'logged_in', 'reboot', 'last_patched', 'disks', 'nics', 'ips',
         'public_ip')

# provider_type -> fact -> why it isn't available. Shown on the page.
UNSUPPORTED: Dict[str, Dict[str, str]] = {
    'tactical_rmm': {
        'nics': "Tactical RMM lists adapters only for Windows agents (wmi_detail.network_config); "
                "Linux and macOS agents report IP addresses only.",
    },
    'ninjaone': {
        'agent_version': "NinjaOne's device records don't carry the agent version.",
        'last_patched': "NinjaOne reports patch installs on /v2/device/{id}/os-patch-installs, which "
                        "ClientSt0r's NinjaOne client doesn't read.",
        'nics': "NinjaOne's device record lists IP and MAC addresses without adapter names "
                "(adapters are on a query endpoint ClientSt0r doesn't read).",
    },
    'datto_rmm': {
        'disks': "Datto RMM reports disks in the per-device audit (/api/v2/audit/device/{uid}), which "
                 "ClientSt0r's Datto client doesn't read.",
        'nics': "Datto RMM reports network adapters in the per-device audit, which ClientSt0r's Datto "
                "client doesn't read.",
        'last_patched': "Datto RMM's device record has a patch status summary but no last-patched date.",
    },
    'atera': {
        'reboot': "Atera's agent record has no restart-pending field.",
        'nics': "Atera lists IP and MAC addresses without adapter names.",
        'last_patched': "Atera's agent record says when patch data was last received, not when the device "
                        "was last patched.",
    },
    'connectwise_automate': {
        'disks': "ConnectWise Automate lists drives on a separate endpoint ClientSt0r's Automate client "
                 "doesn't read.",
        'nics': "ConnectWise Automate's computer record has one local IP and MAC, not an adapter list.",
        'public_ip': "ConnectWise Automate's computer record doesn't carry a public IP.",
    },
    'rem0te': {
        'agent_version': "Rem0te's computer inventory doesn't share the agent version.",
        'logged_in': "Rem0te's computer inventory doesn't share the logged-in user.",
        'last_boot': "Rem0te's computer inventory has no boot time (a patch summary may carry one).",
        'disks': "Rem0te's computer inventory doesn't share disks.",
        'nics': "Rem0te's computer inventory has one IP and MAC, not an adapter list.",
        'public_ip': "Rem0te's computer inventory has one IP address only.",
        'reboot': 'Restart pending comes from the patch summary on Rem0te restart-pending alerts.',
        'last_patched': 'Patch status comes from the patch summary on Rem0te restart-pending alerts.',
    },
}

# Placeholder values providers use for "nobody" / "unknown".
_BLANK = {'', 'none', 'null', '-', 'n/a', 'unknown'}


# --- value helpers -----------------------------------------------------------------

def _present(v) -> bool:
    if v is None or v == [] or v == {}:
        return False
    if isinstance(v, str) and v.strip().lower() in _BLANK:
        return False
    return True


def _get(raw: dict, path: str):
    cur: Any = raw
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _first(raw: dict, *paths):
    for p in paths:
        v = _get(raw, p)
        if _present(v):
            return v
    return None


def _text(value, limit=200) -> str:
    return str(value if value is not None else '').strip()[:limit]


def as_dt(value, *, millis: Optional[bool] = None) -> Optional[datetime]:
    """ISO text, or Unix seconds / milliseconds. `millis` forces the unit
    when the provider documents it; otherwise large numbers are taken as ms."""
    if value in (None, '') or isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().replace('.', '', 1).isdigit():
        value = float(value)
    if isinstance(value, (int, float)):
        ms = millis if millis is not None else value > 10 ** 11
        try:
            return datetime.fromtimestamp(float(value) / (1000.0 if ms else 1.0), tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    dt = parse_datetime(str(value)[:40])
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def as_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ('true', 'yes', '1', 'required', 'pending'):
            return True
        if low in ('false', 'no', '0', 'not required'):
            return False
    return None


def _size(value, unit_bytes: int) -> str:
    """A size for display. Numbers are in `unit_bytes`; text is kept."""
    if value in (None, ''):
        return ''
    if isinstance(value, str):
        return _text(value, 30)
    try:
        n = float(value) * unit_bytes
    except (TypeError, ValueError):
        return ''
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if n < 1024 or unit == 'PB':
            return f'{n:.0f} {unit}' if unit in ('B', 'KB') else f'{n:.1f} {unit}'
        n /= 1024.0
    return ''


def _pct_used(total, free) -> Optional[float]:
    try:
        t, f = float(total), float(free)
    except (TypeError, ValueError):
        return None
    return round((t - f) / t * 100, 1) if t > 0 else None


def _ip_list(value) -> List[str]:
    if isinstance(value, str):
        items = value.replace(';', ',').split(',')
    elif isinstance(value, list):
        items = value
    else:
        return []
    out = []
    for v in items:
        s = _text(v, 50)
        if s and s not in out:
            out.append(s)
    return out[:20]


def _disk(name, total='', free='', percent=None, fstype='') -> dict:
    return {'name': _text(name or '?', 60), 'total': total, 'free': free,
            'percent': percent if isinstance(percent, (int, float)) and not isinstance(percent, bool) else None,
            'fstype': _text(fstype, 20)}


# --- providers ----------------------------------------------------------------------

def _trmm_size(value):
    # No disk is under a megabyte, so a small number is GB (older agents).
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 10 ** 6:
        return _size(value, 1024 ** 3)
    return _size(value, 1)


def _tactical(raw: dict, device) -> dict:
    disks = []
    for d in (raw.get('disks') or [])[:20]:
        if isinstance(d, dict):
            # Agents report "237.5 GB" strings; rmmagent's raw struct uses bytes.
            disks.append(_disk(d.get('device'), _trmm_size(d.get('total')), _trmm_size(d.get('free')),
                               d.get('percent'), d.get('fstype')))
    nics = []
    for group in ((raw.get('wmi_detail') or {}).get('network_config') or [])[:20]:
        for n in (group if isinstance(group, list) else [group]):
            if isinstance(n, dict) and (n.get('IPEnabled') or n.get('IPAddress')):
                nics.append({'name': _text(n.get('Description') or n.get('Caption') or 'Adapter', 80),
                             'mac': _text(n.get('MACAddress'), 30),
                             'ips': ', '.join(_ip_list(n.get('IPAddress') or [])[:6])})
    return {
        'agent_version': _first(raw, 'version'),
        'last_boot': as_dt(raw.get('boot_time'), millis=False),
        # Table rows carry logged_username ("-" for nobody); the detail
        # route carries logged_in_username / last_logged_in_user ("None").
        'logged_in': _first(raw, 'logged_username', 'logged_in_username', 'last_logged_in_user'),
        'reboot': as_bool(raw.get('needs_reboot')),
        'last_patched': as_dt(raw.get('patches_last_installed')),
        'patch_fields': [('Patches pending', 'Yes' if raw['has_patches_pending'] else 'No')]
        if isinstance(raw.get('has_patches_pending'), bool) else [],
        'disks': disks,
        'nics': nics,
        'ips': _ip_list(raw.get('local_ips')),
        'public_ip': _first(raw, 'public_ip'),
    }


def _ninjaone(raw: dict, device) -> dict:
    disks = []
    for v in (raw.get('volumes') or [])[:20]:
        if isinstance(v, dict):
            disks.append(_disk(v.get('name') or v.get('label'), _size(v.get('capacity'), 1),
                               _size(v.get('freeSpace'), 1), _pct_used(v.get('capacity'), v.get('freeSpace')),
                               v.get('fileSystem')))
    return {
        'agent_version': None,
        'last_boot': as_dt(_first(raw, 'os.lastBootTime', 'lastBootTime'), millis=False),
        'logged_in': _first(raw, 'lastLoggedInUser'),
        'reboot': as_bool(_first(raw, 'os.needsReboot', 'needsReboot')),
        'last_patched': None,
        'patch_fields': [],
        'disks': disks,
        'nics': [],
        'ips': _ip_list(raw.get('ipAddresses')),
        'public_ip': _first(raw, 'publicIP'),
    }


DATTO_PATCH_LABELS = (('patchStatus', 'Patch status'), ('patchesApprovedPending', 'Approved, pending'),
                      ('patchesNotApproved', 'Not approved'), ('patchesInstalled', 'Installed'))


def _datto(raw: dict, device) -> dict:
    pm = raw.get('patchManagement') if isinstance(raw.get('patchManagement'), dict) else {}
    reboot = as_bool(raw.get('rebootRequired'))
    if reboot is None and pm.get('patchStatus') == 'RebootRequired':
        reboot = True
    return {
        'agent_version': _first(raw, 'displayVersion', 'cagVersion'),
        'last_boot': as_dt(raw.get('lastReboot'), millis=True),
        'logged_in': _first(raw, 'lastLoggedInUser'),
        'reboot': reboot,
        'last_patched': None,
        'patch_fields': [(label, _text(pm[k], 40)) for k, label in DATTO_PATCH_LABELS
                         if pm.get(k) not in (None, '')],
        'disks': [],
        'nics': [],
        'ips': _ip_list([raw['intIpAddress']] if raw.get('intIpAddress') else []),
        'public_ip': _first(raw, 'extIpAddress'),
    }


def _atera(raw: dict, device) -> dict:
    disks = []
    for d in (raw.get('HardwareDisks') or [])[:20]:
        if isinstance(d, dict):
            disks.append(_disk(d.get('Drive'), _size(d.get('Total'), 1024 ** 2), _size(d.get('Free'), 1024 ** 2),
                               _pct_used(d.get('Total'), d.get('Free'))))
    received = raw.get('LastPatchManagementReceived')
    return {
        'agent_version': _first(raw, 'AgentVersion'),
        'last_boot': as_dt(raw.get('LastRebootTime')),
        'logged_in': _first(raw, 'CurrentLoggedUsers', 'LastLoginUser'),
        'reboot': None,
        'last_patched': None,
        'patch_fields': [('Patch report received', _text(received, 40))] if _present(received) else [],
        'disks': disks,
        'nics': [],
        'ips': _ip_list(raw.get('IpAddresses')),
        'public_ip': _first(raw, 'ReportFromIP'),
    }


def _automate(raw: dict, device) -> dict:
    users = [u.get('LoggedInUserName') for u in (raw.get('LoggedInUsers') or [])
             if isinstance(u, dict) and _present(u.get('LoggedInUserName'))]
    boot = None
    uptime = raw.get('SystemUptime')
    as_of = getattr(device, 'data_refreshed_at', None)
    if isinstance(uptime, (int, float)) and not isinstance(uptime, bool) and uptime >= 0 and as_of:
        # Uptime is seconds as of the read; the boot time is that read minus it.
        boot = as_of - timedelta(seconds=float(uptime))
    return {
        'agent_version': _first(raw, 'RemoteAgentVersion'),
        'last_boot': boot,
        'logged_in': ', '.join(_text(u, 80) for u in users[:4]) if users else _first(raw, 'LastUserName'),
        'reboot': as_bool(raw.get('IsRebootNeeded')),
        'last_patched': as_dt(raw.get('WindowsUpdateDate')),
        'patch_fields': [],
        'disks': [],
        'nics': [],
        'ips': _ip_list([raw['LocalIPAddress']] if raw.get('LocalIPAddress') else []),
        'public_ip': None,
    }


def _rem0te(raw: dict, device) -> dict:
    return {'agent_version': None, 'last_boot': None, 'logged_in': None, 'reboot': None, 'last_patched': None,
            'patch_fields': [], 'disks': [], 'nics': [],
            'ips': _ip_list([raw['ipAddress']] if raw.get('ipAddress') else []), 'public_ip': None}


EXTRACTORS = {
    'tactical_rmm': _tactical,
    'ninjaone': _ninjaone,
    'datto_rmm': _datto,
    'atera': _atera,
    'connectwise_automate': _automate,
    'rem0te': _rem0te,
}

# Whether each provider's device payload carries any patch information.
PATCH_SOURCE = {
    'tactical_rmm': 'needs_reboot, patches_last_installed and has_patches_pending on the agent record',
    'ninjaone': 'os.needsReboot on the device record',
    'datto_rmm': 'rebootRequired and patchManagement on the device record',
    'atera': 'LastPatchManagementReceived on the agent record',
    'connectwise_automate': 'IsRebootNeeded and WindowsUpdateDate on the computer record',
}


def unsupported_reason(provider_type: str, fact: str) -> str:
    return UNSUPPORTED.get(provider_type, {}).get(fact, '')


def facts(device) -> Dict[str, Any]:
    """The facts for one device from its stored raw data, by its provider's
    field map. Unknown providers give nothing (and say so)."""
    ptype = device.connection.provider_type
    raw = device.raw_data or {}
    fn = EXTRACTORS.get(ptype)
    if fn is None:
        out = {k: None for k in FACTS}
        out.update(disks=[], nics=[], ips=[], patch_fields=[])
        out['unsupported'] = {k: 'No field map for this provider.' for k in FACTS}
        return out
    out = fn(raw, device)
    for key in ('agent_version', 'logged_in', 'public_ip'):
        out[key] = _text(out[key], 120) if _present(out.get(key)) else None
    out['unsupported'] = dict(UNSUPPORTED.get(ptype, {}))
    return out


# Services, processes and Windows events: what each provider's API offers
# and why ClientSt0r doesn't have it. Only Tactical RMM's services come
# with a route ClientSt0r's client already calls (integrations/rmm_snapshots.py);
# the others would need new calls, listed here instead of added.
LIST_GAPS: Dict[str, Dict[str, str]] = {
    'tactical_rmm': {
        'processes': "Tactical RMM reads processes live from the agent (GET /agents/{agent_id}/processes/), "
                     "which ClientSt0r's Tactical RMM client doesn't call.",
        'events': "Tactical RMM reads the event log live from the agent "
                  "(GET /agents/{agent_id}/eventlog/{logtype}/{days}/), which ClientSt0r's Tactical RMM client "
                  "doesn't call.",
    },
    'ninjaone': {
        'services': "NinjaOne lists services on GET /v2/device/{id}/windows-services, which ClientSt0r's NinjaOne "
                    "client doesn't call.",
        'processes': "NinjaOne's public API has no per-device process list.",
        'events': "NinjaOne's public API has no per-device event log list.",
    },
    'datto_rmm': {
        'services': "Datto RMM's API has no service list.",
        'processes': "Datto RMM's API has no process list.",
        'events': "Datto RMM's API has no event log list.",
    },
    'atera': {
        'services': "Atera's API has no service list.",
        'processes': "Atera's API has no process list.",
        'events': "Atera's API has no event log list.",
    },
    'connectwise_automate': {
        'services': "ClientSt0r's ConnectWise Automate client doesn't read a computer's services.",
        'processes': "ClientSt0r's ConnectWise Automate client doesn't read a computer's processes.",
        'events': "ClientSt0r's ConnectWise Automate client doesn't read a computer's event log.",
    },
    'rem0te': {
        'services': "Rem0te's integration doesn't give ClientSt0r services (Rem0te reads them on its own "
                    "monitoring pages).",
        'processes': "Rem0te's integration doesn't give ClientSt0r processes (Rem0te reads them on its own "
                     "monitoring pages).",
        'events': "Rem0te's integration doesn't give ClientSt0r Windows events (Rem0te reads them on its own "
                  "monitoring pages).",
    },
}


def list_gap(provider_type: str, kind: str, label: str = '') -> str:
    what = {'events': 'Windows events'}.get(kind, kind)
    return (LIST_GAPS.get(provider_type, {}).get(kind)
            or f"{label or 'This'} integration doesn't give ClientSt0r {what}.")
