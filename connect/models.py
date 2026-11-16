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
    STATES = [
        (PENDING_PAIRING, 'Pairing'),
        (AWAITING_REMOTE, 'Waiting for the other application to approve'),
        (AWAITING_LOCAL, 'Waiting for approval here'),
        (AWAITING_SECOND, 'Waiting for a second administrator'),
        (ACTIVE, 'Connected'),
        (SUSPENDED, 'Suspended'),
        (REVOKED, 'Disconnected'),
        (FAILED, 'Pairing failed'),
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

    # Rotation.
    rotation_interval_days = models.PositiveIntegerField(default=90)
    rotation_overlap_hours = models.PositiveIntegerField(default=24)
    next_rotation_at = models.DateTimeField(null=True, blank=True)
    last_rotation_at = models.DateTimeField(null=True, blank=True)
    last_rotation_error = models.CharField(max_length=300, blank=True)

    tokens_not_before = models.DateTimeField(null=True, blank=True,
                                             help_text='Access tokens issued before this are refused.')
    suspended_reason = models.CharField(max_length=40, blank=True)
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
