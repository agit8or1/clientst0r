"""
Core models - Organization and Tags
"""
from django.db import models

from core.backgrounds import (
    DEFAULT_COLOR as DEFAULT_BACKGROUND_COLOR,
    DEFAULT_PRESET as DEFAULT_BACKGROUND_PRESET,
    PRESET_CHOICES as BACKGROUND_PRESET_CHOICES,
)
from django.utils.text import slugify
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class Organization(models.Model):
    """
    Multi-tenant organization/tenant model.
    All data is scoped to an organization.
    """
    # Organization Type Choices (common types, but allows custom values)
    TYPE_FULLY_MANAGED = 'fully_managed'
    TYPE_BREAK_FIX = 'break_fix'
    TYPE_COMANAGED = 'co_managed'
    TYPE_CONSULTING = 'consulting'
    TYPE_PROJECT_BASED = 'project_based'
    TYPE_INTERNAL = 'internal'
    TYPE_SUBCONTRACTOR = 'subcontractor'
    TYPE_OTHER = 'other'

    SUBCONTRACTOR_TYPE = TYPE_SUBCONTRACTOR  # alias used by Phase 7 outsourcing

    ORGANIZATION_TYPE_CHOICES = [
        ('', 'Not Specified'),
        (TYPE_FULLY_MANAGED, 'Fully Managed'),
        (TYPE_BREAK_FIX, 'Break/Fix'),
        (TYPE_COMANAGED, 'Co-Managed'),
        (TYPE_CONSULTING, 'Consulting Only'),
        (TYPE_PROJECT_BASED, 'Project-Based'),
        (TYPE_INTERNAL, 'Internal / Staff'),
        (TYPE_SUBCONTRACTOR, 'Subcontractor / Outsourcing Partner'),
        (TYPE_OTHER, 'Other'),
    ]

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    organization_type = models.CharField(
        max_length=50,
        choices=ORGANIZATION_TYPE_CHOICES,
        blank=True,
        default='',
        help_text="Client service type"
    )
    description = models.TextField(blank=True)

    # Company Information
    legal_name = models.CharField(max_length=255, blank=True, help_text="Full legal business name")
    tax_id = models.CharField(max_length=50, blank=True, help_text="Tax ID / EIN")

    # Address
    street_address = models.CharField(max_length=255, blank=True)
    street_address_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='United States', blank=True)

    # Contact Information
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    # Primary Contact Person
    primary_contact_name = models.CharField(max_length=255, blank=True)
    primary_contact_title = models.CharField(max_length=100, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=50, blank=True)

    # Branding
    logo = models.ImageField(upload_to='organizations/logos/', blank=True, null=True)
    portal_primary_color = models.CharField(
        max_length=20, blank=True,
        help_text='v3.17.233: hex color (e.g. #0d6efd) used as the primary '
                  'accent on this org\'s customer portal pages. Empty = '
                  'fall back to the system default.',
    )

    # --- Phase 7: Outsourcing partner fields --------------------------
    is_outsourcing_partner = models.BooleanField(
        default=False,
        help_text='When true, this org can receive outsourced tickets via the '
                  'share-ticket-to-partner endpoint. Requires partner_secret.',
    )
    partner_secret = models.CharField(
        max_length=64, blank=True,
        help_text='HMAC shared secret for verifying inbound webhook payloads. '
                  'Auto-generated when is_outsourcing_partner flips to True.',
    )
    partner_endpoint_url = models.URLField(
        blank=True,
        help_text='Inbound webhook URL on the partner side that should '
                  'receive ticket-share notifications.',
    )
    billing_markup_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Optional markup % applied to time entries logged by techs '
                  'from this partner org when billed back to the originating '
                  'client. 0 = no markup.',
    )

    # Phase 18 (v3.17.240): multi-location client hierarchy. A parent
    # organization (e.g. a holding company) sees its descendants' rows
    # via OrganizationManager.for_organization(); descendants stay
    # scoped to themselves. Set blank for top-level organizations.
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='children',
        help_text='Parent organization. Use for branch / division / '
                  'subsidiary structures. The parent\'s queries see '
                  'descendants\' rows; descendants stay scoped to themselves.',
    )

    # Phase 18 v9 (v3.17.282): regional grouping. Free-text tag — the
    # multi-location report groups child orgs under their region label.
    # Examples: "EMEA", "Northeast", "Bay Area".
    region = models.CharField(
        max_length=80, blank=True,
        help_text='Region / area tag — drives the multi-location report '
                  'grouping. Free-text, normalized to lowercase for grouping.',
    )

    # Phase 18 v7 (v3.17.282): site-level SLA overrides. JSON dict
    # keyed by priority code → {response_minutes, resolution_minutes}.
    # When set, the PSA SLA engine uses these instead of the contract
    # / queue defaults for tickets on this org.
    sla_overrides = models.JSONField(
        default=dict, blank=True,
        help_text='Per-priority SLA override map: '
                  '{"P1": {"response_minutes": 15, "resolution_minutes": 240}}. '
                  'Empty = inherit from contract / queue defaults.',
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    # Phase 23 v3.17.339 — exposure score
    exposure_score = models.PositiveIntegerField(
        default=0,
        help_text='Cached rolling security exposure score (0–1000). Recomputed by '
                  '`manage.py recompute_exposure_scores`. Severity-weighted sum of '
                  'open SecurityAlerts + open Vulnerabilities, scaled by asset count.',
    )
    exposure_score_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    @property
    def ancestors(self):
        """v3.17.240: walk up the parent chain (closest first)."""
        out = []
        node = self.parent
        seen = {self.pk}
        while node and node.pk not in seen:
            out.append(node)
            seen.add(node.pk)
            node = node.parent
        return out

    @property
    def breadcrumb_label(self):
        """`Parent → Child` for templates."""
        chain = list(reversed(self.ancestors))
        chain.append(self)
        return ' → '.join(o.name for o in chain)

    def sla_override_for(self, priority_code: str):
        """Phase 18 v7 (v3.17.282): look up the per-priority SLA
        override for this org, walking up the parent chain when not
        set locally. Returns a dict like
        ``{"response_minutes": N, "resolution_minutes": M}`` or None
        when nothing is configured at any level."""
        if not priority_code:
            return None
        for org in [self] + self.ancestors:
            data = org.sla_overrides or {}
            entry = data.get(priority_code)
            if entry:
                return entry
        return None

    @property
    def normalized_region(self) -> str:
        """Lowercased, stripped region tag for case-insensitive grouping."""
        return (self.region or '').strip().lower()

    def __str__(self):
        return self.name

    @property
    def full_address(self):
        """Get full formatted address."""
        parts = []
        if self.street_address:
            parts.append(self.street_address)
        if self.street_address_2:
            parts.append(self.street_address_2)
        if self.city and self.state and self.postal_code:
            parts.append(f"{self.city}, {self.state} {self.postal_code}")
        elif self.city:
            parts.append(self.city)
        if self.country and self.country != 'United States':
            parts.append(self.country)
        return ', '.join(parts) if parts else ''

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        # Phase 7: auto-generate HMAC partner secret when an org becomes an
        # outsourcing partner. Token is 64 hex chars (32 bytes).
        if self.is_outsourcing_partner and not self.partner_secret:
            import secrets
            self.partner_secret = secrets.token_hex(32)
        super().save(*args, **kwargs)


class BetaTesterRequest(models.Model):
    """
    v3.17.473 — anonymous sign-up to beta-test the mobile app.
    Submitted from a public form; superuser approves; the admin page
    shows the opt-in URL + the emails to paste into Play Console's
    Internal Testing tester list.
    """
    from django.conf import settings as _django_settings

    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('approved', 'Approved (give me the URL)'),
        ('added_to_play', 'Added to Play Console'),
        ('rejected', 'Rejected'),
    ]

    name = models.CharField(max_length=200)
    google_account_email = models.EmailField(
        help_text='The Gmail address signed into Play Store on the device '
                  'that will install the beta.',
    )
    company = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=200, blank=True)
    message = models.TextField(blank=True)
    heard_from = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        _django_settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='beta_tester_decisions',
    )
    decision_note = models.CharField(max_length=500, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)

    # v3.17.488 — when this row was forwarded from a remote install via
    # /core/beta-test/upstream/, this holds the origin host (e.g.
    # "https://customer-msp.example.com") so the operator can tell
    # which install the signup came from. Empty = local signup.
    source_install = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'core_beta_tester_requests'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status', '-submitted_at']),
            models.Index(fields=['google_account_email']),
        ]

    def __str__(self):
        return f'{self.name} <{self.google_account_email}> [{self.status}]'


class ConsultRequest(models.Model):
    """
    Free consultation request submitted via the About / MSP Reboot page.
    """
    # Contact info
    name = models.CharField(max_length=255)
    email = models.EmailField()
    company = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=50, blank=True)

    # Areas of interest — stored as comma-separated keys
    areas_of_interest = models.TextField(blank=True, help_text="Comma-separated area keys")

    # Free-form details
    description = models.TextField(blank=True, help_text="Tell us about your situation")
    best_time = models.CharField(max_length=100, blank=True, help_text="Best time to reach you")
    heard_from = models.CharField(max_length=255, blank=True, help_text="How did you hear about us?")

    # Meta
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    notes = models.TextField(blank=True, help_text="Internal notes")

    AREA_CHOICES = [
        ('sales', 'Sales & New Business'),
        ('growth', 'Business Growth'),
        ('technical', 'Technical Challenges'),
        ('margins', 'Margin Improvement'),
        ('efficiency', 'Operational Efficiency'),
        ('tools', 'Tool Consolidation / Stack'),
        ('security', 'Security & Compliance'),
        ('staff', 'Staff & HR'),
        ('processes', 'MSP Processes & Workflows'),
        ('pricing', 'Pricing Strategy'),
        ('other', 'Other'),
    ]

    class Meta:
        db_table = 'consult_requests'
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.name} ({self.email}) — {self.submitted_at:%Y-%m-%d}"

    def get_areas_list(self):
        if not self.areas_of_interest:
            return []
        return [a.strip() for a in self.areas_of_interest.split(',') if a.strip()]

    def get_areas_display(self):
        area_map = dict(self.AREA_CHOICES)
        return [area_map.get(a, a) for a in self.get_areas_list()]


class SupportRating(models.Model):
    """
    Admin-assigned support difficulty ratings for an organization, broken down by category.
    One record per organization + category (upserted on save).
    """
    CATEGORY_APPLICATION = 'application'
    CATEGORY_NETWORK = 'network'
    CATEGORY_CUSTOMER = 'customer'
    CATEGORY_HARDWARE = 'hardware'
    CATEGORY_OVERALL = 'overall'

    CATEGORY_CHOICES = [
        (CATEGORY_APPLICATION, 'Application'),
        (CATEGORY_NETWORK, 'Network'),
        (CATEGORY_CUSTOMER, 'Customer / Users'),
        (CATEGORY_HARDWARE, 'Hardware'),
        (CATEGORY_OVERALL, 'Overall'),
    ]

    RATING_CHOICES = [
        (1, 'Low'),
        (2, 'Moderate'),
        (3, 'Elevated'),
        (4, 'High'),
        (5, 'Critical'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='support_ratings'
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    notes = models.CharField(max_length=255, blank=True)
    rated_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'support_ratings'
        unique_together = [['organization', 'category']]
        ordering = ['category']

    def __str__(self):
        return f"{self.organization} — {self.get_category_display()}: {self.get_rating_display()}"

    @property
    def color_class(self):
        return {1: 'success', 2: 'info', 3: 'warning', 4: 'orange', 5: 'danger'}.get(self.rating, 'secondary')

    @property
    def badge_style(self):
        """Inline style for the orange level which Bootstrap doesn't have natively."""
        if self.rating == 4:
            return 'background-color:#fd7e14;color:#fff;'
        return ''


class Tag(models.Model):
    """
    Generic tagging model for various entities.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    color = models.CharField(max_length=7, default='#6c757d')  # Hex color
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tags'
        unique_together = [['organization', 'slug']]
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class BaseModel(models.Model):
    """
    Abstract base model with common fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Relation(BaseModel):
    """
    Generic relationship model that can link any two objects.
    Links from 'source' to 'target' with a relationship type.

    Examples:
    - Asset -> Document (relation_type='documented_by')
    - Asset -> Password (relation_type='credentials')
    - Document -> Asset (relation_type='applies_to')
    - Contact -> Asset (relation_type='responsible_for')
    """
    RELATION_TYPES = [
        ('applies_to', 'Applies To'),
        ('contains', 'Contains'),
        ('credentials', 'Credentials'),
        ('depends_on', 'Depends On'),
        ('documented_by', 'Documented By'),
        ('related_to', 'Related To'),
        ('responsible_for', 'Responsible For'),
        ('used_by', 'Used By'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='relations')
    relation_type = models.CharField(max_length=50, choices=RELATION_TYPES, default='related_to')

    # Source object (what is linking)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='source_relations'
    )
    source_object_id = models.PositiveIntegerField()
    source_object = GenericForeignKey('source_content_type', 'source_object_id')

    # Target object (what is being linked to)
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='target_relations'
    )
    target_object_id = models.PositiveIntegerField()
    target_object = GenericForeignKey('target_content_type', 'target_object_id')

    # Optional description/notes about the relationship
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'relations'
        indexes = [
            models.Index(fields=['organization', 'source_content_type', 'source_object_id']),
            models.Index(fields=['organization', 'target_content_type', 'target_object_id']),
            models.Index(fields=['relation_type']),
        ]

    def __str__(self):
        return f"{self.source_object} -> {self.get_relation_type_display()} -> {self.target_object}"

    def get_source_type(self):
        """Get human-readable source type."""
        return self.source_content_type.model

    def get_target_type(self):
        """Get human-readable target type."""
        return self.target_content_type.model


class Favorite(models.Model):
    """
    Generic favorites/bookmarks system.
    Users can favorite any object type (passwords, documents, assets, etc).
    """
    from django.contrib.auth.models import User

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='favorites', null=True, blank=True)

    # Generic relation to any favoritable object
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # Optional notes about why favorited
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'favorites'
        unique_together = [['user', 'content_type', 'object_id']]
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'content_type']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} favorited {self.content_object}"


class SecureNote(BaseModel):
    """
    Encrypted notes that can be sent securely between users.
    Notes are encrypted and can have expiration/read-once behavior.
    """
    from django.contrib.auth.models import User

    # Sender
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_secure_notes')

    # Recipients (many-to-many for group sharing)
    recipients = models.ManyToManyField(User, related_name='received_secure_notes')

    # Organization context (optional)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='secure_notes', null=True, blank=True)

    # Content
    title = models.CharField(max_length=255)
    encrypted_content = models.TextField()  # Encrypted message body
    label = models.CharField(max_length=255, blank=True, help_text='Optional label for tracking/organizing secret links')

    # Link-only mode (Issue #47)
    link_only = models.BooleanField(default=False, help_text='Link-only mode: no recipients, share via URL')
    access_token = models.CharField(max_length=64, unique=True, blank=True, help_text='Unique token for link-only access')

    # Security settings
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Auto-delete after this time')
    read_once = models.BooleanField(default=False, help_text='Delete after first read')
    require_password = models.BooleanField(default=False, help_text='Require password to decrypt')
    access_password = models.CharField(max_length=255, blank=True, help_text='Hashed password for access')

    # Phase 3: Advanced features (Issue #47)
    max_views = models.PositiveIntegerField(null=True, blank=True, help_text='Maximum number of views before auto-expiring')

    # Tracking
    read_by = models.ManyToManyField(User, related_name='read_secure_notes', blank=True)
    read_count = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'secure_notes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sender', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"SecureNote from {self.sender.username}: {self.title}"

    def set_content(self, plaintext_content):
        """Encrypt and store content."""
        from vault.encryption import encrypt
        self.encrypted_content = encrypt(plaintext_content)

    def get_content(self):
        """Decrypt and return content."""
        from vault.encryption import decrypt
        if not self.encrypted_content:
            return ''
        return decrypt(self.encrypted_content)

    def generate_access_token(self):
        """Generate a unique cryptographically secure access token for link-only mode."""
        import secrets
        self.access_token = secrets.token_urlsafe(48)
        return self.access_token

    def get_share_url(self, request=None):
        """Get the shareable URL for link-only mode."""
        if not self.link_only or not self.access_token:
            return None
        from django.urls import reverse
        path = reverse('core:secure_note_view_link', kwargs={'token': self.access_token})
        if request:
            return request.build_absolute_uri(path)
        return path

    def mark_as_read(self, user):
        """Mark note as read by user."""
        if user not in self.read_by.all():
            self.read_by.add(user)
            self.read_count += 1
            self.save(update_fields=['read_count'])

            # Delete if read_once is enabled
            if self.read_once:
                self.is_deleted = True
                self.save(update_fields=['is_deleted'])

    def can_be_read_by(self, user):
        """Check if user can read this note."""
        if self.is_deleted:
            return False
        if self.sender == user:
            return True
        # Link-only notes can be read by anyone with the link
        if self.link_only:
            return True
        return user in self.recipients.all()

    @property
    def is_expired(self):
        """Check if note has expired."""
        if not self.expires_at:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at


class SystemSetting(models.Model):
    """
    Global system settings stored in database.
    Singleton pattern - only one instance should exist.
    """
    # General Settings
    site_name = models.CharField(max_length=255, default='Client St0r')
    site_url = models.URLField(max_length=500, blank=True, help_text='Base URL for email links')
    default_timezone = models.CharField(max_length=50, default='UTC', help_text='Default timezone for new users')

    # Whitelabeling Settings
    custom_company_name = models.CharField(max_length=255, blank=True, help_text='Custom company name (replaces Client St0r branding)')
    custom_logo = models.ImageField(upload_to='branding/', blank=True, null=True, help_text='Custom logo (recommended: 200x40px PNG with transparent background)')

    # GeoIP map backdrop (v3.17.522) — styling for the click-to-select world
    # map on the firewall + vault access-rule screens. Purely cosmetic; it never
    # affects which countries are blocked.
    GEOIP_MAP_BACKGROUND_MODES = [
        ('pattern', 'Colour pattern'),
        ('random', 'Random (a different pattern each visit)'),
        ('image', 'Uploaded image'),
    ]
    GEOIP_MAP_PATTERNS = [
        ('slate', 'Slate'),
        ('ocean', 'Ocean'),
        ('midnight', 'Midnight'),
        ('terrain', 'Terrain'),
        ('sunset', 'Sunset'),
        ('mono', 'Mono'),
    ]
    geoip_map_background_mode = models.CharField(
        max_length=20, default='pattern', choices=GEOIP_MAP_BACKGROUND_MODES,
        help_text='Backdrop behind the GeoIP world map.')
    geoip_map_background_pattern = models.CharField(
        max_length=40, default='slate', choices=GEOIP_MAP_PATTERNS,
        help_text="Which colour pattern to use when the mode is 'pattern'.")
    geoip_map_background_image = models.ImageField(
        upload_to='branding/geoip/', blank=True, null=True,
        help_text="Backdrop image used when the mode is 'image'.")
    custom_logo_height = models.PositiveIntegerField(default=30, help_text='Logo height in pixels (default: 30px)')

    # App background policy (v3.17.527) — system-wide control over the page
    # backdrop. Shaped like the GeoIP backdrop above, but with one extra mode:
    # 'user' hands the decision back to each person's own profile settings,
    # which is what happened unconditionally before this existed and stays the
    # default so upgrades change nothing.
    #
    # Any other value is enforced: the profile controls are disabled and the
    # policy wins for everyone. Users still see their controls, greyed out with
    # an explanation — hiding them entirely just moves the confusion.
    BACKGROUND_POLICIES = [
        ('user', 'User controlled — each person picks their own'),
        ('image', 'Static image — one uploaded image for everyone'),
        ('color', 'Colour or pattern — one look for everyone'),
        ('random', 'Random images — a different image each page load'),
    ]
    BACKGROUND_COLOR_STYLES = [
        ('solid', 'Solid colour'),
        ('preset', 'Preset pattern'),
    ]
    # A class attribute, not just the module-level import, so the settings
    # template can iterate it the same way as the two lists above.
    BACKGROUND_PRESET_CHOICES = BACKGROUND_PRESET_CHOICES
    background_policy = models.CharField(
        max_length=20, default='user', choices=BACKGROUND_POLICIES,
        help_text='Who decides the app background. Anything other than '
                  "'user controlled' overrides every user's own setting.")
    background_image = models.ImageField(
        upload_to='branding/backgrounds/', blank=True, null=True,
        help_text="Background image used when the policy is 'static image'.")
    background_color_style = models.CharField(
        max_length=20, default='solid', choices=BACKGROUND_COLOR_STYLES,
        help_text="Solid colour or preset pattern, when the policy is 'colour'.")
    background_color = models.CharField(
        max_length=7, default=DEFAULT_BACKGROUND_COLOR, blank=True,
        help_text='Hex colour used when the colour style is solid.')
    background_preset = models.CharField(
        max_length=40, default=DEFAULT_BACKGROUND_PRESET, blank=True,
        choices=BACKGROUND_PRESET_CHOICES,
        help_text='Which preset pattern to use when the colour style is preset.')

    # Security Settings
    session_timeout_minutes = models.PositiveIntegerField(default=480, help_text='Session timeout in minutes (default: 8 hours)')
    require_2fa = models.BooleanField(default=True, help_text='Require 2FA for all users')
    password_min_length = models.PositiveIntegerField(default=12, help_text='Minimum password length')
    password_require_special = models.BooleanField(default=True, help_text='Require special characters in passwords')
    failed_login_attempts = models.PositiveIntegerField(default=5, help_text='Max failed login attempts before lockout')
    lockout_duration_minutes = models.PositiveIntegerField(default=30, help_text='Account lockout duration')

    # SMTP/Email Settings
    smtp_enabled = models.BooleanField(default=False, help_text='Enable email notifications')
    smtp_host = models.CharField(max_length=255, blank=True, help_text='SMTP server hostname')
    smtp_port = models.PositiveIntegerField(default=587, help_text='SMTP server port')
    smtp_username = models.CharField(max_length=255, blank=True, help_text='SMTP username')
    smtp_password = models.CharField(max_length=255, blank=True, help_text='SMTP password (encrypted)')
    smtp_use_tls = models.BooleanField(default=True, help_text='Use TLS for SMTP')
    smtp_use_ssl = models.BooleanField(default=False, help_text='Use SSL for SMTP')
    smtp_from_email = models.EmailField(blank=True, help_text='From email address')
    smtp_from_name = models.CharField(max_length=255, default='Client St0r', help_text='From name')

    # Notification Settings
    notify_on_user_created = models.BooleanField(default=True, help_text='Notify admins when users are created')
    notify_on_ssl_expiry = models.BooleanField(default=True, help_text='Send SSL expiration warnings')
    notify_on_domain_expiry = models.BooleanField(default=True, help_text='Send domain expiration warnings')
    notify_on_password_expiry = models.BooleanField(default=True, help_text='Send vault password expiration warnings')
    ssl_expiry_warning_days = models.PositiveIntegerField(default=30, help_text='Days before SSL expiry to warn')
    domain_expiry_warning_days = models.PositiveIntegerField(default=60, help_text='Days before domain expiry to warn')
    password_expiry_warning_days = models.PositiveIntegerField(default=14, help_text='Days before vault password expiry to warn')

    # LDAP/Active Directory Settings
    ldap_enabled = models.BooleanField(default=False, help_text='Enable LDAP/Active Directory authentication')
    ldap_server_uri = models.CharField(max_length=500, blank=True, help_text='LDAP server URI (e.g., ldap://dc.example.com:389)')
    ldap_bind_dn = models.CharField(max_length=500, blank=True, help_text='Bind DN for LDAP queries (e.g., CN=ServiceAccount,OU=Users,DC=example,DC=com)')
    ldap_bind_password = models.CharField(max_length=255, blank=True, help_text='Password for bind DN (encrypted)')
    ldap_user_search_base = models.CharField(max_length=500, blank=True, help_text='Base DN for user searches (e.g., OU=Users,DC=example,DC=com)')
    ldap_user_search_filter = models.CharField(max_length=255, default='(sAMAccountName=%(user)s)', help_text='LDAP filter for user lookups')
    ldap_group_search_base = models.CharField(max_length=500, blank=True, help_text='Base DN for group searches (optional)')
    ldap_require_group = models.CharField(max_length=500, blank=True, help_text='Require membership in this group (DN, optional)')
    ldap_start_tls = models.BooleanField(default=True, help_text='Use StartTLS for secure connection')

    # Azure AD / Microsoft Entra ID Settings
    azure_ad_enabled = models.BooleanField(default=False, help_text='Enable Azure AD / Microsoft Entra ID authentication')
    azure_ad_tenant_id = models.CharField(max_length=255, blank=True, help_text='Azure AD Tenant ID (GUID)')
    azure_ad_client_id = models.CharField(max_length=255, blank=True, help_text='Application (client) ID from Azure portal')
    azure_ad_client_secret = models.CharField(max_length=500, blank=True, help_text='Client secret (encrypted)')
    azure_ad_redirect_uri = models.CharField(max_length=500, blank=True, help_text='Redirect URI configured in Azure (e.g., https://yourapp.com/auth/callback)')
    azure_ad_auto_create_users = models.BooleanField(default=True, help_text='Automatically create users on first Azure AD login')
    azure_ad_sync_groups = models.BooleanField(default=False, help_text='Sync Azure AD groups to roles')

    # Snyk Security Scanning Settings
    snyk_enabled = models.BooleanField(default=False, help_text='Enable Snyk security scanning')
    snyk_api_token = models.CharField(max_length=500, blank=True, help_text='Snyk API token for vulnerability scanning')
    snyk_org_id = models.CharField(max_length=255, blank=True, help_text='Snyk organization ID (optional)')
    snyk_severity_threshold = models.CharField(
        max_length=20,
        default='high',
        choices=[
            ('critical', 'Critical'),
            ('high', 'High'),
            ('low', 'Low'),
            ('medium', 'Medium'),
        ],
        help_text='Minimum severity level to report'
    )
    snyk_scan_frequency = models.CharField(
        max_length=20,
        default='daily',
        choices=[
            ('daily', 'Daily'),
            ('hourly', 'Every Hour'),
            ('manual', 'Manual Only'),
            ('weekly', 'Weekly'),
        ],
        help_text='How often to run automatic scans'
    )
    snyk_last_scan = models.DateTimeField(null=True, blank=True, help_text='Timestamp of last Snyk scan')

    # Snyk Product Selection
    snyk_test_open_source = models.BooleanField(default=True, help_text='Scan dependencies with Snyk Open Source (snyk test)')
    snyk_test_code = models.BooleanField(default=False, help_text='Scan source code with Snyk Code (snyk code test) - Requires Snyk Code enabled in dashboard')
    snyk_test_container = models.BooleanField(default=False, help_text='Scan Docker images with Snyk Container (snyk container test)')
    snyk_test_iac = models.BooleanField(default=False, help_text='Scan IaC files with Snyk IaC (snyk iac test)')

    # Bug Reporting
    github_pat = models.CharField(max_length=500, blank=True, help_text='GitHub Personal Access Token for bug reporting (encrypted)')

    # SMS Provider Settings
    sms_provider = models.CharField(
        max_length=20,
        default='twilio',
        choices=[
            ('twilio', 'Twilio'),
            ('plivo', 'Plivo'),
            ('sinch', 'Sinch'),
            ('vonage', 'Vonage/Nexmo'),
            ('aws_sns', 'AWS SNS'),
            ('telnyx', 'Telnyx'),
        ],
        help_text='SMS provider for sending navigation links and notifications'
    )
    sms_enabled = models.BooleanField(default=False, help_text='Enable SMS functionality')
    sms_account_sid = models.CharField(max_length=255, blank=True, help_text='SMS provider account SID/API key')
    sms_auth_token = models.CharField(max_length=500, blank=True, help_text='SMS provider auth token (encrypted)')
    sms_from_number = models.CharField(max_length=20, blank=True, help_text='From phone number (E.164 format, e.g., +15551234567)')

    # Feature Toggles
    monitoring_enabled = models.BooleanField(default=True, help_text='Enable Monitoring feature (Website & Service Monitoring)')
    global_kb_enabled = models.BooleanField(default=True, help_text='Enable Global Knowledge Base (Staff-only shared KB)')
    workflows_enabled = models.BooleanField(default=True, help_text='Enable Workflows & Automation feature')
    locations_map_enabled = models.BooleanField(default=True, help_text='Enable location maps and geocoding features')
    secure_notes_enabled = models.BooleanField(default=True, help_text='Enable secure ephemeral notes feature')
    reports_enabled = models.BooleanField(default=True, help_text='Enable Reports & Analytics feature')
    webhooks_enabled = models.BooleanField(default=True, help_text='Enable Webhooks for event notifications')
    vehicles_enabled = models.BooleanField(default=True, help_text='Enable service vehicle fleet management features')
    inventory_enabled = models.BooleanField(default=True, help_text='Enable Inventory management')
    scheduling_enabled = models.BooleanField(default=True, help_text='Enable Scheduling and Task Management')
    psa_enabled = models.BooleanField(default=False, help_text='Enable native PSA / Service Desk feature (off by default)')
    crm_enabled = models.BooleanField(default=False, help_text='Enable CRM / sales pipeline (leads, opportunities, campaigns, commissions). Off by default.')
    psa_portal_enabled = models.BooleanField(default=False, help_text='Allow customer portal access for PSA clients')
    psa_anonymous_ticket_form_enabled = models.BooleanField(default=False, help_text='Allow public/anonymous ticket submissions')
    psa_email_to_ticket_enabled = models.BooleanField(default=False, help_text='Convert inbound emails to tickets')
    psa_sms_notifications_enabled = models.BooleanField(default=False, help_text='Send SMS to staff (no secrets in body)')
    psa_desktop_alerts_enabled = models.BooleanField(default=False, help_text='Send desktop / browser alerts to staff')
    psa_external_alert_ingest_enabled = models.BooleanField(default=False, help_text='Accept alerts from external monitoring/RMM webhooks')
    psa_csat_enabled = models.BooleanField(
        default=False,
        help_text='Email a 1-5 star CSAT survey link to the requester when '
                  'a ticket is resolved/closed. Off by default — enable '
                  'after vetting your post-close email content.',
    )
    # Phase 12 feature toggles (v3.17.243). All default off so existing
    # installs don't suddenly expose new portal endpoints — admins flip
    # them on after they've been deliberate about each.
    psa_portal_announcements_enabled = models.BooleanField(
        default=False,
        help_text='Render portal announcements on the customer portal home '
                  'and expose the dismiss endpoint.',
    )
    psa_portal_voting_enabled = models.BooleanField(
        default=False,
        help_text='Let portal users "I\'m affected too" vote on tickets they '
                  'can see.',
    )
    psa_portal_escalation_enabled = models.BooleanField(
        default=False,
        help_text='Let portal users escalate one of their tickets directly '
                  '(stamps escalated_at/by/reason + posts a public comment).',
    )
    psa_portal_customer_approvals_enabled = models.BooleanField(
        default=False,
        help_text='Show pending PSAApproval rows flagged is_client_approval '
                  'to portal users + accept their decisions.',
    )
    # Phase 20 v2 (v3.17.259) — financial approval thresholds. When set,
    # a post-save signal auto-flags `Invoice.requires_approval=True` for
    # any invoice that crosses either threshold. 0 = disabled.
    invoice_approval_threshold_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Auto-flag invoices for manager approval when total >= '
                  'this dollar amount. 0 = disabled.',
    )
    invoice_approval_overage_pct = models.PositiveIntegerField(
        default=0,
        help_text='Auto-flag invoices when their source contract is at >= '
                  'this consumed-percent. 0 = disabled.',
    )
    # Phase 20 v5 (v3.17.273) — conditional approval routing on Quote.
    quote_approval_threshold_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Auto-create a PSAApproval chain when a Quote\'s total '
                  '>= this dollar amount. 0 = disabled.',
    )

    # Phase 15 v7 (v3.17.294) — late fee automation. When both knobs
    # are non-zero, the `psa_apply_late_fees` cron applies a fee Charge
    # to every overdue invoice once per overdue period.
    late_fee_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text='Late fee percent of overdue balance (e.g. 1.5 = 1.5%%). '
                  '0 = disabled.',
    )
    late_fee_min_days_overdue = models.PositiveIntegerField(
        default=15,
        help_text='Days past due_date before a late fee is applied.',
    )

    # Phase 15 v11 (v3.17.299) — invoice automation: auto-push
    # contract-generated invoices to the configured AccountingConnection
    # the moment they're created. Off by default so installs that
    # want to review drafts first aren't surprised.
    psa_auto_push_recurring_invoices = models.BooleanField(
        default=False,
        help_text='When True, the recurring-invoice cron also pushes each '
                  'newly-generated draft Invoice to the org\'s configured '
                  'sync-enabled AccountingConnection. Off by default.',
    )

    # Billing defaults — used by the quote and invoice forms when the
    # specific row doesn't override.
    psa_default_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=0,
        help_text='Default tax rate for new quotes / invoices (e.g. 0.0875 for 8.75%). Each quote/invoice can still override.',
    )
    psa_default_currency = models.CharField(
        max_length=8, default='USD',
        help_text='Default currency for new invoices (ISO 4217 code).',
    )

    # PSA AI Assist (Workstream 10) — admin-controlled at top level
    # API keys / provider / model selection live on the existing
    # /core/settings/ai/ page which writes to .env (ANTHROPIC_API_KEY,
    # CLAUDE_MODEL). The fields here are PSA-behavior-specific only.
    psa_ai_enabled = models.BooleanField(default=False, help_text='Enable AI Suggested Replies + Suggested Actions on PSA tickets (off by default)')
    psa_ai_min_confidence = models.DecimalField(max_digits=4, decimal_places=2, default=0.75, help_text='Suggestions below this confidence (0–1) are shown collapsed and cannot be one-click approved.')
    psa_ai_suggestion_ttl_minutes = models.PositiveIntegerField(default=60, help_text='Suggestions older than this auto-expire (cannot be applied).')
    psa_ai_daily_token_limit = models.PositiveIntegerField(default=200000, help_text='Per-organization daily token budget. AI generation stops for the day at this limit.')
    psa_ai_per_user_daily_limit = models.PositiveIntegerField(default=50000, help_text='Per-user daily token cap (anti-abuse — one user cannot drain the org pool).')
    psa_ai_per_user_rate_per_min = models.PositiveIntegerField(default=10, help_text='Max AI generations per user per minute (anti-abuse).')
    psa_ai_max_output_tokens = models.PositiveIntegerField(default=2000, help_text='Hard cap on a single AI response — prevents runaway costs / over-long replies.')
    psa_ai_voice = models.TextField(blank=True, default='Professional, concise, confident.', help_text='Free-form sentence injected into the system prompt — sets the MSP voice/tone.')
    psa_ai_blocked_subject_keywords = models.TextField(blank=True, help_text='Newline-separated; suggestions are skipped when the ticket subject matches any of these (case-insensitive substring match).')

    # Asset Health Features
    asset_age_warnings_enabled = models.BooleanField(default=False, help_text='Show warnings when assets approach or exceed their age threshold')
    asset_age_warning_years = models.PositiveIntegerField(default=3, help_text='Age (years) at which to show a yellow warning for assets without a lifespan set')
    asset_age_critical_years = models.PositiveIntegerField(default=5, help_text='Age (years) at which to show a red critical warning for assets without a lifespan set')
    firmware_checks_enabled = models.BooleanField(default=False, help_text='Enable automatic firmware update checks for network devices (Ubiquiti, TP-Link, Grandstream, etc.)')
    warranty_checks_enabled = models.BooleanField(default=False, help_text='Enable warranty expiry lookups for PCs and servers via vendor APIs (Dell, HP, Lenovo)')
    dell_api_key = models.CharField(max_length=255, blank=True, help_text='Dell TechDirect API key for warranty lookups')
    hp_client_id = models.CharField(max_length=255, blank=True, help_text='HP API client ID for warranty lookups')
    hp_client_secret = models.CharField(max_length=255, blank=True, help_text='HP API client secret for warranty lookups')
    lenovo_client_id = models.CharField(max_length=255, blank=True, help_text='Lenovo warranty API client ID')
    lenovo_client_secret = models.CharField(max_length=255, blank=True, help_text='Lenovo warranty API client secret')

    # UI/UX Settings
    stay_on_page_after_org_switch = models.BooleanField(default=True, help_text='Stay on current page when switching organizations instead of redirecting to dashboard')

    # Map Settings (Issue #57)
    map_default_zoom = models.PositiveIntegerField(default=4, help_text='Default zoom level for dashboard maps (1-18)')
    map_dragging_enabled = models.BooleanField(default=True, help_text='Enable map dragging by default (can be toggled per-map)')
    global_locations_map_enabled = models.BooleanField(default=True, help_text='Enable global locations map for superusers and staff')

    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='system_settings_updates')

    class Meta:
        db_table = 'system_settings'
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'

    def __str__(self):
        return f"System Settings (Updated: {self.updated_at})"

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """Enforce singleton pattern."""
        self.pk = 1
        super().save(*args, **kwargs)

    def get_smtp_password_decrypted(self):
        """Get decrypted SMTP password."""
        if not self.smtp_password:
            return ''
        try:
            from vault.encryption import decrypt
            return decrypt(self.smtp_password)
        except Exception:
            # If decryption fails, assume it's not encrypted (backward compatibility)
            return self.smtp_password

    def get_ldap_bind_password_decrypted(self):
        """Get decrypted LDAP bind password."""
        if not self.ldap_bind_password:
            return ''
        try:
            from vault.encryption_v2 import decrypt_api_credentials
            return decrypt_api_credentials(self.ldap_bind_password, org_id=0)
        except Exception:
            # If decryption fails, assume it's not encrypted (backward compatibility)
            return self.ldap_bind_password

    def get_azure_ad_client_secret_decrypted(self):
        """Get decrypted Azure AD client secret."""
        if not self.azure_ad_client_secret:
            return ''
        try:
            from vault.encryption_v2 import decrypt_api_credentials
            return decrypt_api_credentials(self.azure_ad_client_secret, org_id=0)
        except Exception:
            # If decryption fails, assume it's not encrypted (backward compatibility)
            return self.azure_ad_client_secret

    def delete(self, *args, **kwargs):
        """Prevent deletion of settings."""
        pass


class ScheduledTask(models.Model):
    """
    Database-driven task scheduler.
    Defines recurring tasks with their schedules.
    """
    TASK_TYPES = [
        ('asset_age_check', 'Asset Age Warning Check'),
        ('cleanup_stuck_scans', 'Cleanup Stuck Security Scans'),
        ('domain_expiry_check', 'Domain Expiry Check'),
        ('equipment_catalog_update', 'Equipment Catalog Update'),
        ('firmware_check', 'Firmware Update Check'),
        ('password_breach_scan', 'Password Breach Scanning'),
        ('python_dep_scan', 'Python Dependency Vulnerability Scan'),
        ('system_warnings_digest', 'System Warnings Digest Email'),
        ('vault_password_expiry', 'Vault Password Expiry Notifications'),
        # Phase 40.1 (v3.17.538). Trims the website check history that uptime
        # percentages are computed from — the highest-volume table in the app.
        ('prune_monitor_checks', 'Prune Website Check History'),
        ('psa_sync', 'PSA Synchronization'),
        # Phase 44.3 (v3.17.531). A systemd timer is also shipped; this
        # entry is for installs that run the in-app scheduler instead.
        ('accounting_sync', 'Accounting Sync (QuickBooks Online / Xero)'),
        ('rmm_sync', 'RMM Synchronization'),
        ('scheduling_alerts', 'Scheduled Task Alerts'),
        ('security_scan', 'Automated Security Scan'),
        ('ssl_expiry_check', 'SSL Certificate Expiry Check'),
        ('update_check', 'System Update Check'),
        ('warranty_check', 'Warranty Expiry Check'),
        ('website_monitoring', 'Website Monitoring Checks'),
    ]

    task_type = models.CharField(max_length=50, choices=TASK_TYPES, unique=True)
    description = models.TextField(blank=True)

    # Schedule configuration
    enabled = models.BooleanField(default=True, help_text='Enable/disable this scheduled task')
    interval_minutes = models.PositiveIntegerField(
        default=5,
        help_text='How often to run this task (in minutes)'
    )

    # Execution tracking
    last_run_at = models.DateTimeField(null=True, blank=True, help_text='Last successful execution time')
    next_run_at = models.DateTimeField(null=True, blank=True, help_text='Next scheduled execution time')
    last_status = models.CharField(
        max_length=20,
        choices=[
            ('failed', 'Failed'),
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('success', 'Success'),
        ],
        default='pending'
    )
    last_error = models.TextField(blank=True, help_text='Last error message if failed')
    run_count = models.PositiveIntegerField(default=0, help_text='Total number of executions')

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduled_tasks'
        ordering = ['task_type']

    def __str__(self):
        return f"{self.get_task_type_display()} (every {self.interval_minutes} min)"

    def should_run(self):
        """Check if this task should run now based on schedule."""
        if not self.enabled:
            return False

        # Never run if status is 'running' (prevent overlapping executions)
        if self.last_status == 'running':
            return False

        from django.utils import timezone
        now = timezone.now()

        # If never run, should run
        if not self.last_run_at:
            return True

        # Check if next_run_at is in the past
        if self.next_run_at and now >= self.next_run_at:
            return True

        return False

    def calculate_next_run(self):
        """Calculate the next run time based on interval."""
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        if self.last_run_at:
            self.next_run_at = self.last_run_at + timedelta(minutes=self.interval_minutes)
        else:
            self.next_run_at = now + timedelta(minutes=self.interval_minutes)

    def mark_started(self):
        """Mark task as started."""
        from django.utils import timezone
        self.last_status = 'running'
        self.last_run_at = timezone.now()
        self.save(update_fields=['last_status', 'last_run_at'])

    def mark_completed(self, error=None):
        """Mark task as completed (success or failed)."""
        from django.utils import timezone

        if error:
            self.last_status = 'failed'
            self.last_error = str(error)
        else:
            self.last_status = 'success'
            self.last_error = ''

        self.run_count += 1
        self.calculate_next_run()
        self.save(update_fields=['last_status', 'last_error', 'run_count', 'next_run_at'])

    @classmethod
    def get_or_create_defaults(cls):
        """Create default scheduled tasks if they don't exist."""
        defaults = [
            {
                'task_type': 'website_monitoring',
                'description': 'Check website monitor statuses and SSL certificates',
                'interval_minutes': 5,
                'enabled': True,
            },
            {
                'task_type': 'psa_sync',
                'description': 'Synchronize data from PSA integrations',
                'interval_minutes': 60,
                'enabled': False,
            },
            {
                # v3.17.533: appears on Settings > Scheduler with an enable
                # toggle, so an operator can turn the accounting sync on without
                # touching systemd. The shipped timer unit is the alternative,
                # not a prerequisite — both run the same command.
                'task_type': 'accounting_sync',
                'description': 'Two-way sync with QuickBooks Online / Xero '
                               '(customers, payments, invoice state)',
                'interval_minutes': 60,
                'enabled': False,
            },
            {
                'task_type': 'password_breach_scan',
                'description': 'Check all passwords against HaveIBeenPwned breach database',
                'interval_minutes': 1440,  # Once per day (24 hours)
                'enabled': True,
            },
            {
                'task_type': 'vault_password_expiry',
                'description': 'Send email notifications for vault passwords nearing or past their expiration date',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'ssl_expiry_check',
                'description': 'Check for expiring SSL certificates and send notifications',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'domain_expiry_check',
                'description': 'Check for expiring domains and send notifications',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'cleanup_stuck_scans',
                'description': 'Find and mark stuck security scans as timed out (scans running > 2 hours)',
                'interval_minutes': 60,  # Every hour
                'enabled': True,
            },
            {
                'task_type': 'scheduling_alerts',
                'description': 'Send email/SMS alerts for upcoming and overdue scheduled tasks',
                'interval_minutes': 60,  # Every hour
                'enabled': True,
            },
            {
                'task_type': 'security_scan',
                'description': 'Run automated security scan (OS packages + Snyk) and alert superusers if vulnerabilities are found',
                'interval_minutes': 1440,  # Once per day
                'enabled': False,  # Opt-in
            },
            {
                'task_type': 'python_dep_scan',
                'description': 'Scan installed Python packages with pip-audit for known CVEs',
                'interval_minutes': 1440,  # Once per day
                'enabled': True,
            },
            {
                'task_type': 'system_warnings_digest',
                'description': 'Email superusers a digest of unresolved system warnings (OS, Python deps, expiring certs, etc.) at most once per cycle per warning',
                'interval_minutes': 1440,  # Once per day
                'enabled': False,  # Opt-in (requires SMTP)
            },
        ]

        for task_data in defaults:
            task, created = cls.objects.get_or_create(
                task_type=task_data['task_type'],
                defaults=task_data
            )
            if created:
                task.calculate_next_run()


class SnykScan(models.Model):
    """Track Snyk security scan results."""

    STATUS_CHOICES = [
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('timeout', 'Timed Out'),
    ]

    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('low', 'Low'),
        ('medium', 'Medium'),
    ]

    SCAN_TYPE_CHOICES = [
        ('open_source', 'Open Source (Dependencies)'),
        ('code', 'Code (SAST)'),
        ('container', 'Container (Docker)'),
        ('iac', 'Infrastructure as Code'),
    ]

    # Scan metadata
    scan_id = models.CharField(max_length=100, unique=True, help_text="Unique scan identifier")
    scan_type = models.CharField(max_length=20, choices=SCAN_TYPE_CHOICES, default='open_source', help_text='Type of Snyk product used for this scan')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    cancel_requested = models.BooleanField(default=False, help_text="User requested cancellation")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True, help_text="Scan duration in seconds")
    
    # Scan results
    total_vulnerabilities = models.IntegerField(default=0)
    critical_count = models.IntegerField(default=0)
    high_count = models.IntegerField(default=0)
    medium_count = models.IntegerField(default=0)
    low_count = models.IntegerField(default=0)
    
    # Raw scan output
    scan_output = models.TextField(blank=True, help_text="Full Snyk scan output")
    error_message = models.TextField(blank=True, help_text="Error message if scan failed")
    
    # Scan configuration
    severity_threshold = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='high')
    project_path = models.CharField(max_length=500, default='')  # Will use settings.BASE_DIR if empty
    
    # User who triggered the scan
    triggered_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='snyk_scans'
    )
    
    # JSON field for detailed vulnerability data
    vulnerabilities = models.JSONField(default=dict, blank=True, help_text="Detailed vulnerability information")

    # Vulnerability tracking
    new_vulnerabilities_count = models.IntegerField(default=0, help_text="New vulnerabilities not in previous scan")
    resolved_vulnerabilities_count = models.IntegerField(default=0, help_text="Vulnerabilities resolved since last scan")
    recurring_vulnerabilities_count = models.IntegerField(default=0, help_text="Vulnerabilities present in previous scan")

    class Meta:
        db_table = 'snyk_scans'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['status']),
            models.Index(fields=['critical_count', 'high_count']),
        ]
    
    def __str__(self):
        return f"Snyk Scan {self.scan_id} - {self.status} ({self.total_vulnerabilities} issues)"
    
    def get_severity_counts(self):
        """Return dict of severity counts."""
        return {
            'critical': self.critical_count,
            'high': self.high_count,
            'medium': self.medium_count,
            'low': self.low_count,
        }
    
    def has_critical_issues(self):
        """Check if scan found critical issues."""
        return self.critical_count > 0 or self.high_count > 0
    
    def get_status_badge_class(self):
        """Return Bootstrap badge class for status."""
        badge_map = {
            'pending': 'bg-secondary',
            'running': 'bg-info',
            'completed': 'bg-success' if not self.has_critical_issues() else 'bg-danger',
            'failed': 'bg-danger',
            'cancelled': 'bg-warning',
            'timeout': 'bg-warning',
        }
        return badge_map.get(self.status, 'bg-secondary')

    def compare_with_previous_scan(self):
        """
        Compare this scan's vulnerabilities with the previous completed scan.

        Returns:
            dict: {
                'new': list of new vulnerability IDs,
                'resolved': list of resolved vulnerability IDs,
                'recurring': list of recurring vulnerability IDs
            }
        """
        # Get the previous completed scan
        previous_scan = SnykScan.objects.filter(
            status='completed',
            completed_at__lt=self.started_at
        ).order_by('-completed_at').first()

        if not previous_scan:
            # No previous scan to compare with
            current_vulns = self.vulnerabilities.get('vulnerabilities', [])
            current_ids = {v.get('id') for v in current_vulns if v.get('id')}
            return {
                'new': list(current_ids),
                'resolved': [],
                'recurring': []
            }

        # Extract vulnerability IDs from both scans
        current_vulns = self.vulnerabilities.get('vulnerabilities', [])
        previous_vulns = previous_scan.vulnerabilities.get('vulnerabilities', [])

        current_ids = {v.get('id') for v in current_vulns if v.get('id')}
        previous_ids = {v.get('id') for v in previous_vulns if v.get('id')}

        # Calculate differences
        new_ids = current_ids - previous_ids
        resolved_ids = previous_ids - current_ids
        recurring_ids = current_ids & previous_ids

        return {
            'new': list(new_ids),
            'resolved': list(resolved_ids),
            'recurring': list(recurring_ids)
        }

    def update_vulnerability_tracking(self):
        """Update the new/resolved/recurring vulnerability counts based on comparison with previous scan."""
        comparison = self.compare_with_previous_scan()

        self.new_vulnerabilities_count = len(comparison['new'])
        self.resolved_vulnerabilities_count = len(comparison['resolved'])
        self.recurring_vulnerabilities_count = len(comparison['recurring'])

        self.save(update_fields=[
            'new_vulnerabilities_count',
            'resolved_vulnerabilities_count',
            'recurring_vulnerabilities_count'
        ])

    def is_stuck(self, timeout_hours=2):
        """
        Check if scan is stuck (running/pending for too long).

        Args:
            timeout_hours: Hours after which a scan is considered stuck (default: 2)

        Returns:
            bool: True if scan is stuck
        """
        from django.utils import timezone
        from datetime import timedelta

        # Only check scans in pending or running state
        if self.status not in ['pending', 'running']:
            return False

        # Check if started_at is more than timeout_hours ago
        now = timezone.now()
        timeout_threshold = now - timedelta(hours=timeout_hours)

        return self.started_at < timeout_threshold

    def mark_as_timeout(self):
        """Mark this scan as timed out."""
        from django.utils import timezone

        self.status = 'timeout'
        self.completed_at = timezone.now()
        self.error_message = 'Scan timed out - took longer than expected to complete'

        # Calculate duration if not already set
        if not self.duration_seconds and self.started_at:
            duration = timezone.now() - self.started_at
            self.duration_seconds = int(duration.total_seconds())

        self.save(update_fields=['status', 'completed_at', 'error_message', 'duration_seconds'])

    @classmethod
    def cleanup_stuck_scans(cls, timeout_hours=2):
        """
        Find and mark all stuck scans as timed out.

        Args:
            timeout_hours: Hours after which a scan is considered stuck (default: 2)

        Returns:
            int: Number of scans marked as timed out
        """
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        timeout_threshold = now - timedelta(hours=timeout_hours)

        # Find all stuck scans
        stuck_scans = cls.objects.filter(
            status__in=['pending', 'running'],
            started_at__lt=timeout_threshold
        )

        count = 0
        for scan in stuck_scans:
            scan.mark_as_timeout()
            count += 1

        return count


class FirewallSettings(models.Model):
    """
    Global firewall settings (singleton).
    Controls IP-based and GeoIP-based access restrictions.
    """
    # IP Firewall
    ip_firewall_enabled = models.BooleanField(
        default=False,
        help_text='Enable IP-based firewall'
    )
    ip_firewall_mode = models.CharField(
        max_length=20,
        default='blocklist',
        choices=[
            ('allowlist', 'Allow List (block all except listed IPs)'),
            ('blocklist', 'Block List (allow all except listed IPs)'),
        ],
        help_text='Firewall operation mode'
    )

    # GeoIP Firewall
    geoip_firewall_enabled = models.BooleanField(
        default=False,
        help_text='Enable GeoIP country-based firewall'
    )
    geoip_firewall_mode = models.CharField(
        max_length=20,
        default='blocklist',
        choices=[
            ('allowlist', 'Allow List (block all except listed countries)'),
            ('blocklist', 'Block List (allow all except listed countries)'),
        ],
        help_text='GeoIP operation mode'
    )

    # Bypass settings
    bypass_for_staff = models.BooleanField(
        default=True,
        help_text='Allow staff users to bypass firewall rules'
    )
    bypass_for_api = models.BooleanField(
        default=False,
        help_text='Allow API requests to bypass firewall rules'
    )

    # Logging
    log_blocked_requests = models.BooleanField(
        default=True,
        help_text='Log all blocked requests to audit log'
    )

    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='firewall_settings_updates'
    )

    class Meta:
        db_table = 'firewall_settings'
        verbose_name = 'Firewall Settings'
        verbose_name_plural = 'Firewall Settings'

    def __str__(self):
        return f"Firewall Settings (Updated: {self.updated_at})"

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        """Enforce singleton pattern."""
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of settings."""
        pass


class FirewallIPRule(models.Model):
    """
    IP address or IP range (CIDR) allow/block rule.
    """
    ip_address = models.CharField(
        max_length=50,
        help_text='IP address or CIDR range (e.g., 192.168.1.100 or 192.168.0.0/16)'
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional description (e.g., "Office Network", "VPN Gateway")'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Enable/disable this rule'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_ip_rules'
    )

    class Meta:
        db_table = 'firewall_ip_rules'
        ordering = ['ip_address']
        indexes = [
            models.Index(fields=['is_active', 'ip_address']),
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        desc = f" - {self.description}" if self.description else ""
        return f"{self.ip_address}{desc} ({status})"

    def matches_ip(self, ip_address):
        """
        Check if the given IP address matches this rule.
        Supports both single IPs and CIDR ranges.
        """
        import ipaddress
        try:
            # Parse the rule (could be single IP or network)
            if '/' in self.ip_address:
                # CIDR notation
                network = ipaddress.ip_network(self.ip_address, strict=False)
                ip_obj = ipaddress.ip_address(ip_address)
                return ip_obj in network
            else:
                # Single IP address
                return self.ip_address == ip_address
        except (ValueError, ipaddress.AddressValueError):
            return False


class FirewallCountryRule(models.Model):
    """
    Country-based allow/block rule using GeoIP.
    """
    country_code = models.CharField(
        max_length=2,
        help_text='2-letter ISO country code (e.g., US, GB, CN)'
    )
    country_name = models.CharField(
        max_length=100,
        help_text='Country name for display'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Enable/disable this rule'
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_country_rules'
    )

    class Meta:
        db_table = 'firewall_country_rules'
        ordering = ['country_name']
        unique_together = [['country_code']]
        indexes = [
            models.Index(fields=['is_active', 'country_code']),
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.country_name} ({self.country_code}) - {status}"


class FirewallLog(models.Model):
    """
    Log of blocked firewall requests for audit trail.
    """
    BLOCK_REASON_CHOICES = [
        ('country_blocklist', 'Country in blocklist'),
        ('country_not_in_allowlist', 'Country not in allowlist'),
        ('geoip_lookup_failed', 'GeoIP lookup failed'),
        ('ip_blocklist', 'IP in blocklist'),
        ('ip_not_in_allowlist', 'IP not in allowlist'),
    ]

    ip_address = models.GenericIPAddressField()
    country_code = models.CharField(max_length=2, blank=True)
    country_name = models.CharField(max_length=100, blank=True)
    block_reason = models.CharField(max_length=50, choices=BLOCK_REASON_CHOICES)
    request_path = models.CharField(max_length=500)
    request_method = models.CharField(max_length=10)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Optional user if authenticated
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='firewall_blocks'
    )

    class Meta:
        db_table = 'firewall_logs'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['ip_address', '-timestamp']),
            models.Index(fields=['country_code', '-timestamp']),
        ]

    def __str__(self):
        return f"Blocked {self.ip_address} ({self.get_block_reason_display()}) at {self.timestamp}"


class SecureNoteAccessLog(BaseModel):
    """
    Access log for secure notes (Issue #47 Phase 3).
    Tracks who accessed link-only notes, when, and from where.
    """
    secure_note = models.ForeignKey(
        SecureNote,
        on_delete=models.CASCADE,
        related_name='access_logs'
    )
    
    # Access details
    accessed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Geographic info (optional, can be populated via IP lookup)
    country = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # User info (if authenticated)
    user = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='secure_note_accesses'
    )
    
    class Meta:
        db_table = 'secure_note_access_logs'
        ordering = ['-accessed_at']
        indexes = [
            models.Index(fields=['secure_note', '-accessed_at']),
            models.Index(fields=['-accessed_at']),
        ]
    
    def __str__(self):
        return f"Access to {self.secure_note.title} at {self.accessed_at}"


class Webhook(models.Model):
    """
    Webhook configuration for sending HTTP notifications on events.
    """
    # Event types - Assets
    EVENT_ASSET_CREATED = 'asset.created'
    EVENT_ASSET_UPDATED = 'asset.updated'
    EVENT_ASSET_DELETED = 'asset.deleted'

    # Documents
    EVENT_DOCUMENT_CREATED = 'document.created'
    EVENT_DOCUMENT_UPDATED = 'document.updated'
    EVENT_DOCUMENT_DELETED = 'document.deleted'

    # Passwords/Vault
    EVENT_PASSWORD_CREATED = 'password.created'
    EVENT_PASSWORD_UPDATED = 'password.updated'
    EVENT_PASSWORD_DELETED = 'password.deleted'
    EVENT_PASSWORD_ACCESSED = 'password.accessed'
    EVENT_PASSWORD_SHARED = 'password.shared'

    # Users
    EVENT_USER_CREATED = 'user.created'
    EVENT_USER_UPDATED = 'user.updated'
    EVENT_USER_DELETED = 'user.deleted'
    EVENT_USER_LOGIN = 'user.login'
    EVENT_USER_LOGOUT = 'user.logout'
    EVENT_USER_LOGIN_FAILED = 'user.login_failed'
    EVENT_USER_PASSWORD_CHANGED = 'user.password_changed'

    # Organizations
    EVENT_ORGANIZATION_CREATED = 'organization.created'
    EVENT_ORGANIZATION_UPDATED = 'organization.updated'
    EVENT_ORGANIZATION_DELETED = 'organization.deleted'

    # Locations
    EVENT_LOCATION_CREATED = 'location.created'
    EVENT_LOCATION_UPDATED = 'location.updated'
    EVENT_LOCATION_DELETED = 'location.deleted'

    # Monitoring
    EVENT_MONITOR_UP = 'monitor.up'
    EVENT_MONITOR_DOWN = 'monitor.down'
    EVENT_MONITOR_SSL_EXPIRING = 'monitor.ssl_expiring'
    EVENT_MONITOR_CHECK_FAILED = 'monitor.check_failed'

    # Workflows
    EVENT_WORKFLOW_STARTED = 'workflow.started'
    EVENT_WORKFLOW_COMPLETED = 'workflow.completed'
    EVENT_WORKFLOW_FAILED = 'workflow.failed'

    # Integrations
    EVENT_INTEGRATION_SYNCED = 'integration.synced'
    EVENT_INTEGRATION_FAILED = 'integration.failed'

    # System
    EVENT_SYSTEM_UPDATE_AVAILABLE = 'system.update_available'
    EVENT_SYSTEM_UPDATE_APPLIED = 'system.update_applied'
    EVENT_BACKUP_COMPLETED = 'backup.completed'
    EVENT_BACKUP_FAILED = 'backup.failed'

    EVENT_CHOICES = [
        # Assets
        (EVENT_ASSET_CREATED, 'Asset Created'),
        (EVENT_ASSET_UPDATED, 'Asset Updated'),
        (EVENT_ASSET_DELETED, 'Asset Deleted'),

        # Documents
        (EVENT_DOCUMENT_CREATED, 'Document Created'),
        (EVENT_DOCUMENT_UPDATED, 'Document Updated'),
        (EVENT_DOCUMENT_DELETED, 'Document Deleted'),

        # Passwords/Vault
        (EVENT_PASSWORD_CREATED, 'Password Created'),
        (EVENT_PASSWORD_UPDATED, 'Password Updated'),
        (EVENT_PASSWORD_DELETED, 'Password Deleted'),
        (EVENT_PASSWORD_ACCESSED, 'Password Accessed'),
        (EVENT_PASSWORD_SHARED, 'Password Shared'),

        # Users
        (EVENT_USER_CREATED, 'User Created'),
        (EVENT_USER_UPDATED, 'User Updated'),
        (EVENT_USER_DELETED, 'User Deleted'),
        (EVENT_USER_LOGIN, 'User Login'),
        (EVENT_USER_LOGOUT, 'User Logout'),
        (EVENT_USER_LOGIN_FAILED, 'User Login Failed'),
        (EVENT_USER_PASSWORD_CHANGED, 'User Password Changed'),

        # Organizations
        (EVENT_ORGANIZATION_CREATED, 'Organization Created'),
        (EVENT_ORGANIZATION_UPDATED, 'Organization Updated'),
        (EVENT_ORGANIZATION_DELETED, 'Organization Deleted'),

        # Locations
        (EVENT_LOCATION_CREATED, 'Location Created'),
        (EVENT_LOCATION_UPDATED, 'Location Updated'),
        (EVENT_LOCATION_DELETED, 'Location Deleted'),

        # Monitoring
        (EVENT_MONITOR_UP, 'Monitor Up'),
        (EVENT_MONITOR_DOWN, 'Monitor Down'),
        (EVENT_MONITOR_SSL_EXPIRING, 'Monitor SSL Certificate Expiring'),
        (EVENT_MONITOR_CHECK_FAILED, 'Monitor Check Failed'),

        # Workflows
        (EVENT_WORKFLOW_STARTED, 'Workflow Started'),
        (EVENT_WORKFLOW_COMPLETED, 'Workflow Completed'),
        (EVENT_WORKFLOW_FAILED, 'Workflow Failed'),

        # Integrations
        (EVENT_INTEGRATION_SYNCED, 'Integration Synced'),
        (EVENT_INTEGRATION_FAILED, 'Integration Failed'),

        # System
        (EVENT_SYSTEM_UPDATE_AVAILABLE, 'System Update Available'),
        (EVENT_SYSTEM_UPDATE_APPLIED, 'System Update Applied'),
        (EVENT_BACKUP_COMPLETED, 'Backup Completed'),
        (EVENT_BACKUP_FAILED, 'Backup Failed'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='webhooks',
        help_text='Organization this webhook belongs to'
    )
    name = models.CharField(max_length=255, help_text='Descriptive name for this webhook')
    url = models.URLField(max_length=500, help_text='URL to send webhook POST requests to')
    events = models.JSONField(
        default=list,
        help_text='List of event types to trigger this webhook'
    )
    secret = models.CharField(
        max_length=255,
        blank=True,
        help_text='Secret key for signing webhook payloads (optional)'
    )
    is_active = models.BooleanField(default=True, help_text='Enable/disable this webhook')
    custom_headers = models.JSONField(
        default=dict,
        blank=True,
        help_text='Custom HTTP headers to include in requests (e.g., Authorization)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_webhooks'
    )

    class Meta:
        db_table = 'webhooks'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.url})"


class WebhookDelivery(models.Model):
    """
    Log of webhook delivery attempts.
    """
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    webhook = models.ForeignKey(
        Webhook,
        on_delete=models.CASCADE,
        related_name='deliveries'
    )
    event_type = models.CharField(max_length=50)
    payload = models.JSONField(help_text='The JSON payload sent to the webhook')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    response_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    delivered_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.IntegerField(null=True, blank=True, help_text='Request duration in milliseconds')

    class Meta:
        db_table = 'webhook_deliveries'
        ordering = ['-delivered_at']
        indexes = [
            models.Index(fields=['webhook', '-delivered_at']),
            models.Index(fields=['status']),
        ]
        verbose_name_plural = 'Webhook deliveries'

    def __str__(self):
        return f"{self.webhook.name} - {self.event_type} ({self.status})"


# ============================================================================
# System Package Scanning
# ============================================================================

class SystemPackageScan(models.Model):
    """
    Store results from system package vulnerability scans.
    Tracks OS package updates and security vulnerabilities.
    """
    scan_date = models.DateTimeField(auto_now_add=True)
    package_manager = models.CharField(
        max_length=50,
        help_text="Package manager used (apt, yum, dnf, pacman)"
    )
    total_packages = models.IntegerField(default=0)
    upgradeable_packages = models.IntegerField(default=0)
    security_updates = models.IntegerField(default=0)
    scan_data = models.JSONField(
        default=dict,
        help_text="Full scan results including package details"
    )

    class Meta:
        db_table = 'system_package_scans'
        ordering = ['-scan_date']
        indexes = [
            models.Index(fields=['-scan_date']),
        ]

    def __str__(self):
        return f"Scan {self.scan_date.strftime('%Y-%m-%d %H:%M')} - {self.security_updates} security updates"

    @property
    def has_security_updates(self):
        """Check if security updates are available"""
        return self.security_updates > 0

    @property
    def security_status(self):
        """Get security status as color/label"""
        if self.security_updates == 0:
            return 'success', 'Secure'
        elif self.security_updates < 5:
            return 'warning', 'Low Risk'
        elif self.security_updates < 20:
            return 'danger', 'Medium Risk'
        else:
            return 'danger', 'High Risk'


class PythonPackageScan(models.Model):
    """
    Store results from Python dependency vulnerability scans (pip-audit).
    Tracks installed Python packages and known CVEs.
    """
    scan_date = models.DateTimeField(auto_now_add=True)
    total_packages = models.IntegerField(default=0)
    vulnerable_packages = models.IntegerField(default=0, help_text='Distinct packages with at least one vuln')
    total_vulnerabilities = models.IntegerField(default=0, help_text='Total vuln findings (a package can have multiple)')
    critical_count = models.IntegerField(default=0)
    high_count = models.IntegerField(default=0)
    medium_count = models.IntegerField(default=0)
    low_count = models.IntegerField(default=0)
    unknown_count = models.IntegerField(default=0)
    scan_succeeded = models.BooleanField(default=True)
    scan_error = models.TextField(blank=True)
    scan_data = models.JSONField(
        default=dict,
        help_text='Full pip-audit results: list of {name, version, vulns: [{id, fix_versions, severity, summary}]}'
    )

    class Meta:
        db_table = 'python_package_scans'
        ordering = ['-scan_date']
        indexes = [
            models.Index(fields=['-scan_date']),
        ]

    def __str__(self):
        return f"Python scan {self.scan_date.strftime('%Y-%m-%d %H:%M')} — {self.total_vulnerabilities} vulns"

    @property
    def has_vulnerabilities(self):
        return self.total_vulnerabilities > 0

    @property
    def security_status(self):
        """Return (severity_class, label) tuple — same shape as SystemPackageScan."""
        if not self.scan_succeeded:
            return 'secondary', 'Scan failed'
        if self.critical_count > 0:
            return 'danger', 'Critical'
        if self.high_count > 0:
            return 'danger', 'High Risk'
        if self.medium_count > 0:
            return 'warning', 'Medium Risk'
        if self.low_count > 0 or self.unknown_count > 0:
            return 'warning', 'Low Risk'
        return 'success', 'Secure'

    @property
    def worst_severity(self):
        """Return the most severe severity present, or None."""
        if self.critical_count:
            return 'critical'
        if self.high_count:
            return 'high'
        if self.medium_count:
            return 'medium'
        if self.low_count:
            return 'low'
        if self.unknown_count:
            return 'unknown'
        return None


class SystemWarningNotification(models.Model):
    """
    Per-warning notification record. Used by the system_warnings_digest task
    to avoid emailing the same warning twice. Cleared/superseded when the
    underlying warning ID rotates (e.g. a new scan ID).
    """
    warning_id = models.CharField(
        max_length=200,
        unique=True,
        help_text='Stable warning id from system_warnings.collect_system_warnings()',
    )
    severity = models.CharField(max_length=20)
    title = models.TextField()
    notified_at = models.DateTimeField(auto_now_add=True)
    recipients_count = models.IntegerField(default=0)

    class Meta:
        db_table = 'system_warning_notifications'
        ordering = ['-notified_at']
        indexes = [
            models.Index(fields=['-notified_at']),
        ]

    def __str__(self):
        return f"{self.severity}: {self.warning_id}"
