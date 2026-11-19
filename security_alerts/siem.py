"""
Phase 23 v3.17.337 — SIEM webhook adapter.

Generic ingestion endpoint for SIEM/Syslog/CEF event forwarders. Each
configured `SIEMWebhookEndpoint` exposes a per-token URL; inbound POSTs
are parsed (CEF / generic JSON) into the existing `SecurityAlert` schema
so the downstream triage UI / rule engine / playbooks just work.

CEF (ArcSight Common Event Format) wire shape:

    CEF:Version|Vendor|Product|ProductVersion|SignatureID|Name|Severity|Extension

Extensions are key=value pairs. We translate:
    Name              → SecurityAlert.title
    Severity (0..10)  → SecurityAlert.severity bucket
    SignatureID + dvc → external_id (for dedupe)
    src / dvc / dhost → asset_hint
    msg               → description
    full raw line     → raw_payload['cef_raw']
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from django.utils import timezone


# CEF severity 0..3 → low, 4..6 → medium, 7..8 → high, 9..10 → critical.
# Many sources also use the strings directly.
_CEF_SEVERITY_BANDS = (
    (0, 'low'),
    (3, 'low'),
    (4, 'medium'),
    (6, 'medium'),
    (7, 'high'),
    (8, 'high'),
    (9, 'critical'),
    (10, 'critical'),
)
_SEV_STRING_MAP = {
    'info': 'info', 'informational': 'info',
    'low': 'low',
    'medium': 'medium', 'med': 'medium',
    'high': 'high',
    'critical': 'critical', 'crit': 'critical',
    'very-high': 'critical',
}


def _bucket_severity(value) -> str:
    """Map a CEF/JSON severity value to the SecurityAlert.SEVERITY_CHOICES key."""
    if value is None:
        return 'medium'
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _SEV_STRING_MAP:
            return _SEV_STRING_MAP[v]
        # Numeric string?
        try:
            value = int(v)
        except (TypeError, ValueError):
            # SR-10: never store a vendor's free-text severity; an unknown
            # word becomes medium and is logged so the mapping can be added.
            import logging
            logging.getLogger(__name__).warning('Unknown security alert severity %r mapped to medium', v[:40])
            return 'medium'
    if isinstance(value, (int, float)):
        n = max(0, min(10, int(value)))
        if n <= 3:
            return 'low'
        if n <= 6:
            return 'medium'
        if n <= 8:
            return 'high'
        return 'critical'
    return 'medium'


def _split_cef_extension(ext: str) -> dict:
    """Parse CEF extension `k1=v1 k2=v2 v2-cont k3=v3` into a dict.

    CEF extension values may contain spaces, so we split lazily on
    `KEY=` boundaries (KEY = `[A-Za-z][A-Za-z0-9_]*`).
    """
    result = {}
    if not ext:
        return result
    pattern = re.compile(r'(?:^|\s)([A-Za-z][A-Za-z0-9_]*)=')
    matches = list(pattern.finditer(ext))
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ext)
        # Strip trailing spaces but keep internal spaces.
        result[key] = ext[start:end].rstrip()
    return result


def parse_cef_line(line: str) -> dict | None:
    """Parse a single CEF line into a normalized alert dict.

    Returns None when `line` doesn't start with `CEF:`.
    """
    if not line:
        return None
    line = line.strip()
    if not line.startswith('CEF:'):
        return None
    # Pipes inside a header field are escaped as `\|`. Split on
    # un-escaped pipes — a small state machine handles the escape.
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == '\\' and i + 1 < len(line) and line[i + 1] == '|':
            buf.append('|')
            i += 2
            continue
        if c == '|':
            parts.append(''.join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append(''.join(buf))

    # Expect at least 8 parts: CEF:Version, Vendor, Product, Version, SigID, Name, Sev, Extension
    if len(parts) < 8:
        return None
    cef_header = parts[0]  # 'CEF:0'
    vendor = parts[1]
    product = parts[2]
    product_ver = parts[3]
    signature_id = parts[4]
    name = parts[5]
    severity = parts[6]
    # Extension may legitimately contain `|` only if escaped; collapse
    # everything past index 7 just in case.
    extension = '|'.join(parts[7:])
    ext = _split_cef_extension(extension)

    asset_hint = (
        ext.get('dvchost') or ext.get('dhost') or ext.get('shost')
        or ext.get('dst') or ext.get('src') or ext.get('dvc') or ''
    )
    description = ext.get('msg') or ext.get('reason') or ''
    external_id = (
        ext.get('externalId')
        or f'{vendor}:{product}:{signature_id}:{ext.get("rt", "")}:{asset_hint}'
    )
    return {
        'external_id': external_id[:200],
        'severity': _bucket_severity(severity),
        'title': (name or signature_id or 'Untitled')[:300],
        'description': description,
        'asset_hint': asset_hint[:200],
        'raw_payload': {
            'cef_raw': line,
            'cef_header': cef_header,
            'vendor': vendor,
            'product': product,
            'product_version': product_ver,
            'signature_id': signature_id,
            'extension': ext,
        },
    }


def _pick(d: dict, *keys, default=''):
    for k in keys:
        v = d.get(k)
        if v not in (None, ''):
            return v
    return default


def parse_json_event(payload) -> dict | None:
    """Normalize a generic JSON payload into the SecurityAlert dict shape."""
    if not isinstance(payload, dict):
        return None
    title = _pick(payload, 'title', 'name', 'subject', 'summary', 'event_name')
    if not title:
        return None
    return {
        'external_id': str(_pick(
            payload, 'external_id', 'id', 'event_id', 'uuid', 'eventId',
            default=f'json-{int(timezone.now().timestamp() * 1000)}',
        ))[:200],
        'severity': _bucket_severity(_pick(payload, 'severity', 'level', 'priority')),
        'title': str(title)[:300],
        'description': str(_pick(payload, 'description', 'message', 'msg', 'detail')),
        'asset_hint': str(_pick(
            payload, 'asset', 'asset_hint', 'host', 'hostname', 'src',
            'dst', 'device', 'dvchost',
        ))[:200],
        'raw_payload': payload,
    }


def parse_inbound(body: bytes, expected_format: str) -> list[dict]:
    """Parse the request body into a list of normalized alert dicts.

    Tries the configured format first, then falls back to JSON / CEF
    auto-detect so a misconfigured collector still gets ingested rather
    than silently dropped.
    """
    text = (body or b'').decode('utf-8', errors='replace').strip()
    if not text:
        return []

    alerts: list[dict] = []

    def _try_json():
        try:
            data = json.loads(text)
        except Exception:
            return None
        if isinstance(data, list):
            return [a for a in (parse_json_event(d) for d in data) if a]
        if isinstance(data, dict):
            # CEF-via-JSON: {"events":[{...}]}
            if 'events' in data and isinstance(data['events'], list):
                return [a for a in (parse_json_event(d) for d in data['events']) if a]
            single = parse_json_event(data)
            return [single] if single else []
        return None

    def _try_cef():
        out = []
        for line in text.splitlines():
            parsed = parse_cef_line(line)
            if parsed:
                out.append(parsed)
        return out

    if expected_format == 'json':
        alerts = _try_json() or _try_cef() or []
    elif expected_format == 'cef':
        alerts = _try_cef() or _try_json() or []
    elif expected_format == 'syslog':
        # Simple syslog with embedded CEF payload — try CEF then JSON.
        alerts = _try_cef() or _try_json() or []
    else:
        alerts = _try_json() or _try_cef() or []

    return alerts


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    """Constant-time compare HMAC-SHA256 of body against header."""
    if not signature_header:
        return False
    expected = hmac.new(
        (secret or '').encode('utf-8'), body, hashlib.sha256,
    ).hexdigest()
    sig = signature_header.strip().lower()
    if sig.startswith('sha256='):
        sig = sig[len('sha256='):]
    return hmac.compare_digest(expected, sig)


def ingest_payload(endpoint, alerts: list[dict]) -> int:
    """Persist normalized alert dicts onto the endpoint. Returns count of new rows."""
    from .models import SecurityAlert
    from .adapters.base import _maybe_auto_ticket

    imported = 0
    for a in alerts:
        ext_id = a.get('external_id')
        if not ext_id:
            continue
        defaults = {
            'organization': endpoint.organization,
            'client_org': endpoint.client_org,
            'severity': a.get('severity') or endpoint.default_severity,
            'title': (a.get('title') or '')[:300],
            'description': a.get('description') or '',
            'asset_hint': (a.get('asset_hint') or '')[:200],
            'raw_payload': a.get('raw_payload') or {},
        }
        obj, created = SecurityAlert.objects.update_or_create(
            siem_endpoint=endpoint, external_id=ext_id,
            defaults=defaults,
        )
        if created:
            imported += 1
            try:
                _maybe_auto_ticket(obj)
            except Exception:
                # Auto-ticket failures must not blow up ingestion.
                pass
            try:
                from .models import _correlate_alert_to_incident
                _correlate_alert_to_incident(obj)
            except Exception:
                pass
    return imported
