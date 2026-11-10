"""
Test helpers: an in-process Rem0te that checks ClientSt0r's requests the way
Rem0te does (Ed25519 request signature over rem0te-http-req-v1 with its
audience, ±120 s, single-use nonce, delegation JWS with req_sha256 over the
canonical body) and answers in the contract's shapes; and a Rem0te signing
key for events and inbound requests. Never imported by the application.
The real Rem0te is exercised by scripts/e2e/cross_peer/.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from requests.models import Response
from requests.structures import CaseInsensitiveDict

from . import identity, pairing, protocol, schema

REM0TE_AUDIENCE = 'rem0te:test'
CS_AUDIENCE = 'clientst0r:test'
PEER_ID = 'clientst0r-test'
KID = 'rem0te-test-1'
API = '/api/integration/v1'

_KEY = None


def rem0te_key():
    global _KEY
    if _KEY is None:
        _KEY = protocol.load_private_key(protocol.generate_private_key_pem())
    return _KEY


def rem0te_public_pem():
    return protocol.public_pem(rem0te_key())


def setup_identity(base='https://cs.example.com'):
    ident = identity.generate_keys()
    identity.update(ident, peer_id=PEER_ID, audience=CS_AUDIENCE, public_base_url=base)
    return identity.get()


def make_connection(org, name='Rem0te', enabled=True, base_url='https://rem0te.example.com', **extra):
    from integrations.models import RMMConnection
    from integrations.ticket_rmm import ENABLED, LOCATION
    conn = RMMConnection.objects.create(organization=org, provider_type='rem0te', name=name, base_url=base_url,
                                        customer_scope=RMMConnection.CUSTOMER_SCOPE_SINGLE)
    conn.set_credentials({'api_key': 'rk_test'})
    conn.field_mappings = dict({ENABLED: enabled, LOCATION: 'hosted', pairing.AUTH: 'ed25519',
                                pairing.AUDIENCE: REM0TE_AUDIENCE,
                                pairing.SIGNING_KEYS: [{'kid': KID, 'public_key_pem': rem0te_public_pem()}]},
                               **extra)
    conn.save()
    return conn


def sign_event(event, alert=False, key=None, kid=KID):
    msg = (protocol.alert_event_signing_string if alert else protocol.event_signing_string)(event)
    return {'alg': 'Ed25519', 'kid': kid, 'sig': protocol.sign(key or rem0te_key(), msg)}


def signed_post(client, path, body, key=None, kid=KID, audience=CS_AUDIENCE, ts=None, nonce=None):
    """POST to ClientSt0r as Rem0te does. Returns the Django test response."""
    raw = protocol.canonical_json(body).encode() if not isinstance(body, bytes) else body
    h = protocol.request_headers(key or rem0te_key(), f'rem0te/{kid}', audience, 'POST', path, raw,
                                 timestamp=ts, nonce=nonce)
    return client.post(path, raw, content_type='application/json',
                       **{'HTTP_' + k.upper().replace('-', '_'): v for k, v in h.items()})


def capabilities(version='0.29.0', **over):
    doc = {
        'contract': protocol.CONTRACT, 'rem0te_version': version, 'audience': REM0TE_AUDIENCE, 'peer_id': PEER_ID,
        'features': {'ticket_analysis': True, 'model_comparison': True, 'endpoint_evidence': ['inventory', 'heartbeat'],
                     'actions': ['windows.service.start@1'], 'alerts': True},
        'model_profiles': [],
        'limits': {'max_model_profiles': 3, 'max_job_ttl_seconds': 86400, 'max_delegation_ttl_seconds': 300,
                   'max_request_bytes': 524288},
        'signing_keys': [{'kid': KID, 'alg': 'Ed25519', 'public_key_pem': rem0te_public_pem()}],
    }
    doc.update(over)
    return doc


def _iso_now():
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())


class FakeRem0te:
    """Patch requests.Session.request. `fail` = callable(method, path) →
    None | ('unreachable',) | (status, code, message) to inject errors."""

    def __init__(self):
        self.calls = []
        self.nonces = set()
        self.caps = capabilities()
        self.jobs = {}
        self.proposals = {}
        self.links = {}
        self.alert_events = []
        self.fail = None
        self.mapped_orgs = None  # None = every organization is mapped

    @contextmanager
    def running(self):
        with patch.object(requests.Session, 'request', autospec=True, side_effect=self._handle):
            yield self

    def _respond(self, status, body=None, headers=None):
        r = Response()
        r.status_code = status
        r._content = b'' if body is None else json.dumps(body).encode()
        r._content_consumed = True
        r.headers = CaseInsensitiveDict({'Content-Type': 'application/json',
                                         'Date': time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime()),
                                         **(headers or {})})
        return r

    def _err(self, status, code, message):
        return self._respond(status, {'error': {'code': code, 'message': message}})

    def _handle(self, session, method, url, data=None, headers=None, **kw):
        parts = urlsplit(url)
        path = parts.path + (f'?{parts.query}' if parts.query else '')
        route = parts.path[len(API):] if parts.path.startswith(API) else parts.path
        body_raw = data or b''
        self.calls.append((method, route, body_raw, dict(headers or {})))
        if self.fail:
            f = self.fail(method, route)
            if f == ('unreachable',):
                raise requests.ConnectionError('refused')
            if f:
                return self._err(*f)
        h = {k.lower(): v for k, v in (headers or {}).items()}
        ident = identity.get(create=False)
        try:
            key_id, ts, nonce, sig = (h['rem0te-key-id'], h['rem0te-timestamp'], h['rem0te-nonce'],
                                      h['rem0te-signature'])
        except KeyError:
            return self._err(401, 'UNAUTHENTICATED', 'Missing or malformed signature headers')
        if key_id != f'{ident.peer_id}/{ident.request_kid}':
            return self._err(401, 'UNAUTHENTICATED', 'Unknown key')
        if abs(time.time() - int(ts)) > 120:
            return self._err(401, 'UNAUTHENTICATED', 'Timestamp outside the allowed window')
        msg = protocol.request_signing_string(REM0TE_AUDIENCE, method, path, ts, nonce, protocol.sha256_hex(body_raw))
        if not protocol.verify(protocol.load_public_key(protocol.public_pem(ident.request_private_key)), msg, sig):
            return self._err(401, 'UNAUTHENTICATED', 'Request signature invalid')
        if nonce in self.nonces:
            return self._err(401, 'REPLAYED', 'Nonce already used')
        self.nonces.add(nonce)
        body = json.loads(body_raw) if body_raw else None
        claims = None
        if 'rem0te-delegation' in h:
            keys = {ident.delegation_kid: protocol.load_public_key(protocol.public_pem(ident.delegation_private_key))}
            try:
                claims = protocol.verify_jws(h['rem0te-delegation'], keys)
            except protocol.ProtocolError as e:
                return self._err(401, 'DELEGATION_INVALID', str(e))
            if claims['aud'] != REM0TE_AUDIENCE or claims['iss'] != ident.peer_id \
                    or claims['exp'] - claims['iat'] > 300:
                return self._err(401, 'DELEGATION_INVALID', 'claims')
            if body is not None and claims.get('req_sha256') != protocol.sha256_hex(protocol.canonical_json(body)):
                return self._err(401, 'DELEGATION_INVALID', 'req_sha256 mismatch')
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        org = (body or {}).get('organization_id') or q.get('organization_id')
        if org and self.mapped_orgs is not None and org not in self.mapped_orgs:
            return self._err(403, 'FORBIDDEN', 'Organization not mapped')
        return self._route(method, route, body, q, claims)

    def _route(self, method, route, body, q, claims):
        if method == 'GET' and route == '/capabilities':
            return self._respond(200, self.caps)
        if method == 'GET' and route == '/alerts/events':
            after = int(q.get('after', 0))
            evs = [e for e in self.alert_events if e['alert_event']['organization_id'] == q['organization_id']
                   and e['alert_event']['sequence'] > after][:100]
            last = max([e['alert_event']['sequence'] for e in self.alert_events] or [0])
            return self._respond(200, {'organization_id': q['organization_id'], 'last_sequence': last,
                                       'events': evs})
        if method == 'POST' and route == '/jobs':
            if claims is None or claims['scope'] != 'ticket_analysis:submit':
                return self._err(401, 'DELEGATION_INVALID', 'scope')
            errs = schema.errors('job-request', body)
            if errs:
                return self._err(400, 'INVALID_REQUEST', errs[0])
            sha = protocol.sha256_hex(protocol.canonical_json(body))
            prior = self.jobs.get(body['idempotency_key'])
            if prior:
                if prior['payload_sha256'] != sha:
                    return self._err(409, 'IDEMPOTENCY_CONFLICT', 'different payload')
                return self._respond(200, prior, {'idempotent-replayed': 'true'})
            now = _iso_now()
            job = {'contract': protocol.CONTRACT, 'job_id': str(uuid.uuid4()), 'status': 'queued',
                   'organization_id': body['organization_id'], 'technician_id': body['technician_id'],
                   'ticket': {'id': body['ticket']['id'], 'revision': body['ticket']['revision']},
                   'endpoint_id': (body.get('endpoint') or {}).get('rem0te_endpoint_id'),
                   'model_profiles': body['model_profiles'], 'correlation_id': body['correlation_id'],
                   'idempotency_key': body['idempotency_key'], 'payload_sha256': sha, 'created_at': now,
                   'updated_at': now, 'expires_at': body['expires_at'], 'completed_at': None,
                   'last_event_sequence': 1,
                   'runs': [{'model_profile': p, 'status': 'pending', 'error_code': None}
                            for p in body['model_profiles']], 'error': None, 'result': None}
            self.jobs[body['idempotency_key']] = job
            return self._respond(202, job)
        if method == 'GET' and route.startswith('/jobs/') and route.endswith('/events'):
            return self._respond(200, {'job_id': route.split('/')[2], 'last_event_sequence': 0, 'events': []})
        if method == 'POST' and route.startswith('/alerts/') and route.endswith('/ticket'):
            alert_id = route.split('/')[2]
            errs = schema.errors('alert-ticket-link', body)
            if errs:
                return self._err(400, 'INVALID_REQUEST', errs[0])
            have = self.links.get(alert_id)
            if have and have['ticket_id'] != body['ticket_id']:
                return self._err(409, 'TICKET_ALREADY_LINKED', 'another ticket')
            self.links[alert_id] = body
            return self._respond(200, {'alert_id': alert_id, 'ticket': {'id': body['ticket_id'],
                                                                        'url': body['ticket_url']}})
        if method == 'POST' and route == '/action-proposals':
            if claims is None or claims['scope'] != 'actions:propose':
                return self._err(401, 'DELEGATION_INVALID', 'scope')
            errs = schema.errors('action-proposal-request', body)
            if errs:
                return self._err(400, 'INVALID_REQUEST', errs[0])
            key = body['idempotency_key']
            if key in self.proposals:
                return self._respond(200, self.proposals[key], {'idempotent-replayed': 'true'})
            now = _iso_now()
            job_id = uuid.uuid4().hex
            p = {'contract': protocol.CONTRACT, 'idempotency_key': key, 'job_id': job_id,
                 'status': 'awaiting_approval', 'status_reason': None,
                 'rem0te_endpoint_id': body['rem0te_endpoint_id'], 'action': body['action'],
                 'origin': body['origin'], 'ticket_ref': body['ticket_ref'], 'risk': 'low',
                 'approvals_required': 1, 'customer_signoff': False,
                 'approval_url': f'https://approve.example.com/approve/{job_id}', 'plan_digest': 'a' * 64,
                 'window': {'not_before': now, 'not_after': now}, 'outcome': None, 'observed': None,
                 'created_at': now, 'updated_at': now}
            self.proposals[key] = p
            return self._respond(201, p)
        if method == 'GET' and route.startswith('/action-proposals/'):
            job_id = route.split('/')[2]
            for p in self.proposals.values():
                if p['job_id'] == job_id:
                    return self._respond(200, p)
            return self._err(404, 'NOT_FOUND', 'no such proposal')
        return self._err(404, 'NOT_FOUND', f'no route {method} {route}')

    # -- helpers for tests -------------------------------------------------
    def job_event(self, job_doc, seq, etype, status, result=None, runs_status=None):
        snap = dict(job_doc, status=status, last_event_sequence=seq, result=result)
        if runs_status:
            snap['runs'] = [dict(r, status=runs_status) for r in job_doc['runs']]
        event = {'contract': protocol.CONTRACT, 'event_id': str(uuid.uuid4()), 'sequence': seq, 'type': etype,
                 'occurred_at': _iso_now(), 'peer_id': PEER_ID, 'organization_id': job_doc['organization_id'],
                 'job_id': job_doc['job_id'], 'correlation_id': job_doc['correlation_id'], 'job': snap}
        return {'event': event, 'signature': sign_event(event)}

    def alert_event(self, org_id, seq, etype='alert.raised', alert_id='cmalert0000000000000000001',
                    endpoint='cmendpoint00000000000000001', computer='FRONTDESK-01', severity='critical',
                    state='open'):
        alert = {'alert_id': alert_id, 'monitor': 'spooler', 'kind': 'SERVICE_STOPPED', 'severity': severity,
                 'state': 'resolved' if etype == 'alert.resolved' else state,
                 'title': f'{computer}: service Spooler is Stopped', 'rem0te_endpoint_id': endpoint,
                 'computer_name': computer, 'site_name': None, 'first_seen_at': _iso_now(),
                 'last_seen_at': _iso_now(), 'occurrences': seq,
                 'resolved_at': _iso_now() if etype == 'alert.resolved' else None, 'outage_alert_id': None,
                 'ticket': None}
        event = {'contract': protocol.CONTRACT, 'event_id': str(uuid.uuid4()), 'sequence': seq, 'type': etype,
                 'occurred_at': _iso_now(), 'peer_id': PEER_ID, 'organization_id': org_id, 'alert': alert}
        signed = {'alert_event': event, 'signature': sign_event(event, alert=True)}
        self.alert_events.append(signed)
        return signed
