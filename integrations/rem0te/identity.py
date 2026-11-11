"""
ClientSt0r's Ed25519 identity towards Rem0te (integrations.Rem0teIdentity).

What an administrator copies into Rem0te's INTEGRATION_PEERS_FILE comes from
`peer_entry()`: the peer id, both audiences, the two PUBLIC keys with their
key ids, and the two ClientSt0r URLs. Private keys never leave this module
except to sign.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Optional
from urllib.parse import urlsplit

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import protocol

PEER_ID_RE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


class IdentityError(Exception):
    pass


def get(create=True):
    from integrations.models import Rem0teIdentity
    ident = Rem0teIdentity.objects.order_by('pk').first()
    if ident is None and create:
        ident = Rem0teIdentity.objects.create()
    return ident


def has_keys(ident=None) -> bool:
    ident = ident or get(create=False)
    return bool(ident and ident.request_kid and ident.request_private_key and ident.delegation_kid
                and ident.delegation_private_key and protocol.KID_RE.match(ident.request_kid)
                and protocol.KID_RE.match(ident.delegation_kid))


def _kid(prefix):
    return f'{prefix}-{timezone.now():%Y%m%d}-{secrets.token_hex(3)}'


def generate_keys(by=None, rotate=False):
    """Create the request and delegation key pairs (or replace them). The
    old public keys must stay in Rem0te's peers file until Rem0te is
    restarted with the new ones; nothing here can reach that file."""
    from audit.models import AuditLog
    with transaction.atomic():
        ident = get()
        from integrations.models import Rem0teIdentity
        ident = Rem0teIdentity.objects.select_for_update().get(pk=ident.pk)
        if has_keys(ident) and not rotate:
            return ident
        ident.request_kid = _kid('req')
        ident.request_private_key = protocol.generate_private_key_pem()
        ident.delegation_kid = _kid('del')
        ident.delegation_private_key = protocol.generate_private_key_pem()
        if rotate:
            ident.rotated_at = timezone.now()
        ident.next_request_kid = ident.next_request_private_key = ''
        ident.next_delegation_kid = ident.next_delegation_private_key = ''
        ident.next_staged_at = None
        ident.save()
    AuditLog.log(user=by, action='update', object_type='rem0te_identity', object_id=ident.pk,
                 object_repr='ClientSt0r Rem0te identity',
                 description=('Rotated' if rotate else 'Generated') + ' ClientSt0r\'s Rem0te request and delegation '
                 f'keys (request {ident.request_kid}, delegation {ident.delegation_kid})',
                 extra_data={'request_kid': ident.request_kid, 'delegation_kid': ident.delegation_kid})
    return ident


def has_next_keys(ident=None) -> bool:
    ident = ident or get(create=False)
    return bool(ident and ident.next_request_kid and ident.next_request_private_key and ident.next_delegation_kid
                and ident.next_delegation_private_key)


def stage_next_keys(by=None):
    """Rotation without an outage, step 1: create the next request and
    delegation key pairs. They are listed in the peers-file entry next to the
    current ones (Rem0te accepts every listed key) but nothing signs with them
    until `promote_next_keys`."""
    from audit.models import AuditLog
    from integrations.models import Rem0teIdentity
    with transaction.atomic():
        ident = get(create=False)
        if ident is None or not has_keys(ident):
            raise IdentityError('Generate the first keys before staging new ones.')
        ident = Rem0teIdentity.objects.select_for_update().get(pk=ident.pk)
        if has_next_keys(ident):
            raise IdentityError('New keys are already staged: switch to them or discard them first.')
        ident.next_request_kid, ident.next_request_private_key = _kid('req'), protocol.generate_private_key_pem()
        ident.next_delegation_kid, ident.next_delegation_private_key = _kid('del'), protocol.generate_private_key_pem()
        ident.next_staged_at = timezone.now()
        ident.save()
    AuditLog.log(user=by, action='update', object_type='rem0te_identity', object_id=ident.pk,
                 object_repr='ClientSt0r Rem0te identity',
                 description=f'Staged next Rem0te keys (request {ident.next_request_kid}, delegation '
                             f'{ident.next_delegation_kid}); the current keys still sign',
                 extra_data={'next_request_kid': ident.next_request_kid,
                             'next_delegation_kid': ident.next_delegation_kid})
    return ident


def promote_next_keys(by=None):
    """Step 2, once Rem0te was restarted with the entry listing both: sign with
    the staged keys. The old public keys may then leave the peers file."""
    from audit.models import AuditLog
    from integrations.models import Rem0teIdentity
    with transaction.atomic():
        ident = get(create=False)
        if ident is None or not has_next_keys(ident):
            raise IdentityError('No keys are staged.')
        ident = Rem0teIdentity.objects.select_for_update().get(pk=ident.pk)
        old = (ident.request_kid, ident.delegation_kid)
        ident.request_kid, ident.request_private_key = ident.next_request_kid, ident.next_request_private_key
        ident.delegation_kid, ident.delegation_private_key = (ident.next_delegation_kid,
                                                              ident.next_delegation_private_key)
        ident.next_request_kid = ident.next_request_private_key = ''
        ident.next_delegation_kid = ident.next_delegation_private_key = ''
        ident.next_staged_at = None
        ident.rotated_at = timezone.now()
        ident.save()
    AuditLog.log(user=by, action='update', object_type='rem0te_identity', object_id=ident.pk,
                 object_repr='ClientSt0r Rem0te identity',
                 description=f'Switched to the staged Rem0te keys (request {ident.request_kid}, delegation '
                             f'{ident.delegation_kid}); retired {old[0]}, {old[1]}',
                 extra_data={'request_kid': ident.request_kid, 'delegation_kid': ident.delegation_kid,
                             'retired': list(old)})
    return ident


def discard_next_keys(by=None):
    from audit.models import AuditLog
    ident = get(create=False)
    if ident is None or not has_next_keys(ident):
        return ident
    kids = (ident.next_request_kid, ident.next_delegation_kid)
    ident.next_request_kid = ident.next_request_private_key = ''
    ident.next_delegation_kid = ident.next_delegation_private_key = ''
    ident.next_staged_at = None
    ident.save()
    AuditLog.log(user=by, action='update', object_type='rem0te_identity', object_id=ident.pk,
                 object_repr='ClientSt0r Rem0te identity', description=f'Discarded staged Rem0te keys {kids[0]}, '
                                                                        f'{kids[1]}')
    return ident


def validate_base_url(url: str) -> str:
    """'' if ok, else why not. https, or http on loopback (the lab)."""
    try:
        parts = urlsplit((url or '').strip())
    except ValueError:
        return 'Not a URL.'
    if parts.username or parts.password:
        return 'The address must not contain credentials.'
    if parts.query or parts.fragment:
        return 'The address must not have a query or fragment.'
    if parts.scheme == 'https' and parts.hostname:
        return ''
    if parts.scheme == 'http' and (parts.hostname or '') in LOOPBACK:
        return ''
    return 'Use https (plain http only on loopback, for a lab).'


def update(ident, *, peer_id=None, audience=None, public_base_url=None, by=None):
    from audit.models import AuditLog
    changes = {}
    if peer_id is not None:
        peer_id = peer_id.strip()
        if not PEER_ID_RE.match(peer_id):
            raise IdentityError('The peer id may use letters, digits, ".", "-" and "_" (at most 64).')
        changes['peer_id'] = peer_id
    if audience is not None:
        audience = audience.strip()
        if not (1 <= len(audience) <= 256) or protocol_controls(audience):
            raise IdentityError('The audience must be 1–256 printable characters.')
        changes['audience'] = audience
    if public_base_url is not None:
        public_base_url = public_base_url.strip().rstrip('/')
        problem = validate_base_url(public_base_url)
        if problem:
            raise IdentityError(problem)
        changes['public_base_url'] = public_base_url
    for k, v in changes.items():
        setattr(ident, k, v)
    if changes:
        ident.save()
        AuditLog.log(user=by, action='update', object_type='rem0te_identity', object_id=ident.pk,
                     object_repr='ClientSt0r Rem0te identity',
                     description='ClientSt0r Rem0te identity changed: ' + ', '.join(sorted(changes)),
                     extra_data=changes)
    return ident


def protocol_controls(s: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7f for c in s)


def urls(ident=None) -> dict:
    ident = ident or get(create=False)
    base = (ident.public_base_url if ident else '') or ''
    if not base:
        return {'inference': '', 'events': ''}
    return {'inference': base + reverse('integration_api:inference'),
            'events': base + reverse('integration_api:events')}


def request_key_id(ident) -> str:
    return f'{ident.peer_id}/{ident.request_kid}'


def configured(ident=None) -> str:
    """'' when ClientSt0r's side is complete, else what is missing."""
    ident = ident or get(create=False)
    if ident is None or not has_keys(ident):
        return "ClientSt0r's Rem0te keys have not been generated yet."
    if not ident.audience:
        return "ClientSt0r's audience (Rem0te's peerAudience) is not set."
    if not ident.public_base_url:
        return 'The address Rem0te reaches ClientSt0r at is not set.'
    return ''


def public_view(ident=None) -> Optional[dict]:
    """Everything an administrator may see and copy. No private material."""
    ident = ident or get(create=False)
    if ident is None:
        return None
    out = {'peer_id': ident.peer_id, 'audience': ident.audience, 'public_base_url': ident.public_base_url,
           'has_keys': has_keys(ident), 'urls': urls(ident), 'rotated_at': ident.rotated_at,
           'missing': configured(ident)}
    if has_keys(ident):
        for which in ('request', 'delegation'):
            pem = protocol.public_pem(getattr(ident, f'{which}_private_key'))
            out[which] = {'kid': getattr(ident, f'{which}_kid'), 'public_key_pem': pem,
                          'fingerprint': protocol.fingerprint(pem)}
    out['next'] = None
    if has_keys(ident) and has_next_keys(ident):
        out['next'] = {'staged_at': ident.next_staged_at}
        for which in ('request', 'delegation'):
            pem = protocol.public_pem(getattr(ident, f'next_{which}_private_key'))
            out['next'][which] = {'kid': getattr(ident, f'next_{which}_kid'), 'public_key_pem': pem,
                                  'fingerprint': protocol.fingerprint(pem)}
    return out


def peer_entry(connection=None, model_profiles=None) -> Optional[dict]:
    """ClientSt0r's entry for Rem0te's peers file (peers[]). `audience` is
    Rem0te's own audience, from the connection; the rest is ClientSt0r's."""
    view = public_view()
    if not view or not view['has_keys']:
        return None
    rem0te_audience = ''
    if connection is not None:
        from .pairing import settings as rem0te_settings
        rem0te_audience = rem0te_settings(connection)['rem0te_audience']
    keys = {w: [{'kid': view[w]['kid'], 'publicKeyPem': view[w]['public_key_pem']}] for w in ('request', 'delegation')}
    if view.get('next'):
        for w in ('request', 'delegation'):
            keys[w].append({'kid': view['next'][w]['kid'], 'publicKeyPem': view['next'][w]['public_key_pem']})
    return {
        'id': view['peer_id'],
        'audience': rem0te_audience or 'rem0te:<your-rem0te-host>',
        'peerAudience': view['audience'] or 'clientst0r:<your-clientst0r-host>',
        'requestKeys': keys['request'],
        'delegationKeys': keys['delegation'],
        'inferenceUrl': view['urls']['inference'] or '<https://clientst0r.example.com>/api/integration/v1/inference',
        'eventsUrl': view['urls']['events'] or '<https://clientst0r.example.com>/api/integration/v1/events',
        'modelProfiles': list(model_profiles or []) or ['<profile>'],
        'clientCertSha256': [],
    }


def peer_entry_json(connection=None, model_profiles=None) -> str:
    entry = peer_entry(connection, model_profiles)
    return json.dumps(entry, indent=2) if entry else ''


def request_signer(ident=None):
    ident = ident or get(create=False)
    if not has_keys(ident):
        raise IdentityError("ClientSt0r's Rem0te keys have not been generated yet.")
    return protocol.load_private_key(ident.request_private_key)


def delegation_signer(ident=None):
    ident = ident or get(create=False)
    if not has_keys(ident):
        raise IdentityError("ClientSt0r's Rem0te keys have not been generated yet.")
    return protocol.load_private_key(ident.delegation_private_key)
