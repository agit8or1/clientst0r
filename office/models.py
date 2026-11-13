"""
Office documents: binary revisions, editor instances, edit sessions.

clientst0r is the canonical store for local Office files. An editor (ONLYOFFICE
Docs, Collabora Online) only ever holds a working copy; every save comes back
through ``office.storage.save_new_revision`` and becomes a new, immutable
``FileRevision``. See docs/OFFICE_DOCUMENTS.md for the full design.

A *target* is the object a file belongs to. Four kinds exist, each an explicit
nullable foreign key (never a GenericForeignKey, so the database enforces the
relation and tenant joins stay plain SQL):

    document           docs.Document with content_type='file'
    attachment         files.Attachment (assets, documentation, vehicles, ...)
    ticket_attachment  psa.TicketAttachment
    office_file        office.OfficeFile (templates and disposable diagnostics)

``office.targets`` wraps them behind one interface.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BaseModel, Organization
from vault.secret_fields import EncryptedTextField

TARGET_FIELDS = ('document', 'attachment', 'ticket_attachment', 'office_file')


def _exactly_one_target():
    """Q that is true when exactly one of the target FKs is set."""
    options = []
    for chosen in TARGET_FIELDS:
        cond = Q(**{f'{chosen}__isnull': False})
        for other in TARGET_FIELDS:
            if other != chosen:
                cond &= Q(**{f'{other}__isnull': True})
        options.append(cond)
    q = options[0]
    for cond in options[1:]:
        q |= cond
    return q


def _at_most_one_target():
    """True when zero or one target FK is set (rows whose target was deleted
    keep their history with every FK cleared)."""
    none_set = Q(**{f'{f}__isnull': True for f in TARGET_FIELDS})
    return none_set | _exactly_one_target()


# Well-known vendor defaults; never accepted as a shared secret.
FORBIDDEN_SECRETS = frozenset({
    'developer-only-not-a-real-secret',  # ONLYOFFICE default for every JWT secret
    'verysecretstring',                  # ONLYOFFICE storage.fs.secretString default
    'secret', 'changeme', 'password',
})
MIN_SECRET_LENGTH = 16


def secret_problem(value):
    """'' when `value` is acceptable as an instance shared secret, else why not."""
    value = (value or '').strip()
    if not value:
        return 'No shared secret is set.'
    if value.lower() in FORBIDDEN_SECRETS:
        return 'That is a published default secret; generate a new random one.'
    if len(value) < MIN_SECRET_LENGTH:
        return f'Use at least {MIN_SECRET_LENGTH} random characters.'
    return ''


PROVIDER_CHOICES = [
    ('onlyoffice', 'ONLYOFFICE Docs'),
    ('collabora', 'Collabora Online'),
]


# ---------------------------------------------------------------------------
# Editor instances and policy
# ---------------------------------------------------------------------------

class EditorInstance(BaseModel):
    """One deployed editor service. Configured by superusers only."""

    MODE_CHOICES = [
        ('same_server', 'Installed on this server'),
        ('separate_server', 'Separate VM / server'),
        ('existing_service', 'Existing service'),
        # Provisioned and run by clientst0r through the Office service helper
        # (office/managed/, deploy/office-helper/). Its URLs and secret are
        # written by office.managed.provision, never typed in.
        ('managed_local', 'Managed local (container on this server)'),
    ]
    MANUAL_MODES = ('same_server', 'separate_server', 'existing_service')
    HEALTH_CHOICES = [
        ('unknown', 'Not checked yet'),
        ('ok', 'Healthy'),
        ('degraded', 'Degraded'),
        ('down', 'Unreachable'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    name = models.CharField(max_length=100, unique=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='separate_server')
    browser_url = models.URLField(
        max_length=500,
        help_text='Address users\' browsers load the editor from (https).')
    internal_url = models.URLField(
        max_length=500, blank=True,
        help_text='Optional server-to-server address clientst0r uses to reach the editor '
                  '(for example a private LAN name). Empty: the browser address is used.')
    callback_base_url = models.URLField(
        max_length=500,
        help_text='Address the editor uses to reach clientst0r (callbacks / WOPI).')
    shared_secret = EncryptedTextField(
        blank=True,
        help_text='JWT secret (ONLYOFFICE) or proof key material (Collabora). Encrypted at rest.')
    ca_bundle = models.TextField(
        blank=True,
        help_text='PEM certificate(s) of a private CA that signed the editor\'s certificate.')
    # Not editable in the UI: the private-CA bundle is the supported way to
    # trust an internal certificate. Only a shell/admin action can clear it.
    verify_tls = models.BooleanField(default=True, editable=False)

    # Detected by the provider health check (never typed in). No connection
    # or user limit is assumed from them: limits depend on the edition and
    # licence actually deployed.
    detected_version = models.CharField(max_length=50, blank=True)
    detected_edition = models.CharField(max_length=100, blank=True)
    capabilities = models.JSONField(
        default=dict, blank=True,
        help_text='Detected by the provider\'s health check. Never typed in by hand.')

    # Provider-specific options an administrator sets (never detected, never
    # secrets). Collabora: require_proof, disable_print, hide_export — see
    # office/providers/collabora/options.py and `manage.py office_collabora`.
    provider_options = models.JSONField(default=dict, blank=True)

    max_file_mb = models.PositiveIntegerField(default=100)
    connect_timeout_s = models.PositiveSmallIntegerField(default=5)
    request_timeout_s = models.PositiveSmallIntegerField(default=30)
    conversion_timeout_s = models.PositiveSmallIntegerField(default=120)

    enabled = models.BooleanField(default=False)
    shared = models.BooleanField(
        default=True, help_text='Available to every organization. Off: only the listed ones.')
    organizations = models.ManyToManyField(
        Organization, blank=True, related_name='dedicated_office_instances')

    last_check_at = models.DateTimeField(null=True, blank=True)
    health_status = models.CharField(max_length=10, choices=HEALTH_CHOICES, default='unknown')
    health_detail = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'office_editor_instances'
        ordering = ['provider', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'

    @property
    def is_healthy(self):
        return self.health_status == 'ok'

    def available_to(self, organization_id):
        if self.shared:
            return True
        if organization_id is None:
            return False
        return self.organizations.filter(pk=organization_id).exists()

    def server_url(self):
        """Base URL for server-to-server calls."""
        return self.internal_url or self.browser_url


class OfficeSettings(models.Model):
    """Singleton (pk=1): platform-wide Office policy."""

    enabled_providers = models.JSONField(default=list, blank=True)
    default_instance = models.ForeignKey(EditorInstance, on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='+')
    allow_org_override = models.BooleanField(
        default=False,
        help_text='Let organization admins pick among the instances available to them.')
    quarantine_retention_days = models.PositiveIntegerField(default=30)
    session_ttl_minutes = models.PositiveIntegerField(
        default=240, help_text='An edit session expires after this long without renewal.')
    session_max_hours = models.PositiveIntegerField(
        default=24, help_text='Hard limit on one edit session, renewals included.')
    token_ttl_minutes = models.PositiveIntegerField(
        default=60, help_text='Access tokens expire after this long unless renewed.')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'office_settings'

    def __str__(self):
        return 'Office settings'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class OrganizationOfficePolicy(models.Model):
    """What one organization chose, within the platform policy."""

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE,
                                        related_name='office_policy')
    office_enabled = models.BooleanField(
        default=True, help_text='Off: nobody in this organization can open the Office editor.')
    preferred_instance = models.ForeignKey(EditorInstance, on_delete=models.SET_NULL,
                                           null=True, blank=True, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'office_org_policies'

    def __str__(self):
        return f'Office policy for {self.organization_id}'


# ---------------------------------------------------------------------------
# Office-owned files: templates and disposable diagnostics documents
# ---------------------------------------------------------------------------

def office_file_upload_to(instance, filename):
    # Real content lives in FileRevision; this is only the current pointer.
    return f'office/files/{uuid.uuid4().hex}'


class OfficeFile(BaseModel):
    PURPOSES = [
        ('template', 'Template'),
        ('diagnostic', 'Diagnostics round-trip document'),
    ]
    purpose = models.CharField(max_length=20, choices=PURPOSES)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name='office_files',
        help_text='Empty: a global template (or a system diagnostics file).')
    name = models.CharField(max_length=255, help_text='File name, with extension.')
    description = models.TextField(blank=True)
    file = models.FileField(upload_to=office_file_upload_to, max_length=500, blank=True)
    file_size = models.BigIntegerField(default=0)
    mime = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    expires_at = models.DateTimeField(null=True, blank=True,
                                      help_text='Diagnostics files are purged after this.')

    class Meta:
        db_table = 'office_files'
        ordering = ['name']
        indexes = [models.Index(fields=['purpose', 'organization'])]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Edit sessions and tokens
# ---------------------------------------------------------------------------

class EditSession(models.Model):
    MODE_CHOICES = [('view', 'View'), ('edit', 'Edit')]
    STATE_CHOICES = [
        ('open', 'Open'),
        ('closing', 'Closing (waiting for the editor\'s final save)'),
        ('closed', 'Closed'),
        ('revoked', 'Revoked'),
        ('failed', 'Failed'),
    ]
    LIVE_STATES = ('open', 'closing')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True,
                                     blank=True, related_name='office_sessions')
    # SET_NULL: a session outlives its target so a late save can still be
    # matched and quarantined after the file was deleted.
    document = models.ForeignKey('docs.Document', on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='office_sessions')
    attachment = models.ForeignKey('files.Attachment', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='office_sessions')
    ticket_attachment = models.ForeignKey('psa.TicketAttachment', on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='office_sessions')
    office_file = models.ForeignKey(OfficeFile, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='sessions')
    target_label = models.CharField(max_length=255, blank=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='office_sessions')
    instance = models.ForeignKey(EditorInstance, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='sessions')
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)
    document_key = models.CharField(max_length=128, db_index=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='open')
    base_revision = models.ForeignKey('FileRevision', on_delete=models.SET_NULL, null=True,
                                      blank=True, related_name='+')
    opened_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    max_expires_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=255, blank=True)
    # Provider-owned scratch data (lock ids, editor user ids). Never secrets.
    provider_state = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'office_edit_sessions'
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['state', 'expires_at']),
            models.Index(fields=['user', 'state']),
        ]
        constraints = [
            models.CheckConstraint(condition=_at_most_one_target(),
                                   name='office_session_one_target'),
        ]

    def __str__(self):
        return f'{self.get_mode_display()} session {self.pk} ({self.state})'

    @property
    def is_live(self):
        return self.state in self.LIVE_STATES and self.expires_at > timezone.now()


class AccessToken(models.Model):
    """A bearer token for one session. Only the HMAC of the token is stored
    (vault.secret_fields.hash_token, purpose ``office.access``)."""

    OPS = ('read', 'write', 'lock', 'rename', 'export')

    session = models.ForeignKey(EditSession, on_delete=models.CASCADE, related_name='tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    ops = models.JSONField(default=list)
    purpose = models.CharField(max_length=30, blank=True,
                               help_text='Label only: browser / callback / wopi.')
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'office_access_tokens'
        indexes = [models.Index(fields=['session', 'revoked_at'])]

    def __str__(self):
        return f'token for session {self.session_id}'


# ---------------------------------------------------------------------------
# Binary revisions
# ---------------------------------------------------------------------------

class FileRevision(models.Model):
    SOURCES = [
        ('create', 'Created blank'),
        ('upload', 'Uploaded'),
        ('editor_save', 'Saved from the editor'),
        ('restore', 'Restored'),
        ('copy', 'Copied'),
        ('import', 'Imported'),
        ('convert', 'Converted'),
    ]

    document = models.ForeignKey('docs.Document', on_delete=models.CASCADE, null=True,
                                 blank=True, related_name='office_revisions')
    attachment = models.ForeignKey('files.Attachment', on_delete=models.CASCADE, null=True,
                                   blank=True, related_name='office_revisions')
    ticket_attachment = models.ForeignKey('psa.TicketAttachment', on_delete=models.CASCADE,
                                          null=True, blank=True, related_name='office_revisions')
    office_file = models.ForeignKey(OfficeFile, on_delete=models.CASCADE, null=True,
                                    blank=True, related_name='revisions')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True,
                                     blank=True, related_name='office_revisions')

    revision_number = models.PositiveIntegerField()
    file = models.FileField(max_length=500)
    sha256 = models.CharField(max_length=64)
    size = models.BigIntegerField()
    mime = models.CharField(max_length=150)
    original_name = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=20, choices=SOURCES)
    editor_session = models.ForeignKey(EditSession, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='revisions')
    based_on_revision = models.ForeignKey('self', on_delete=models.SET_NULL, null=True,
                                          blank=True, related_name='+')
    restored_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True,
                                      blank=True, related_name='+')

    class Meta:
        db_table = 'office_file_revisions'
        ordering = ['-revision_number']
        constraints = [
            models.CheckConstraint(condition=_exactly_one_target(),
                                   name='office_revision_one_target'),
        ] + [
            models.UniqueConstraint(
                fields=[f, 'revision_number'], condition=Q(**{f'{f}__isnull': False}),
                name=f'office_revision_unique_{f}')
            for f in TARGET_FIELDS
        ]
        indexes = [models.Index(fields=['organization', 'created_at'])]

    def __str__(self):
        return f'{self.original_name} r{self.revision_number}'


# ---------------------------------------------------------------------------
# Quarantine: saves that could not be accepted, kept for recovery
# ---------------------------------------------------------------------------

def quarantine_upload_to(instance, filename):
    return f'office/quarantine/{timezone.now():%Y/%m}/{uuid.uuid4().hex}'


class QuarantinedSave(models.Model):
    REASONS = [
        ('stale', 'Based on an older revision'),
        ('revoked', 'Session revoked or expired'),
        ('permission', 'User no longer allowed to edit'),
        ('validation', 'Content failed validation'),
        ('storage_error', 'Could not be stored'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True,
                                     blank=True, related_name='office_quarantine')
    document = models.ForeignKey('docs.Document', on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='+')
    attachment = models.ForeignKey('files.Attachment', on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='+')
    ticket_attachment = models.ForeignKey('psa.TicketAttachment', on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='+')
    office_file = models.ForeignKey(OfficeFile, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='+')
    target_label = models.CharField(max_length=255, blank=True)
    session = models.ForeignKey(EditSession, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='quarantined_saves')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             blank=True, related_name='+')
    file = models.FileField(upload_to=quarantine_upload_to, max_length=500)
    sha256 = models.CharField(max_length=64)
    size = models.BigIntegerField()
    original_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=20, choices=REASONS)
    detail = models.CharField(max_length=500, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    recovered_revision = models.ForeignKey(FileRevision, on_delete=models.SET_NULL, null=True,
                                           blank=True, related_name='+')

    class Meta:
        db_table = 'office_quarantined_saves'
        ordering = ['-received_at']
        indexes = [models.Index(fields=['expires_at'])]
        constraints = [
            models.CheckConstraint(condition=_at_most_one_target(),
                                   name='office_quarantine_one_target'),
        ]

    def __str__(self):
        return f'quarantined {self.original_name} ({self.reason})'


# ---------------------------------------------------------------------------
# WOPI locks (Collabora Online)
# ---------------------------------------------------------------------------

class WopiLock(models.Model):
    """The WOPI lock on one target file, as set by LOCK / UNLOCK.

    One row per target (``target_kind`` + ``target_pk`` is unique). Changes
    are compare-and-set updates on that row (``office.providers.collabora.
    locks``), so two concurrent LOCK requests cannot both win, on any
    database. A lock with ``expires_at`` in the past counts as no lock
    (WOPI: locks expire after 30 minutes unless refreshed). The lock id is
    the editor's opaque string (at most 1024 ASCII characters), not a
    secret.
    """

    target_kind = models.CharField(max_length=20)
    target_pk = models.BigIntegerField()
    lock_id = models.CharField(max_length=1024)
    expires_at = models.DateTimeField()
    session = models.ForeignKey(EditSession, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'office_wopi_locks'
        constraints = [
            models.UniqueConstraint(fields=['target_kind', 'target_pk'],
                                    name='office_wopi_lock_one_per_target'),
        ]

    def __str__(self):
        return f'WOPI lock on {self.target_kind}:{self.target_pk}'


# ---------------------------------------------------------------------------
# Managed Local ONLYOFFICE (office/managed/, docs/office/MANAGED_LOCAL.md)
# ---------------------------------------------------------------------------

class ManagedOfficeService(models.Model):
    """Singleton (pk=1): this deployment's managed ONLYOFFICE container, as
    clientst0r last saw it through the Office service helper. The helper and
    its root-owned configuration are the source of truth; this row is a
    cache plus the administrator's app-side choices."""

    ENGINES = [('onlyoffice', 'ONLYOFFICE Docs'),
               ('collabora', 'Collabora Online Development Edition (CODE)')]
    LAYOUTS = [('dedicated', 'Dedicated host name'),
               ('same-host', 'Same host as clientst0r (Collabora only)')]

    enabled = models.BooleanField(
        default=False,
        help_text='Managed mode is off until a deployment administrator turns it on.')
    # The engine the administrator chose. What is actually installed is the
    # helper's status (status["engine"]); the root config decides which
    # engines may be chosen at all (ENGINES=).
    engine = models.CharField(max_length=20, choices=ENGINES, default='onlyoffice')
    same_host_acknowledged_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When an administrator accepted the same-host origin-sharing warning.')
    same_host_acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                                  null=True, blank=True, related_name='+')
    instance = models.ForeignKey(EditorInstance, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name='+')
    status = models.JSONField(default=dict, blank=True,
                              help_text='Last helper status (no secrets).')
    status_at = models.DateTimeField(null=True, blank=True)
    helper_reachable = models.BooleanField(default=False)
    status_error = models.CharField(max_length=500, blank=True)
    last_connection_ok_at = models.DateTimeField(null=True, blank=True)
    last_connection_detail = models.TextField(blank=True)

    maintenance_updates = models.BooleanField(
        default=False,
        help_text='Allow updates inside the maintenance window. Off: updates are manual only.')
    maintenance_weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text='0 = Monday ... 6 = Sunday; empty = every day.')
    maintenance_hour = models.PositiveSmallIntegerField(
        default=3, help_text='Window start, server local time (0-23).')
    maintenance_hours = models.PositiveSmallIntegerField(default=2, help_text='Window length (1-6).')

    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'office_managed_service'

    def __str__(self):
        return 'Managed Office service'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class ManagedOfficeOperation(models.Model):
    """One lifecycle operation on the managed container, run in the
    background by office.managed.jobs (scheduler task
    ``office_managed_operations``). At most one is active at a time; the
    database enforces it with a conditional unique constraint."""

    ACTIONS = [
        ('install', 'Install'), ('start', 'Start'), ('stop', 'Stop'), ('restart', 'Restart'),
        ('update', 'Update'), ('rollback', 'Roll back'), ('uninstall', 'Uninstall'),
        # drain, uninstall the current engine (data kept), install the other
        ('switch_engine', 'Switch engine'),
        # drain, rewrite the proxy files, re-create the container
        ('set_layout', 'Switch address layout'),
    ]
    STATES = [
        ('queued', 'Queued'),
        ('draining', 'Draining editing sessions'),
        ('running', 'Running on the server'),
        ('verifying', 'Verifying'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('postponed', 'Postponed (sessions could not be drained)'),
        ('cancelled', 'Cancelled'),
    ]
    ACTIVE_STATES = ('queued', 'draining', 'running', 'verifying')
    SOURCES = [('admin', 'Administrator'), ('maintenance', 'Maintenance window')]

    lock_key = models.CharField(max_length=20, default='managed', editable=False)
    action = models.CharField(max_length=20, choices=ACTIONS)
    target_release = models.CharField(max_length=40, blank=True)
    target_engine = models.CharField(max_length=20, blank=True)
    target_layout = models.CharField(max_length=20, blank=True)
    state = models.CharField(max_length=20, choices=STATES, default='queued')
    source = models.CharField(max_length=20, choices=SOURCES, default='admin')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    lease = models.CharField(max_length=40, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    helper_op_id = models.CharField(max_length=60, blank=True)
    helper_submits = models.PositiveSmallIntegerField(default=0)
    drain_started_at = models.DateTimeField(null=True, blank=True)
    progress = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = 'office_managed_operations'
        ordering = ['-queued_at']
        constraints = [
            models.UniqueConstraint(fields=['lock_key'],
                                    condition=Q(state__in=('queued', 'draining', 'running',
                                                           'verifying')),
                                    name='office_managed_one_active_operation'),
        ]

    def __str__(self):
        return f'{self.get_action_display()} ({self.state})'

    @property
    def is_active(self):
        return self.state in self.ACTIVE_STATES
