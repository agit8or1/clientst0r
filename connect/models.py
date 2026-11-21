"""
Agit8or Connect — Clientst0r's side of the app-to-app protocol.

One Clientst0r installation serves exactly one MSP, so InstallationIdentity
IS that MSP's identity towards other apps. A Connection is one pairing with
one installation of another app; Clientst0r customer Organizations are mapped
to the other app's tenants only through TenantGrant rows of that connection.

Secrets: the only secret stored here is each connection's own Ed25519
private key (ConnectionKey.private_key), sealed with AES-256-GCM under
APP_MASTER_KEY and bound to the row (AAD "connect.ConnectionKey.private_key#
<uuid>"; the uuid exists before the value is sealed and keys are never moved
between rows). Pairing codes are stored only as an HMAC. Nothing here stores
an access token: tokens are short-lived JWTs verified, never looked up.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from vault.secret_fields import SealedTextField, seal, unseal


class InstallationIdentity(models.Model):
    """This installation (= this MSP) as other apps see it. One row, created
    once; the installation id never changes."""
    installation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    display_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    kill_switch_engaged = models.BooleanField(default=False)
    kill_switch_at = models.DateTimeField(null=True, blank=True)
    kill_switch_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    # Source policy (DESIGN.md §5.5): bumped inside every SourceRule change, so
    # each worker reloads its compiled rules on the next request.
    connect_policy_version = models.PositiveBigIntegerField(default=1)
    # Observe period for connections that existed before source rules shipped
    # (DESIGN.md §13.2). Set only by the migration; never extended.
    source_observe_until = models.DateTimeField(null=True, blank=True)
    source_observe_connections = models.JSONField(default=list, blank=True)
    # Quick Connect (protocol 1.1, DESIGN.md §2.2, §6.1): this installation's
    # own egress addresses as other applications see them ([{net, note}],
    # canonical networks), declared by an administrator and never derived
    # from a browser address; and whether the browser-mediated bootstrap is
    # offered at all (off by default, on top of AGIT8OR_CONNECT_ENABLED).
    egress_addresses = models.JSONField(default=list, blank=True)
    qc_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'connect_installation'

    def __str__(self):
        return f'{self.display_name or "Clientst0r"} ({self.installation_id})'


class Connection(models.Model):
    PENDING_PAIRING = 'pending_pairing'
    AWAITING_REMOTE = 'awaiting_remote_approval'
    AWAITING_LOCAL = 'awaiting_local_approval'
    AWAITING_SECOND = 'awaiting_second_approval'
    ACTIVE = 'active'
    SUSPENDED = 'suspended'
    REVOKED = 'revoked'
    FAILED = 'failed'
    SECURITY_BLOCKED = 'security_blocked'
    # Increment C3 (DESIGN.md §4.1): after both sides approved permissions and
    # customers, each side approves the other side's source addresses
    # (awaiting_network), then a connection test must pass (testing) before
    # commit_connection() makes it active. Nothing becomes active otherwise.
    AWAITING_NETWORK = 'awaiting_network'
    TESTING = 'testing'
    STATES = [
        (PENDING_PAIRING, 'Pairing'),
        (AWAITING_REMOTE, 'Waiting for the other application to approve'),
        (AWAITING_LOCAL, 'Waiting for approval here'),
        (AWAITING_SECOND, 'Waiting for a second administrator'),
        (AWAITING_NETWORK, 'Awaiting network authorization'),
        (TESTING, 'Testing'),
        (ACTIVE, 'Connected'),
        (SUSPENDED, 'Suspended'),
        (REVOKED, 'Disconnected'),
        (FAILED, 'Pairing failed'),
        (SECURITY_BLOCKED, 'Security Blocked'),
    ]
    OUTBOUND, INBOUND = 'outbound', 'inbound'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False,
                          help_text='Our connection id; the client_id the other app uses at our token endpoint.')
    direction = models.CharField(max_length=10, choices=[(OUTBOUND, 'We connected to them'),
                                                         (INBOUND, 'They connected to us')])
    state = models.CharField(max_length=30, choices=STATES, default=PENDING_PAIRING, db_index=True)

    remote_app_type = models.CharField(max_length=64)
    remote_installation_id = models.CharField(max_length=128, db_index=True)
    remote_display_name = models.CharField(max_length=200, blank=True)
    remote_app_version = models.CharField(max_length=64, blank=True)
    remote_protocol_version = models.CharField(max_length=8, default='1')
    base_url = models.URLField(max_length=500, help_text='The other app\'s discovery address.')
    remote_endpoints = models.JSONField(default=dict, blank=True)
    remote_catalog = models.JSONField(default=list, blank=True)
    remote_connection_id = models.CharField(max_length=128, blank=True,
                                            help_text='The other app\'s id for this connection (our client_id there).')
    remote_jwks = models.JSONField(default=dict, blank=True, help_text='Public keys of the other app for this '
                                                                         'connection (never private material).')
    remote_jwks_fetched_at = models.DateTimeField(null=True, blank=True)

    # Network / TLS (Advanced settings).
    allow_private_network = models.BooleanField(
        default=False, help_text='Allow an internal address (private IP, VPN, private DNS). Cloud metadata '
                                 'addresses stay blocked.')
    tls_ca_bundle = models.TextField(blank=True, help_text='PEM CA certificates to trust for this connection '
                                                           'only (private CA). Replaces the public CA list.')
    tls_client_cert = models.TextField(blank=True, help_text='Optional client certificate (PEM) for mutual TLS.')
    tls_client_key = SealedTextField(blank=True, help_text='Private key of the mutual-TLS client certificate.')

    # Permissions, both directions.
    inbound_scopes = models.JSONField(default=list, blank=True, help_text='What the other app may do here.')
    peer_requested_scopes = models.JSONField(default=list, blank=True)
    requested_outbound_scopes = models.JSONField(default=list, blank=True)
    outbound_scopes = models.JSONField(default=list, blank=True, help_text='What we may do in the other app.')
    inbound_event_types = models.JSONField(default=list, blank=True)
    remote_tenant_grants = models.JSONField(default=list, blank=True,
                                            help_text='What the other app reported it granted us (display only).')

    # Pairing transcript.
    pairing_request_id = models.CharField(max_length=128, blank=True)
    pairing_request_jti = models.CharField(max_length=128, blank=True)
    pairing_request_jws = models.TextField(blank=True)
    sas = models.CharField(max_length=16, blank=True)
    proposed_tenants = models.JSONField(default=list, blank=True)

    # Health.
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    auth_failure_count = models.PositiveIntegerField(default=0)
    last_test = models.JSONField(default=dict, blank=True)
    # Source address of the last authenticated request (inbound binding check).
    last_source_ip = models.GenericIPAddressField(null=True, blank=True)
    last_source_at = models.DateTimeField(null=True, blank=True)
    # Security Blocked evidence (DESIGN.md §2.1, §7.3): never cleared, only
    # superseded by a later block; copied to the audit chain.
    security_block_code = models.CharField(max_length=40, blank=True)
    security_block_at = models.DateTimeField(null=True, blank=True)
    security_block_detail = models.JSONField(default=dict, blank=True)

    # Health while active and the monitor's durable schedule (Quick Connect
    # increment D; DESIGN.md §2.1, §4.2, §8). One displayed status comes from
    # connect.status.display(); these fields only feed it.
    HEALTH_CONNECTED, HEALTH_DEGRADED, HEALTH_OFFLINE = 'connected', 'degraded', 'offline'
    CIRCUIT_CLOSED, CIRCUIT_OPEN, CIRCUIT_HALF_OPEN = 'closed', 'open', 'half_open'
    health = models.CharField(max_length=10, blank=True, choices=[
        (HEALTH_CONNECTED, 'Connected'), (HEALTH_DEGRADED, 'Degraded'), (HEALTH_OFFLINE, 'Offline')])
    health_dims = models.JSONField(default=dict, blank=True,
                                   help_text='{transport, tls, authenticated, authorised, operational} -> '
                                             '{ok, since, last_ok, last_fail, code}')
    consecutive_ok = models.PositiveSmallIntegerField(default=0)
    consecutive_fail = models.PositiveSmallIntegerField(default=0)
    next_check_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_check_at = models.DateTimeField(null=True, blank=True)
    retry_step = models.PositiveSmallIntegerField(default=0, help_text='Index into the backoff ladder.')
    circuit = models.CharField(max_length=10, default=CIRCUIT_CLOSED, choices=[
        (CIRCUIT_CLOSED, 'Closed'), (CIRCUIT_OPEN, 'Open'), (CIRCUIT_HALF_OPEN, 'Half open')])
    monitor_interval_s = models.PositiveSmallIntegerField(default=60)
    # A connection in testing is retested automatically until this time
    # (the other side may not have finished its own approval yet).
    retest_until = models.DateTimeField(null=True, blank=True)
    # Last authorised call this installation completed TO the other
    # application (qc_probe peer_reached_at, diagnostics step 15).
    last_outbound_ok_at = models.DateTimeField(null=True, blank=True)
    # Last displayed status seen (connect.status.display key), and the
    # problem status an alert was sent for (cleared by the recovery notice).
    status_key = models.CharField(max_length=30, blank=True)
    alerted_status = models.CharField(max_length=30, blank=True)
    # Alerts (Quick Connect increment E; DESIGN.md §10). A mute is time
    # limited and audited; it silences Degraded / Offline / Suspended /
    # Revoked notices and their tickets, never Security Blocked (that still
    # e-mails, raises the system warning and counts on the bell).
    alert_mute_until = models.DateTimeField(null=True, blank=True)
    alert_mute_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+')
    alert_mute_reason = models.CharField(max_length=200, blank=True)
    # Opt-in: one PSA ticket per incident (opened on the first transition to
    # Offline or Security Blocked, noted on later transitions and on
    # recovery), filed under this customer record, which is also the
    # organization whose webhooks receive connected_app.status_changed.
    alert_ticket = models.BooleanField(default=False)
    alert_organization = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='+')
    # qc-diagnostics/1 probe of the other application, learnt from its
    # discovery document by a diagnostics run (same origin, advertised).
    # When set, the light health check calls it instead of v1 POST test.
    remote_probe_url = models.CharField(max_length=500, blank=True)

    # Rotation.
    rotation_interval_days = models.PositiveIntegerField(default=90)
    rotation_overlap_hours = models.PositiveIntegerField(default=24)
    next_rotation_at = models.DateTimeField(null=True, blank=True)
    last_rotation_at = models.DateTimeField(null=True, blank=True)
    last_rotation_error = models.CharField(max_length=300, blank=True)

    tokens_not_before = models.DateTimeField(null=True, blank=True,
                                             help_text='Access tokens issued before this are refused.')
    suspended_reason = models.CharField(max_length=40, blank=True)
    # '' = v1 code pairing; '1.1' = Quick Connect (qc-bootstrap/1). After the
    # exchange a Quick Connect connection is an ordinary v1 connection.
    qc_revision = models.CharField(max_length=8, blank=True)
    # Hard deadline of a Quick Connect attempt: the reaper rolls it back after
    # this (DESIGN.md §6.5), removing every rule it created.
    qc_attempt_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')

    class Meta:
        db_table = 'connect_connections'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.remote_display_name or self.remote_app_type} ({self.get_state_display()})'

    @property
    def is_active(self):
        return self.state == self.ACTIVE

    def endpoint(self, name, **fmt):
        url = (self.remote_endpoints or {}).get(name, '')
        for k, v in fmt.items():
            url = url.replace('{' + k + '}', str(v))
        return url

    def client_key_pem(self) -> str:
        field = self._meta.get_field('tls_client_key')
        return field.unseal_text(self.tls_client_key) if self.tls_client_key else ''


class ConnectionKey(models.Model):
    """One of OUR Ed25519 keys for one connection. kid = RFC 7638 thumbprint."""
    STAGED, ACTIVE, RETIRING, RETIRED, FAILED = 'staged', 'active', 'retiring', 'retired', 'failed'
    STATES = [(s, s.title()) for s in (STAGED, ACTIVE, RETIRING, RETIRED, FAILED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='keys')
    kid = models.CharField(max_length=64)
    state = models.CharField(max_length=10, choices=STATES, default=ACTIVE)
    public_jwk = models.JSONField()
    private_key = SealedTextField(bind_row=True, blank=True,
                                  help_text='PKCS#8 PEM, sealed to this row. Wiped when the key is retired.')
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retire_after = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connect_keys'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['connection', 'kid'], name='connect_key_unique_kid')]

    def __str__(self):
        return f'{self.kid[:12]}… ({self.state})'

    def _aad(self):
        return self._meta.get_field('private_key').row_aad(self.pk)

    def set_private_pem(self, pem: str):
        self.private_key = seal(pem, self._aad()) if pem else ''

    def private_pem(self) -> str:
        return unseal(self.private_key, self._aad()) if self.private_key else ''

    @property
    def fingerprint(self):
        return ' '.join(self.kid[i:i + 4] for i in range(0, len(self.kid), 4))


class PairingInvitation(models.Model):
    """A code an administrator here reads out to the other app's
    administrator. Only an HMAC of the code is stored."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    used_at = models.DateTimeField(null=True, blank=True)
    burned_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'connect_invitations'
        ordering = ['-created_at']

    @property
    def is_open(self):
        return self.used_at is None and self.burned_at is None and self.expires_at > timezone.now()

    @property
    def status(self):
        if self.used_at:
            return 'used'
        if self.burned_at:
            return 'locked'
        return 'open' if self.expires_at > timezone.now() else 'expired'


class PairingRequest(models.Model):
    """An inbound pairing request awaiting a decision here."""
    PENDING, AWAITING_SECOND, APPROVED, REJECTED, EXPIRED = (
        'pending', 'awaiting_second_approval', 'approved', 'rejected', 'expired')
    STATUSES = [(PENDING, 'Waiting for approval'), (AWAITING_SECOND, 'Waiting for a second administrator'),
                (APPROVED, 'Approved'), (REJECTED, 'Rejected'), (EXPIRED, 'Expired')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False,
                          help_text='Public request id the other app polls.')
    invitation = models.ForeignKey(PairingInvitation, on_delete=models.SET_NULL, null=True, related_name='requests')
    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, related_name='pairing_request')
    status = models.CharField(max_length=30, choices=STATUSES, default=PENDING)
    initiator_jwk = models.JSONField()
    result_jws = models.TextField(blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    protected_change_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'connect_pairing_requests'
        ordering = ['-created_at']


class TenantGrant(models.Model):
    """One Clientst0r customer Organization made reachable through one
    connection, under the other app's tenant id, for a subset of scopes."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='tenant_grants')
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    remote_tenant_id = models.CharField(max_length=128)
    remote_tenant_label = models.CharField(max_length=200, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')

    class Meta:
        db_table = 'connect_tenant_grants'
        ordering = ['organization__name']
        constraints = [
            models.UniqueConstraint(fields=['connection', 'remote_tenant_id'], name='connect_grant_unique_remote'),
            models.UniqueConstraint(fields=['connection', 'organization'], name='connect_grant_unique_org'),
        ]

    def __str__(self):
        return f'{self.organization} ↔ {self.remote_tenant_id}'


class ReplayRecord(models.Model):
    """One-time values (assertion / DPoP jti, event ids, pairing jti)."""
    namespace = models.CharField(max_length=16)
    key = models.CharField(max_length=255)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'connect_replay'
        constraints = [models.UniqueConstraint(fields=['namespace', 'key'], name='connect_replay_unique')]


class OutboundEvent(models.Model):
    QUEUED, DELIVERED, DEAD, CANCELLED = 'queued', 'delivered', 'dead', 'cancelled'
    STATUSES = [(QUEUED, 'Queued'), (DELIVERED, 'Delivered'), (DEAD, 'Failed (dead letter)'),
                (CANCELLED, 'Cancelled')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='outbound_events')
    tenant_grant = models.ForeignKey(TenantGrant, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    event_type = models.CharField(max_length=100)
    envelope = models.JSONField()
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    # Requeued from the failed list by an administrator (same id, so the
    # receiver still deduplicates); the age limit counts from here.
    requeued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connect_outbound_events'
        ordering = ['-created_at']


class DeliveryAttempt(models.Model):
    event = models.ForeignKey(OutboundEvent, on_delete=models.CASCADE, related_name='attempt_log')
    attempted_at = models.DateTimeField(auto_now_add=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    error = models.CharField(max_length=300, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'connect_delivery_attempts'
        ordering = ['-attempted_at']


class InboundEvent(models.Model):
    ACCEPTED, IGNORED = 'accepted', 'ignored'
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='inbound_events')
    event_id = models.CharField(max_length=64)
    event_type = models.CharField(max_length=100)
    tenant_grant = models.ForeignKey(TenantGrant, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    correlation_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=10, default=ACCEPTED)
    data = models.JSONField(default=dict, blank=True,
                            help_text='Event data, kept for the handler of its type (Phase 3).')
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'connect_inbound_events'
        ordering = ['-received_at']
        constraints = [models.UniqueConstraint(fields=['connection', 'event_id'], name='connect_inbound_dedup')]


class AppendOnlyError(Exception):
    pass


class _AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError('The Connect audit log is append-only.')

    def delete(self):
        raise AppendOnlyError('The Connect audit log is append-only.')


class ConnectAuditEvent(models.Model):
    """Append-only, hash-chained audit of every Connect operation.

    hash = SHA-256(canonical_json({"prev": prev_hash, "record": record()}))
    (agit8or_connect.audit). Rows refuse update and delete in the ORM; there
    is no admin registration and no change/delete permission.
    `manage.py connect_verify_audit_chain` re-computes the chain. No secrets
    and no customer content: ids, operation names, scopes and results."""
    seq = models.PositiveBigIntegerField(unique=True)
    ts_us = models.BigIntegerField()
    connection_id = models.CharField(max_length=64, blank=True, db_index=True)
    initiating_app = models.CharField(max_length=128, blank=True)
    tenant = models.CharField(max_length=128, blank=True)
    actor = models.CharField(max_length=160, blank=True, help_text='user:<id>:<username> or app:<installation>')
    operation = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    result = models.CharField(max_length=32)
    correlation_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    objects = _AppendOnlyQuerySet.as_manager()

    class Meta:
        db_table = 'connect_audit'
        ordering = ['-seq']
        default_permissions = ('view',)

    def record(self) -> dict:
        return {'seq': self.seq, 'ts_us': self.ts_us, 'operation': self.operation, 'result': self.result,
                'connection_id': self.connection_id, 'tenant': self.tenant, 'scopes': list(self.scopes or []),
                'actor': self.actor, 'initiating_app': self.initiating_app, 'correlation_id': self.correlation_id,
                'detail': self.detail or {}}

    @property
    def at(self):
        from datetime import datetime, timezone as dt_tz
        return datetime.fromtimestamp(self.ts_us / 1_000_000, tz=dt_tz.utc)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError('The Connect audit log is append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError('The Connect audit log is append-only.')


class ConnectChange(models.Model):
    """A staged change to Connect network policy (DESIGN.md §11): proposed with
    a server-side preview, approved (a second administrator through
    tech_access when it widens access), then applied in one transaction that
    bumps InstallationIdentity.connect_policy_version."""
    SOURCE_RULES, DESTINATION, PERMISSIONS = 'source_rules', 'destination', 'permissions'
    KINDS = [(SOURCE_RULES, 'Source rules'), (DESTINATION, 'Approved destination'),
             (PERMISSIONS, 'Permissions and customers')]
    STAGED, AWAITING_SECOND, APPLIED, REJECTED, EXPIRED, ROLLED_BACK = (
        'staged', 'awaiting_second', 'applied', 'rejected', 'expired', 'rolled_back')
    # Approved, applied only by commit_connection() after a passing test (a
    # new connection's source rules for the other side, C3).
    APPROVED = 'approved'
    STATUSES = [(STAGED, 'Staged'), (AWAITING_SECOND, 'Waiting for a second administrator'),
                (APPROVED, 'Approved — applied when the connection test passes'), (APPLIED, 'Applied'),
                (REJECTED, 'Rejected'), (EXPIRED, 'Expired'), (ROLLED_BACK, 'Rolled back')]

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='network_changes')
    kind = models.CharField(max_length=20, choices=KINDS, default=SOURCE_RULES)
    payload = models.JSONField(default=dict, blank=True)
    preview = models.JSONField(default=dict, blank=True)
    widening = models.BooleanField(default=False)
    fingerprint = models.CharField(max_length=64, blank=True)
    base_version = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUSES, default=STAGED, db_index=True)
    note = models.CharField(max_length=300, blank=True)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    protected_change_id = models.PositiveIntegerField(null=True, blank=True)
    rollback_of = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connect_changes'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_kind_display()} change #{self.pk} ({self.status})'


class SourceRule(models.Model):
    """One source-address rule for the Connect endpoints (DESIGN.md §5).

    Two layers: ``installation`` (one list for every Connect request) and
    ``connection`` (per connection; a pairing rule may first hang off an
    invitation and is linked to the connection the request creates). A
    request passes only if both layers allow it; a deny in either wins.
    Only ``temporary`` and ``active`` rows are ever evaluated; ``observed``
    rows record sources seen during the observe period and grant nothing."""
    INSTALLATION, CONNECTION = 'installation', 'connection'
    LAYERS = [(INSTALLATION, 'Installation'), (CONNECTION, 'Connection')]
    ALLOW, DENY = 'allow', 'deny'
    ACTIONS = [(ALLOW, 'Allow'), (DENY, 'Deny')]
    STAGED, TEMPORARY, ACTIVE, REMOVED, OBSERVED = 'staged', 'temporary', 'active', 'removed', 'observed'
    STATUSES = [(STAGED, 'Staged'), (TEMPORARY, 'Temporary'), (ACTIVE, 'Active'), (REMOVED, 'Removed'),
                (OBSERVED, 'Observed (not allowed)')]
    PAIRING, DISCOVERY, ALL = 'pairing', 'discovery', 'all'
    # After a Quick Connect exchange: only the v1 pairing-status poll, until
    # the attempt's deadline (the other side learns the outcome; C3).
    POLL = 'poll'
    PURPOSES = [(PAIRING, 'Pairing only'), (POLL, 'Pairing status only'), (DISCOVERY, 'Discovery only'),
                (ALL, 'Every Connect endpoint')]

    layer = models.CharField(max_length=15, choices=LAYERS)
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='source_rules')
    invitation = models.ForeignKey(PairingInvitation, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='source_rules')
    network = models.CharField(max_length=64)
    private = models.BooleanField(default=False, help_text='The administrator confirmed this is a private, '
                                                           'loopback or link-local address.')
    action = models.CharField(max_length=5, choices=ACTIONS, default=ALLOW)
    status = models.CharField(max_length=10, choices=STATUSES, default=STAGED, db_index=True)
    purpose = models.CharField(max_length=10, choices=PURPOSES, default=ALL)
    expires_at = models.DateTimeField(null=True, blank=True)
    description = models.CharField(max_length=200, blank=True)
    change = models.ForeignKey(ConnectChange, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='rules')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    observed_first_at = models.DateTimeField(null=True, blank=True)
    match_count = models.PositiveBigIntegerField(default=0)
    last_matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connect_source_rules'
        ordering = ['layer', 'action', 'network']
        indexes = [models.Index(fields=['status', 'layer'])]

    def __str__(self):
        return f'{self.get_action_display()} {self.network} ({self.layer}, {self.status})'

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at <= timezone.now())


class ApprovedDestination(models.Model):
    """Where this connection may reach the other application (DESIGN.md §2.2,
    §7): host, port, approved addresses (each ``{net, private, approved_by,
    approved_at}``), trust anchor, optional SPKI pins, expected identity.
    The transport is pinned to it (connect/destinations.py)."""
    STAGED, ACTIVE = 'staged', 'active'
    SYSTEM, PRIVATE_CA = 'system', 'private_ca'

    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, related_name='destination')
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(default=443)
    addresses = models.JSONField(default=list, blank=True)
    trust = models.CharField(max_length=12, choices=[(SYSTEM, 'System CAs'), (PRIVATE_CA, 'Private CA only')],
                             default=SYSTEM)
    ca_bundle = models.TextField(blank=True)
    spki_pins = models.JSONField(default=list, blank=True, help_text='base64 SHA-256 of the leaf SPKI')
    expected_installation_id = models.CharField(max_length=128, blank=True)
    expected_cert_names = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=[(STAGED, 'Staged'), (ACTIVE, 'Active')], default=STAGED)
    version = models.PositiveIntegerField(default=1)
    observed = models.JSONField(default=dict, blank=True, help_text='Last refused address / key, as evidence.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'connect_destinations'

    def __str__(self):
        return f'{self.host}:{self.port} ({len(self.addresses or [])} address(es), {self.status})'

    def pinned(self):
        import ipaddress
        return frozenset(ipaddress.ip_network(e['net']) for e in self.addresses or [])

    @property
    def has_private(self):
        return any(e.get('private') for e in self.addresses or [])

    @property
    def nets(self):
        return [e['net'] for e in self.addresses or []]


class _SealedRowMixin:
    """Values sealed with AES-256-GCM under APP_MASTER_KEY and bound to the
    row (the uuid primary key exists before the value is sealed)."""

    def _set_sealed(self, name, value):
        aad = self._meta.get_field(name).row_aad(self.pk)
        setattr(self, name, seal(value, aad) if value else '')

    def _get_sealed(self, name) -> str:
        v = getattr(self, name)
        return unseal(v, self._meta.get_field(name).row_aad(self.pk)) if v else ''


class QuickConnectInvitation(_SealedRowMixin, models.Model):
    """Initiator side (A) of one Quick Connect attempt (DESIGN.md §2.2, §6.3,
    PROTOCOL-1.1.md §5.3, §10). Not a credential: it lets an administrator
    who is already signed in to the other application review the request.

    The PKCE verifier and, between the callback and the exchange, the
    authorisation code are sealed to this row and wiped once the exchange
    ran. ``state`` is stored only as a SHA-256 and is additionally bound to
    the administrator's session."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, related_name='qc_invitation')
    jti = models.CharField(max_length=128, unique=True)
    invitation_jws = models.TextField()
    state_hash = models.CharField(max_length=64, unique=True)
    nonce_hash = models.CharField(max_length=64)
    code_challenge = models.CharField(max_length=64)
    code_verifier = SealedTextField(bind_row=True, blank=True)
    responder_origin = models.CharField(max_length=512, help_text='Invitation aud: the approved destination.')
    authorize_url = models.CharField(max_length=600)
    redirect_uri = models.CharField(max_length=512)
    egress = models.JSONField(default=list, blank=True, help_text='Our declared egress, as signed.')
    requested_scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    # Callback (browser leg 2), processed at most once.
    callback_at = models.DateTimeField(null=True, blank=True)
    accept_jws = models.TextField(blank=True)
    pending_code = SealedTextField(bind_row=True, blank=True)
    peer_egress = models.JSONField(default=list, blank=True, help_text='The other side\'s declared egress '
                                                                         '(signed accept).')
    exchanged_at = models.DateTimeField(null=True, blank=True)
    burned_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'connect_qc_invitations'
        ordering = ['-created_at']

    def set_verifier(self, value):
        self._set_sealed('code_verifier', value)

    def verifier(self) -> str:
        return self._get_sealed('code_verifier')

    def set_code(self, value):
        self._set_sealed('pending_code', value)

    def code(self) -> str:
        return self._get_sealed('pending_code')


class QuickConnectGrant(models.Model):
    """Responder side (B) of one Quick Connect attempt: the authorisation
    code of the browser flow (DESIGN.md §2.2, PROTOCOL-1.1.md §5.4, §5.6,
    §10). Only the code's SHA-256 is stored, never the code."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.OneToOneField(Connection, on_delete=models.CASCADE, related_name='qc_grant')
    code_hash = models.CharField(max_length=64, unique=True)
    code_expires_at = models.DateTimeField()
    invitation_jti = models.CharField(max_length=128)
    invitation_iss = models.CharField(max_length=128)
    invitation_jws = models.TextField()
    initiator_jwk = models.JSONField()
    accept_jws = models.TextField()
    egress = models.JSONField(default=list, blank=True, help_text='Initiator\'s declared egress, approved here '
                                                                    'as the temporary rule.')
    rule_expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    observed_source = models.GenericIPAddressField(null=True, blank=True)
    # The last exchange refused by the source layer for this attempt (shown to
    # the administrator; nothing is ever added because of it).
    refused_source = models.GenericIPAddressField(null=True, blank=True)
    refused_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'connect_qc_grants'
        ordering = ['-created_at']


class DiagnosticRun(models.Model):
    """One run of the fifteen connection diagnostics (DESIGN.md §2.2, §9;
    connect/diagnostics.py). ``steps`` holds sanitised results only:
    addresses, certificate names / expiry / SPKI hash, HTTP status, protocol
    and counts. Never a token, assertion, proof, code, signature or key."""
    MANUAL, WIZARD, MONITOR, RETEST = 'manual', 'wizard', 'monitor', 'retest'
    TRIGGERS = [(MANUAL, 'Run by an administrator'), (WIZARD, 'Quick Connect wizard'),
                (MONITOR, 'Monitor'), (RETEST, 'Retest')]
    PASS, FAIL = 'pass', 'fail'

    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='diagnostic_runs')
    trigger = models.CharField(max_length=10, choices=TRIGGERS, default=MANUAL)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    steps = models.JSONField(default=list, blank=True)
    result = models.CharField(max_length=10, blank=True)
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='+')

    class Meta:
        db_table = 'connect_diagnostic_runs'
        ordering = ['-started_at']

    def __str__(self):
        return f'Diagnostics {self.started_at:%Y-%m-%d %H:%M} ({self.result or "running"})'


class ConnectIncident(models.Model):
    """One problem period of a connection (Quick Connect increment E;
    DESIGN.md §10): from the first alerting status (Degraded, Offline,
    Security Blocked, Suspended by the kill switch, Revoked by the other
    side) until it is Connected again or ends. This row is the source of
    the shared event layer's OperationalEvent (events/sources.py, source
    ``connect``; an integer key there) and carries the one optional ticket
    of the incident. Status changes update it; heartbeats never touch it.
    Names, statuses and failure codes only: no address, token or key."""
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='incidents')
    status = models.CharField(max_length=30, help_text='Current displayed status (connect.status key).')
    worst_status = models.CharField(max_length=30, blank=True)
    code = models.CharField(max_length=40, blank=True)
    transitions = models.JSONField(default=list, blank=True, help_text='[{from, to, code, at}], the latest 50.')
    transition_count = models.PositiveIntegerField(default=1)
    opened_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=30, blank=True)
    muted = models.BooleanField(default=False, help_text='Opened while the connection\'s alerts were muted.')
    ticket_id = models.PositiveIntegerField(null=True, blank=True, help_text='psa.Ticket opened for it (opt-in).')
    ticket_error = models.CharField(max_length=200, blank=True)
    # The ticket's recovery is settled (resolved when untouched, or left for
    # a person) only after the incident stayed resolved for REOPEN_WINDOW,
    # so a flapping connection keeps one incident and one ticket.
    ticket_settled = models.BooleanField(default=False)

    class Meta:
        db_table = 'connect_incidents'
        ordering = ['-opened_at']
        constraints = [models.UniqueConstraint(fields=['connection'], condition=models.Q(resolved_at__isnull=True),
                                               name='connect_one_open_incident')]

    def __str__(self):
        return f'Incident {self.pk} ({self.status})'

    @property
    def is_open(self):
        return self.resolved_at is None
