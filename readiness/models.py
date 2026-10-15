"""
Documentation readiness: what an MSP has decided must be documented for its
customers, and the per-customer exceptions it has accepted.

A DocumentationStandard says "for every customer in scope we must have
documented A, B, C". Each StandardRequirement is one checkable rule (see
`readiness.params` for the kinds and their parameters). Scores are computed
on read by `readiness.scoring`; nothing here stores a result.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import Organization


class DocumentationStandard(models.Model):
    SCOPE_ALL = 'all'
    SCOPE_ORG_TYPE = 'org_type'
    SCOPE_ASSET_TYPE = 'asset_type'
    SCOPE_CHOICES = [
        (SCOPE_ALL, 'Every customer'),
        (SCOPE_ORG_TYPE, 'Customers of a given type'),
        (SCOPE_ASSET_TYPE, 'Customers with assets of a given type'),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_ALL)
    # Organization.organization_type value for SCOPE_ORG_TYPE, Asset.asset_type
    # value for SCOPE_ASSET_TYPE, blank for SCOPE_ALL.
    scope_value = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(
        default=1, help_text='Bumped every time the standard or its requirements are edited.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='readiness_standards_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'readiness_standards'
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        from assets.models import Asset
        if self.scope == self.SCOPE_ALL:
            self.scope_value = ''
        elif self.scope == self.SCOPE_ORG_TYPE:
            valid = {k for k, _ in Organization.ORGANIZATION_TYPE_CHOICES if k}
            if self.scope_value not in valid:
                raise ValidationError({'scope_value': 'Choose a customer type.'})
        elif self.scope == self.SCOPE_ASSET_TYPE:
            valid = {k for k, _ in Asset.ASSET_TYPES}
            if self.scope_value not in valid:
                raise ValidationError({'scope_value': 'Choose an asset type.'})

    @property
    def scope_label(self):
        if self.scope == self.SCOPE_ORG_TYPE:
            label = dict(Organization.ORGANIZATION_TYPE_CHOICES).get(self.scope_value, self.scope_value)
            return f'Customers of type "{label}"'
        if self.scope == self.SCOPE_ASSET_TYPE:
            from assets.models import Asset
            label = dict(Asset.ASSET_TYPES).get(self.scope_value, self.scope_value)
            return f'Customers with {label} assets'
        return 'Every customer'


class StandardRequirement(models.Model):
    KIND_DOCUMENT_EXISTS = 'document_exists'
    KIND_DOCUMENT_FRESH = 'document_fresh'
    KIND_DOCUMENT_OWNER = 'document_owner'
    KIND_ASSET_FIELDS = 'asset_fields'
    KIND_CONTACT_ROLE = 'contact_role'
    KIND_CREDENTIAL_REFERENCE = 'credential_reference'
    KIND_RELATIONSHIP_PRESENT = 'relationship_present'
    KIND_CHOICES = [
        (KIND_DOCUMENT_EXISTS, 'Document exists'),
        (KIND_DOCUMENT_FRESH, 'Document reviewed recently'),
        (KIND_DOCUMENT_OWNER, 'Document has an owner'),
        (KIND_ASSET_FIELDS, 'Asset fields filled in'),
        (KIND_CONTACT_ROLE, 'Contact with a role'),
        (KIND_CREDENTIAL_REFERENCE, 'Credential reference exists'),
        (KIND_RELATIONSHIP_PRESENT, 'Assets linked to docs/contacts'),
    ]
    DOCUMENT_KINDS = (KIND_DOCUMENT_EXISTS, KIND_DOCUMENT_FRESH, KIND_DOCUMENT_OWNER)

    standard = models.ForeignKey(
        DocumentationStandard, on_delete=models.CASCADE, related_name='requirements')
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=40, choices=KIND_CHOICES)
    params = models.JSONField(default=dict, blank=True)
    weight = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(
        blank=True, help_text='Why this matters. Shown to whoever has to fix it.')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'readiness_requirements'
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    def clean(self):
        from .params import validate_params
        self.params = validate_params(self.kind, self.params or {})


class StandardExceptionQuerySet(models.QuerySet):
    def active(self, now=None):
        now = now or timezone.now()
        return self.filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))


class StandardException(models.Model):
    """An accepted gap: this customer does not need (all or one requirement
    of) this standard, for a stated reason, until `expires_at`."""
    standard = models.ForeignKey(
        DocumentationStandard, on_delete=models.CASCADE, related_name='exceptions')
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='readiness_exceptions')
    requirement = models.ForeignKey(
        StandardRequirement, on_delete=models.CASCADE, null=True, blank=True,
        related_name='exceptions',
        help_text='Blank = the whole standard is excepted for this customer.')
    reason = models.TextField()
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='readiness_exceptions_created')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StandardExceptionQuerySet.as_manager()

    class Meta:
        db_table = 'readiness_exceptions'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'standard'])]

    def __str__(self):
        target = self.requirement.title if self.requirement_id else 'all requirements'
        return f'{self.organization} / {self.standard}: {target}'

    def clean(self):
        if self.requirement_id and self.requirement.standard_id != self.standard_id:
            raise ValidationError({'requirement': 'That requirement belongs to another standard.'})

    @property
    def is_active(self):
        return self.expires_at is None or self.expires_at > timezone.now()
