"""
Contract documents: build, approve, send, track and sign customer contracts.

These are the *documents* a customer signs (a managed services agreement, a
statement of work, a renewal, an amendment). They are deliberately separate
from `psa.Contract`, which is the *billing* record the PSA uses for hours,
SLAs and recurring invoices. A signed contract document can create or link a
PSA billing contract (`ContractDocument.billing_contract`), but neither
changes the other.

  ContractSettings          deployment defaults (organization NULL) and
                            optional per-customer overrides
  ContractTemplate          a starter (deployment-wide) or customer template
  ContractTemplateVersion   one immutable saved version of a template
  ContractClause            reusable clause / optional section
  ContractDocument          one contract for one customer (the draft lives
                            here and may be edited freely)
  ContractSigner            who is asked to sign (draft configuration)
  ContractAttachment        exhibits; bytes kept with their SHA-256
  ContractVersion           one issued, frozen version: content JSON + hash,
                            HTML snapshot, issued PDF; later the final PDF
  ContractApproval          an internal approval of one exact version
  ContractInvitation        one signer's invitation for one version
  ContractAccessToken       hashed opaque link tokens of an invitation
  ContractSignature         one signature of one version (immutable)
  ContractEvent             append-only timeline / audit history
  ContractNotification      in-app alerts for staff
  ContractAlert             de-duplication ledger for alerts
  ContractJob               background jobs (e-mail, finalization) with
                            retries and idempotency keys

Nothing here is a cryptographic (certificate-based) signature: a signature is
a typed or drawn mark plus evidence (who, when, from where, which exact
version by SHA-256). The hashes make later changes detectable; they do not
prove identity.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def canonical_json(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      default=str).encode('utf-8')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data or b'').hexdigest()


class ImmutableError(ValueError):
    pass


KINDS = [
    ('managed_services', 'Managed IT services agreement'),
    ('sow', 'Statement of work / project agreement'),
    ('recurring_support', 'Recurring support / service agreement'),
    ('backup_dr', 'Backup and disaster recovery services'),
    ('security', 'Security services'),
    ('renewal', 'Contract renewal'),
    ('amendment', 'Contract amendment / addendum'),
    ('other', 'Other'),
]

BILLING_FREQUENCIES = [
    ('one_time', 'One time'), ('monthly', 'Monthly'), ('quarterly', 'Quarterly'),
    ('annually', 'Annually'),
]

PARALLEL, SEQUENTIAL = 'parallel', 'sequential'
SIGNING_ORDERS = [(PARALLEL, 'Parallel — every client signer at once'),
                  (SEQUENTIAL, 'Sequential — client signers one after another')]

DEFAULT_CONSENT_TEXT = (
    'I agree to sign this document electronically. I understand that my typed or drawn signature, '
    'together with the time, my IP address, my browser and a SHA-256 fingerprint of this exact '
    'version of the document, will be recorded as my electronic signature. I can download a copy '
    'of the document before and after signing. I may decline to sign electronically and ask the '
    'sender for another way to sign.'
)
DEFAULT_INTENT_TEXT = 'By selecting "Sign" I intend to sign this agreement.'

DEFAULT_INVITATION_SUBJECT = 'Please review and sign: {{contract.title}} ({{contract.reference}})'
DEFAULT_INVITATION_BODY = (
    'Hello {{signer.name}},\n\n'
    '{{provider.name}} has sent you "{{contract.title}}" ({{contract.reference}}) for '
    '{{client.name}} to review and sign.\n\n'
    'Open it here:\n{{link}}\n\n'
    'This link is personal to you and expires on {{invitation.expires}}. Please do not forward it.\n\n'
    '— {{provider.name}}'
)
DEFAULT_REMINDER_SUBJECT = 'Reminder: {{contract.title}} is waiting for your signature'
DEFAULT_REMINDER_BODY = (
    'Hello {{signer.name}},\n\n'
    'This is a reminder that "{{contract.title}}" ({{contract.reference}}) for {{client.name}} is '
    'waiting for your review.\n\nOpen it here:\n{{link}}\n\n'
    'The link expires on {{invitation.expires}}.\n\n— {{provider.name}}'
)
DEFAULT_COMPLETED_SUBJECT = 'Signed copy: {{contract.title}} ({{contract.reference}})'
DEFAULT_COMPLETED_BODY = (
    'Hello {{signer.name}},\n\n'
    'Every party has signed "{{contract.title}}" ({{contract.reference}}). The signed copy, with its '
    'signature summary, is attached.\n\n— {{provider.name}}'
)


class ContractSettings(models.Model):
    """Deployment defaults (organization NULL) or one customer's override.

    A customer row is a full copy made when someone first customises that
    customer; deleting it returns the customer to the deployment defaults."""
    organization = models.OneToOneField('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='contract_settings')
    # Branding and provider details
    provider_name = models.CharField(max_length=255, blank=True,
                                     help_text='Your company name on contracts. Blank: the site brand name.')
    provider_address = models.TextField(blank=True)
    provider_email = models.EmailField(blank=True)
    provider_phone = models.CharField(max_length=50, blank=True)
    provider_website = models.CharField(max_length=255, blank=True)
    brand_color = models.CharField(max_length=7, default='#1f4e79', help_text='Hex colour, e.g. #1f4e79.')
    email_footer = models.TextField(blank=True, help_text='Added to the end of every contract e-mail.')
    # Defaults
    default_template = models.ForeignKey('ContractTemplate', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='+')
    default_clauses = models.ManyToManyField('ContractClause', blank=True, related_name='+',
                                             help_text='Offered first in the clause picker.')
    # Notification recipients and channels
    notify_owner = models.BooleanField(default=True)
    notify_account_manager = models.BooleanField(default=True)
    notify_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+',
                                          help_text='Selected admins or managers who are always told.')
    notify_roles = models.ManyToManyField('accounts.RoleTemplate', blank=True, related_name='+',
                                          help_text='MSP staff whose global role is one of these are told.')
    notify_in_app = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    notify_repeat_views = models.BooleanField(default=False,
                                              help_text='Also alert on later views, at most once per cooldown.')
    repeat_view_cooldown_minutes = models.PositiveIntegerField(default=240)
    # Reminders and expiry
    reminders_enabled = models.BooleanField(default=True)
    reminder_first_after_days = models.PositiveSmallIntegerField(default=3)
    reminder_interval_days = models.PositiveSmallIntegerField(default=3)
    reminder_max = models.PositiveSmallIntegerField(default=3)
    invitation_expiry_days = models.PositiveSmallIntegerField(default=30)
    acceptance_deadline_days = models.PositiveSmallIntegerField(default=30, help_text='0: no deadline.')
    # Signing
    require_email_verification = models.BooleanField(default=False)
    require_countersignature = models.BooleanField(default=False)
    signing_order = models.CharField(max_length=12, choices=SIGNING_ORDERS, default=PARALLEL)
    require_internal_approval = models.BooleanField(default=False)
    allow_self_approval = models.BooleanField(default=False)
    # Renewal / expiration alerts (days before the contract's expiration date)
    renewal_alert_days = models.PositiveSmallIntegerField(default=60)
    expiration_alert_days = models.PositiveSmallIntegerField(default=14)
    # Privacy
    access_log_retention_days = models.PositiveIntegerField(
        default=365, help_text='Days to keep IP address and browser of link and view events (0: keep). '
                               'Signature evidence keeps them for as long as the contract exists.')
    # Wording
    consent_text = models.TextField(default=DEFAULT_CONSENT_TEXT)
    intent_text = models.CharField(max_length=500, default=DEFAULT_INTENT_TEXT)
    invitation_subject = models.CharField(max_length=255, default=DEFAULT_INVITATION_SUBJECT)
    invitation_body = models.TextField(default=DEFAULT_INVITATION_BODY)
    reminder_subject = models.CharField(max_length=255, default=DEFAULT_REMINDER_SUBJECT)
    reminder_body = models.TextField(default=DEFAULT_REMINDER_BODY)
    completed_subject = models.CharField(max_length=255, default=DEFAULT_COMPLETED_SUBJECT)
    completed_body = models.TextField(default=DEFAULT_COMPLETED_BODY)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')

    COPY_FIELDS = (
        'provider_name', 'provider_address', 'provider_email', 'provider_phone', 'provider_website',
        'brand_color', 'email_footer', 'default_template', 'notify_owner', 'notify_account_manager',
        'notify_in_app', 'notify_email', 'notify_repeat_views', 'repeat_view_cooldown_minutes',
        'reminders_enabled', 'reminder_first_after_days', 'reminder_interval_days', 'reminder_max',
        'invitation_expiry_days', 'acceptance_deadline_days', 'require_email_verification',
        'require_countersignature', 'signing_order', 'require_internal_approval', 'allow_self_approval',
        'renewal_alert_days', 'expiration_alert_days', 'access_log_retention_days', 'consent_text',
        'intent_text', 'invitation_subject', 'invitation_body', 'reminder_subject', 'reminder_body',
        'completed_subject', 'completed_body',
    )

    class Meta:
        db_table = 'contracts_settings'

    def __str__(self):
        return f'Contract settings ({self.organization.name if self.organization_id else "deployment default"})'

    @classmethod
    def deployment_default(cls):
        row = cls.objects.filter(organization__isnull=True).order_by('pk').first()
        if row is None:
            row = cls.objects.create(organization=None)
        return row

    @classmethod
    def for_organization(cls, organization):
        """The effective settings for a customer (its override, else the default)."""
        if organization is not None:
            row = cls.objects.filter(organization=organization).first()
            if row is not None:
                return row
        return cls.deployment_default()

    @classmethod
    def override_for(cls, organization):
        """Get or create the customer's own override as a copy of the default."""
        row = cls.objects.filter(organization=organization).first()
        if row is not None:
            return row
        base = cls.deployment_default()
        row = cls(organization=organization, **{f: getattr(base, f) for f in cls.COPY_FIELDS})
        row.save()
        row.notify_users.set(base.notify_users.all())
        row.notify_roles.set(base.notify_roles.all())
        row.default_clauses.set(base.default_clauses.all())
        return row

    def provider_display_name(self):
        if self.provider_name:
            return self.provider_name
        from core import mailer
        from core.models import SystemSetting
        return mailer.brand_name(SystemSetting.get_settings())


class ContractTemplate(models.Model):
    """A reusable starting point. organization NULL: a deployment-wide
    starter, managed by staff who may manage templates for every customer."""
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='contract_templates')
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=30, choices=KINDS, default='other')
    description = models.TextField(blank=True)
    is_sample = models.BooleanField(default=False, help_text='Shipped sample language that needs review before use.')
    is_active = models.BooleanField(default=True)
    cloned_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contracts_templates'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def latest_version(self):
        return self.versions.order_by('-version_number').first()

    @property
    def scope_label(self):
        return self.organization.name if self.organization_id else 'All customers (starter)'


class ContractTemplateVersion(models.Model):
    """One saved version of a template. Never changed after it is saved, so
    contracts created from it (and their snapshots) are unaffected by later
    template edits."""
    template = models.ForeignKey(ContractTemplate, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    data = models.JSONField(default=dict, help_text='{sections, line_items, defaults}')
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'contracts_template_versions'
        ordering = ['-version_number']
        constraints = [models.UniqueConstraint(fields=['template', 'version_number'],
                                               name='contracts_template_version_unique')]

    def __str__(self):
        return f'{self.template.name} v{self.version_number}'

    def save(self, *args, **kwargs):
        if self.pk and ContractTemplateVersion.objects.filter(pk=self.pk).exists():
            raise ImmutableError('A saved template version cannot be changed; save a new version.')
        super().save(*args, **kwargs)


class ContractClause(models.Model):
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='contract_clauses')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    body = models.TextField(help_text='Sanitised HTML.')
    is_optional = models.BooleanField(default=True, help_text='Offered as an optional section.')
    is_sample = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contracts_clauses'
        ordering = ['category', 'title']

    def __str__(self):
        return self.title


class ContractDocument(models.Model):
    DRAFT = 'draft'
    PENDING_APPROVAL = 'pending_approval'
    READY = 'ready_to_send'
    SENT = 'sent'
    VIEWED = 'viewed'
    PARTIALLY_SIGNED = 'partially_signed'
    SIGNED = 'signed'
    DECLINED = 'declined'
    EXPIRED = 'expired'
    VOIDED = 'voided'
    SUPERSEDED = 'superseded'
    STATUSES = [
        (DRAFT, 'Draft'), (PENDING_APPROVAL, 'Pending Internal Approval'), (READY, 'Ready to Send'),
        (SENT, 'Sent'), (VIEWED, 'Viewed'), (PARTIALLY_SIGNED, 'Partially Signed'), (SIGNED, 'Signed'),
        (DECLINED, 'Declined'), (EXPIRED, 'Expired'), (VOIDED, 'Voided'), (SUPERSEDED, 'Superseded'),
    ]
    OPEN_FOR_SIGNING = (SENT, VIEWED, PARTIALLY_SIGNED)

    RELATIONS = [('', ''), ('cloned_from', 'Cloned from'), ('amends', 'Amends'), ('renews', 'Renews'),
                 ('replaces', 'Replaces')]

    organization = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True,
                                     related_name='contract_documents')
    organization_name = models.CharField(max_length=255, blank=True,
                                         help_text='Copied from the customer; kept if it is deleted.')
    reference = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=30, choices=KINDS, default='other')
    status = models.CharField(max_length=20, choices=STATUSES, default=DRAFT, db_index=True)
    template_version = models.ForeignKey(ContractTemplateVersion, on_delete=models.SET_NULL, null=True,
                                         blank=True, related_name='+')
    related_contract = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='related_from')
    relation = models.CharField(max_length=20, choices=RELATIONS, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='owned_contract_documents')
    account_manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='managed_contract_documents')
    notify_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+')

    # Draft content (edited freely while a draft)
    sections = models.JSONField(default=list, blank=True)
    line_items = models.JSONField(default=list, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    tax_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0, help_text='Percent.')
    payment_terms = models.CharField(max_length=255, blank=True, default='Net 30')
    billing_frequency = models.CharField(max_length=12, choices=BILLING_FREQUENCIES, default='monthly')
    effective_date = models.DateField(null=True, blank=True)
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    renewal_terms = models.TextField(blank=True)
    auto_renew = models.BooleanField(default=False)
    notice_period_days = models.PositiveSmallIntegerField(null=True, blank=True)
    acceptance_deadline = models.DateField(null=True, blank=True)
    draft_revision = models.PositiveIntegerField(default=0)
    draft_saved_at = models.DateTimeField(null=True, blank=True)
    draft_saved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+')

    # Per-contract signing overrides (NULL: use the settings)
    require_email_verification = models.BooleanField(null=True, blank=True)
    require_countersignature = models.BooleanField(null=True, blank=True)
    signing_order = models.CharField(max_length=12, choices=SIGNING_ORDERS, blank=True)
    require_internal_approval = models.BooleanField(null=True, blank=True)
    invitation_expiry_days = models.PositiveSmallIntegerField(null=True, blank=True)
    reminders_enabled = models.BooleanField(null=True, blank=True)

    current_version = models.ForeignKey('ContractVersion', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+')
    billing_contract = models.ForeignKey('psa.Contract', on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='contract_documents',
                                         help_text='PSA billing contract created from or linked to this one.')
    # Cached totals for the dashboard (recomputed on every draft save)
    one_time_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    recurring_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Viewing aggregates (never affect status ordering)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0, help_text='Likely human views.')
    link_request_count = models.PositiveIntegerField(default=0)

    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')
    void_reason = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contracts_documents'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['organization', 'status']),
                   models.Index(fields=['status', 'expiration_date'])]

    def __str__(self):
        return f'{self.reference} {self.title}'

    @property
    def is_editable(self):
        return self.status == self.DRAFT

    @property
    def is_open_for_signing(self):
        return self.status in self.OPEN_FOR_SIGNING

    @property
    def client_name(self):
        return self.organization.name if self.organization_id else self.organization_name

    def delete(self, *args, **kwargs):
        if self.versions.exists():
            raise ImmutableError('An issued contract is kept as a record; void it instead of deleting it.')
        return super().delete(*args, **kwargs)


class ContractSigner(models.Model):
    CLIENT, INTERNAL = 'client', 'internal'
    ROLES = [(CLIENT, 'Client signer'), (INTERNAL, 'Internal countersigner')]
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, related_name='signers')
    role = models.CharField(max_length=10, choices=ROLES, default=CLIENT)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    title = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=1)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+', help_text='Internal countersigner account.')

    class Meta:
        db_table = 'contracts_signers'
        ordering = ['role', 'order', 'pk']

    def __str__(self):
        return f'{self.name} <{self.email}> ({self.role})'


class ContractAttachment(models.Model):
    MAX_BYTES = 10 * 1024 * 1024
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, related_name='attachments')
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    data = models.BinaryField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    uploaded_at = models.DateTimeField(default=timezone.now)
    removed_at = models.DateTimeField(null=True, blank=True,
                                      help_text='Removed from the draft; kept because an issued version may cite it.')

    class Meta:
        db_table = 'contracts_attachments'
        ordering = ['uploaded_at']

    def __str__(self):
        return self.name


class ContractVersion(models.Model):
    PENDING_APPROVAL = 'pending_approval'
    READY = 'ready'
    REJECTED = 'rejected'
    SENT = 'sent'
    SIGNED = 'signed'
    DECLINED = 'declined'
    EXPIRED = 'expired'
    SUPERSEDED = 'superseded'
    VOIDED = 'voided'
    STATUSES = [(PENDING_APPROVAL, 'Pending approval'), (READY, 'Ready to send'), (REJECTED, 'Approval rejected'),
                (SENT, 'Sent'), (SIGNED, 'Signed'), (DECLINED, 'Declined'), (EXPIRED, 'Expired'),
                (SUPERSEDED, 'Superseded'), (VOIDED, 'Voided')]
    FROZEN_FIELDS = ('contract_id', 'version_number', 'content', 'content_hash', 'rendered_html',
                     'snapshot_html', 'snapshot_hash', 'consent_text', 'intent_text',
                     'signing_order', 'require_verification', 'require_countersignature',
                     'requires_approval', 'issued_at')
    # The issued PDF may be added once (if making it failed at issue time,
    # sending makes it); nothing is signed before it exists.
    WRITE_ONCE_FIELDS = ('pdf', 'pdf_hash', 'final_pdf', 'final_pdf_hash', 'certificate_json', 'certificate_hash')

    contract = models.ForeignKey(ContractDocument, on_delete=models.PROTECT, related_name='versions')
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUSES, default=READY)
    content = models.JSONField(help_text='Exactly what was issued; content_hash is SHA-256 of its canonical JSON.')
    content_hash = models.CharField(max_length=64)
    rendered_html = models.TextField(help_text='The sanitised agreement body shown to signers.')
    snapshot_html = models.TextField()
    snapshot_hash = models.CharField(max_length=64)
    pdf = models.BinaryField(null=True, blank=True)
    pdf_hash = models.CharField(max_length=64, blank=True)
    consent_text = models.TextField()
    intent_text = models.CharField(max_length=500)
    signing_order = models.CharField(max_length=12, choices=SIGNING_ORDERS, default=PARALLEL)
    require_verification = models.BooleanField(default=False)
    require_countersignature = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')
    superseded_at = models.DateTimeField(null=True, blank=True)
    # Completion
    completed_at = models.DateTimeField(null=True, blank=True, help_text='Every required signature recorded.')
    finalization_status = models.CharField(max_length=10, blank=True,
                                           choices=[('', ''), ('pending', 'Pending'), ('done', 'Done'),
                                                    ('failed', 'Failed — will retry')])
    finalization_error = models.CharField(max_length=500, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    final_pdf = models.BinaryField(null=True, blank=True)
    final_pdf_hash = models.CharField(max_length=64, blank=True)
    certificate_json = models.TextField(blank=True)
    certificate_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = 'contracts_versions'
        ordering = ['-version_number']
        constraints = [models.UniqueConstraint(fields=['contract', 'version_number'],
                                               name='contracts_version_unique')]

    def __str__(self):
        return f'{self.contract.reference} v{self.version_number}'

    def content_json(self) -> bytes:
        return canonical_json(self.content)

    def verify(self) -> dict:
        checks = {'content': sha256(self.content_json()) == self.content_hash,
                  'snapshot': sha256(self.snapshot_html.encode('utf-8')) == self.snapshot_hash,
                  'pdf': (not self.pdf_hash) or sha256(bytes(self.pdf or b'')) == self.pdf_hash}
        if self.final_pdf_hash:
            checks['final_pdf'] = sha256(bytes(self.final_pdf or b'')) == self.final_pdf_hash
        if self.certificate_hash:
            checks['certificate'] = sha256(self.certificate_json.encode('utf-8')) == self.certificate_hash
        return checks

    def save(self, *args, **kwargs):
        if self.pk:
            old = ContractVersion.objects.filter(pk=self.pk).first()
            if old is not None:
                for f in self.FROZEN_FIELDS:
                    a, b = getattr(old, f), getattr(self, f)
                    if isinstance(a, memoryview):
                        a = bytes(a)
                    if isinstance(b, memoryview):
                        b = bytes(b)
                    if a != b:
                        raise ImmutableError(f'An issued contract version cannot be changed ({f}).')
                for f in self.WRITE_ONCE_FIELDS:
                    a, b = getattr(old, f), getattr(self, f)
                    if isinstance(a, memoryview):
                        a = bytes(a)
                    if isinstance(b, memoryview):
                        b = bytes(b)
                    if a and a != b:
                        raise ImmutableError(f'The completed record cannot be changed ({f}).')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError('An issued contract version cannot be deleted.')

    @property
    def signer_specs(self):
        return list((self.content or {}).get('signers') or [])


class ContractApproval(models.Model):
    APPROVED, REJECTED = 'approved', 'rejected'
    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, related_name='approvals')
    decision = models.CharField(max_length=10, choices=[(APPROVED, 'Approved'), (REJECTED, 'Rejected')])
    content_hash = models.CharField(max_length=64, help_text='The exact version content approved.')
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    decided_by_name = models.CharField(max_length=200)
    decided_at = models.DateTimeField(default=timezone.now)
    comment = models.TextField(blank=True)

    class Meta:
        db_table = 'contracts_approvals'
        ordering = ['-decided_at']

    def save(self, *args, **kwargs):
        if self.pk and ContractApproval.objects.filter(pk=self.pk).exists():
            raise ImmutableError('An approval decision cannot be changed.')
        super().save(*args, **kwargs)


class ContractInvitation(models.Model):
    WAITING = 'waiting'      # sequential / countersign: not this signer's turn yet
    ACTIVE = 'active'
    SIGNED = 'signed'
    DECLINED = 'declined'
    REVOKED = 'revoked'
    EXPIRED = 'expired'
    SUPERSEDED = 'superseded'
    STATUSES = [(WAITING, 'Waiting for earlier signers'), (ACTIVE, 'Active'), (SIGNED, 'Signed'),
                (DECLINED, 'Declined'), (REVOKED, 'Revoked'), (EXPIRED, 'Expired'), (SUPERSEDED, 'Superseded')]
    OPEN = (WAITING, ACTIVE)
    DELIVERY = [('', 'Not sent'), ('queued', 'Queued'),
                ('accepted', 'Accepted by the mail server (not proof of delivery)'),
                ('failed', 'Sending failed')]

    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, related_name='invitations')
    contract = models.ForeignKey(ContractDocument, on_delete=models.PROTECT, related_name='invitations')
    signer_ref = models.PositiveSmallIntegerField(help_text='Position of the signer in the version content.')
    role = models.CharField(max_length=10, choices=ContractSigner.ROLES)
    name = models.CharField(max_length=200)
    email = models.EmailField()
    title = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=1)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+')
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=STATUSES, default=WAITING, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=255, blank=True)
    replaced_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # Delivery
    send_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(max_length=10, choices=DELIVERY, blank=True)
    delivery_error = models.CharField(max_length=300, blank=True)
    reminders_sent = models.PositiveSmallIntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    # Viewing (kept apart from the signature state)
    link_request_count = models.PositiveIntegerField(default=0)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    verified_view_count = models.PositiveIntegerField(default=0)
    last_view_alert_at = models.DateTimeField(null=True, blank=True)
    # E-mail code verification (the code itself is never stored or logged)
    verified_at = models.DateTimeField(null=True, blank=True)
    code_hash = models.CharField(max_length=64, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    code_attempts = models.PositiveSmallIntegerField(default=0)
    code_sent_at = models.DateTimeField(null=True, blank=True)
    code_window_start = models.DateTimeField(null=True, blank=True)
    code_window_count = models.PositiveSmallIntegerField(default=0)
    # Outcome
    signed_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'contracts_invitations'
        ordering = ['role', 'order', 'pk']
        indexes = [models.Index(fields=['status', 'expires_at'])]

    def __str__(self):
        return f'{self.contract.reference} v{self.version.version_number} → {self.email}'

    @property
    def is_open(self):
        return self.status in self.OPEN

    def is_expired(self, now=None):
        now = now or timezone.now()
        return bool(self.expires_at and self.expires_at <= now)


class ContractAccessToken(models.Model):
    """One opaque link token. Only an HMAC of the token is stored; the raw
    token exists only in the e-mail or the one page that showed it."""
    PURPOSE = 'contracts.invitation-link'
    invitation = models.ForeignKey(ContractInvitation, on_delete=models.CASCADE, related_name='tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    channel = models.CharField(max_length=10, choices=[('email', 'E-mail'), ('link', 'Copied link'),
                                                       ('reminder', 'Reminder e-mail')])
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_access_tokens'

    @classmethod
    def hash(cls, raw: str) -> str:
        from vault.secret_fields import hash_token
        return hash_token(raw or '', cls.PURPOSE)


class ContractSignature(models.Model):
    TYPED, DRAWN = 'typed', 'drawn'
    METHODS = [(TYPED, 'Typed'), (DRAWN, 'Drawn')]
    LINK, EMAIL_CODE, STAFF_ACCOUNT = 'link', 'email_code', 'staff_account'
    LEVELS = [(LINK, 'Link holder only (identity not verified)'),
              (EMAIL_CODE, 'E-mail code sent to the invited address'),
              (STAFF_ACCOUNT, 'Signed in to a staff account')]

    invitation = models.OneToOneField(ContractInvitation, on_delete=models.PROTECT, related_name='signature')
    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, related_name='signatures')
    role = models.CharField(max_length=10, choices=ContractSigner.ROLES)
    invited_name = models.CharField(max_length=200)
    invited_email = models.EmailField()
    printed_name = models.CharField(max_length=200)
    title = models.CharField(max_length=200, blank=True)
    method = models.CharField(max_length=6, choices=METHODS)
    typed_signature = models.CharField(max_length=200, blank=True)
    signature_image = models.TextField(blank=True, help_text='Drawn signature (re-encoded data:image/png).')
    signing_date = models.DateField()
    intent_text = models.CharField(max_length=500)
    consent_text = models.TextField()
    consent_hash = models.CharField(max_length=64)
    verification_level = models.CharField(max_length=14, choices=LEVELS)
    signed_at = models.DateTimeField(default=timezone.now)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    content_hash = models.CharField(max_length=64)
    snapshot_hash = models.CharField(max_length=64)
    pdf_hash = models.CharField(max_length=64, blank=True)
    evidence_hash = models.CharField(max_length=64)

    class Meta:
        db_table = 'contracts_signatures'
        ordering = ['signed_at']

    def __str__(self):
        return f'{self.printed_name} signed {self.version}'

    def evidence(self) -> dict:
        v = self.version
        return {
            'schema': 'clientst0r.contract-signature.v1',
            'contract': {'id': v.contract_id, 'reference': v.content.get('contract', {}).get('reference', '')},
            'version': {'id': v.pk, 'number': v.version_number, 'content_hash': self.content_hash,
                        'snapshot_hash': self.snapshot_hash, 'pdf_hash': self.pdf_hash},
            'invitation': {'id': self.invitation_id, 'role': self.role, 'invited_name': self.invited_name,
                           'invited_email': self.invited_email},
            'signer': {'printed_name': self.printed_name, 'title': self.title, 'method': self.method,
                       'typed_signature': self.typed_signature,
                       'signature_image_sha256': sha256(self.signature_image.encode('utf-8'))
                       if self.signature_image else ''},
            'signing_date': self.signing_date.isoformat(),
            'intent_text': self.intent_text,
            'consent_hash': self.consent_hash,
            'verification_level': self.verification_level,
            'signed_at': self.signed_at.isoformat(),
            'ip_address': self.ip_address or '',
            'user_agent': self.user_agent,
        }

    def evidence_json(self) -> bytes:
        return canonical_json(self.evidence())

    def verify(self) -> dict:
        v = self.version
        checks = {'bound': (self.content_hash, self.snapshot_hash, self.pdf_hash) == (
                      v.content_hash, v.snapshot_hash, v.pdf_hash),
                  'consent': sha256(self.consent_text.encode('utf-8')) == self.consent_hash,
                  'evidence': sha256(self.evidence_json()) == self.evidence_hash}
        checks.update({f'version_{k}': ok for k, ok in v.verify().items()})
        return checks

    def save(self, *args, **kwargs):
        if self.pk and ContractSignature.objects.filter(pk=self.pk).exists():
            raise ImmutableError('A signature record cannot be changed.')
        if not self.consent_hash:
            self.consent_hash = sha256(self.consent_text.encode('utf-8'))
        if not self.evidence_hash:
            self.evidence_hash = sha256(self.evidence_json())
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError('A signature record cannot be deleted.')


class ContractEvent(models.Model):
    """Append-only history. Normal operations only add rows; the retention
    task may blank the IP address and browser of old link/view events."""
    KINDS = [
        ('created', 'Created'), ('draft_edited', 'Draft edited'), ('submitted', 'Submitted for approval'),
        ('approved', 'Approved'), ('rejected', 'Approval rejected'), ('issued', 'Version issued'),
        ('sent', 'Sent'), ('invitation_issued', 'Invitation issued'), ('invitation_activated', 'Invitation active'),
        ('invitation_resent', 'Invitation resent'), ('invitation_revoked', 'Invitation revoked'),
        ('invitation_replaced', 'Invitation replaced'), ('invitation_expired', 'Invitation expired'),
        ('link_generated', 'Signing link generated'), ('email_queued', 'E-mail queued'),
        ('email_accepted', 'E-mail accepted by the mail server'), ('email_failed', 'E-mail failed'),
        ('reminder_queued', 'Reminder queued'), ('reminder_cancelled', 'Reminder cancelled'),
        ('link_requested', 'Link requested'), ('human_view', 'Likely human view'),
        ('verified_view', 'Verified signer view'), ('code_sent', 'Verification code sent'),
        ('code_verified', 'Verification succeeded'), ('code_failed', 'Verification failed'),
        ('consent', 'Electronic-signature consent given'), ('signed', 'Signed'), ('declined', 'Declined'),
        ('completed', 'All signatures complete'), ('finalized', 'Final PDF stored'),
        ('finalization_failed', 'Finalization failed'), ('superseded', 'Superseded'), ('voided', 'Voided'),
        ('expired', 'Expired'), ('downloaded', 'Copy downloaded'), ('notified', 'Staff notified'),
        ('billing_linked', 'Billing contract linked'), ('attachment_added', 'Attachment added'),
        ('attachment_removed', 'Attachment removed'),
    ]
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, related_name='events')
    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, null=True, blank=True,
                                related_name='events')
    invitation = models.ForeignKey(ContractInvitation, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='events')
    kind = models.CharField(max_length=24, choices=KINDS, db_index=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='+')
    actor_label = models.CharField(max_length=255, blank=True)
    message = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'contracts_events'
        ordering = ['-at', '-pk']

    def __str__(self):
        return f'{self.contract_id} {self.kind} {self.at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        if self.pk and ContractEvent.objects.filter(pk=self.pk).exists():
            raise ImmutableError('Contract history is append-only.')
        super().save(*args, **kwargs)


class ContractNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contract_notifications')
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=30)
    message = models.CharField(max_length=500)
    dedup_key = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_notifications'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['user', 'dedup_key'], name='contracts_notification_dedup')]


class ContractAlert(models.Model):
    """One alert decision. The unique key makes an alert happen once even when
    two requests race to raise it."""
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, related_name='alerts')
    key = models.CharField(max_length=200, unique=True)
    kind = models.CharField(max_length=30)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'contracts_alerts'


class ContractJob(models.Model):
    PENDING, RUNNING, DONE, FAILED, CANCELLED = 'pending', 'running', 'done', 'failed', 'cancelled'
    STATUSES = [(PENDING, 'Pending'), (RUNNING, 'Running'), (DONE, 'Done'), (FAILED, 'Failed (gave up)'),
                (CANCELLED, 'Cancelled')]
    KINDS = [('invitation_email', 'Invitation e-mail'), ('reminder_email', 'Reminder e-mail'),
             ('staff_email', 'Staff notification e-mail'), ('finalize', 'Finalize signed contract'),
             ('completed_copy', 'Signed copy to signer')]
    kind = models.CharField(max_length=20, choices=KINDS)
    contract = models.ForeignKey(ContractDocument, on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='jobs')
    version = models.ForeignKey(ContractVersion, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    invitation = models.ForeignKey(ContractInvitation, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='jobs')
    payload = models.JSONField(default=dict, blank=True, help_text='Never holds tokens or codes.')
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=6)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_jobs'
        ordering = ['next_attempt_at']
        indexes = [models.Index(fields=['status', 'next_attempt_at'])]

    def __str__(self):
        return f'{self.kind} {self.idempotency_key} ({self.status})'
