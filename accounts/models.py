"""
Accounts models - Memberships and Roles
"""
import contextlib
import threading

from django.db import models

from core.backgrounds import DEFAULT_PRESET, PRESET_CHOICES
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Organization, BaseModel


# Opt-in flag for the create_default_membership signal. By default the signal
# is OFF — silently auto-attaching every newly-created user to the first
# active org polluted org Members lists with users that were never invited.
# Enable it explicitly for code paths that legitimately want it (e.g. the
# self-signup flow on a single-tenant install) by wrapping the User.create
# call in `with _enable_auto_membership(): ...`.
_auto_membership_state = threading.local()


@contextlib.contextmanager
def _enable_auto_membership():
    prev = getattr(_auto_membership_state, 'enabled', False)
    _auto_membership_state.enabled = True
    try:
        yield
    finally:
        _auto_membership_state.enabled = prev


class Role(models.TextChoices):
    """
    Role definitions for RBAC.
    """
    ADMIN = 'admin', 'Admin'
    EDITOR = 'editor', 'Editor'
    OWNER = 'owner', 'Owner'
    READONLY = 'readonly', 'Read-Only'


class Membership(BaseModel):
    """
    User membership in an organization with a role.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.READONLY)
    role_template = models.ForeignKey(
        'RoleTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='memberships',
        help_text='Granular role template (overrides simple role if set)'
    )
    is_active = models.BooleanField(default=True)
    is_org_admin = models.BooleanField(
        default=False,
        help_text='Org Admin: lets a portal user manage which other members of '
                  'the same organization can access vault items shared in '
                  '`org_admin_managed` mode. Independent of the staff Admin '
                  'role; only meaningful for client portal users.'
    )
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_memberships')
    invited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'memberships'
        unique_together = [['user', 'organization']]
        ordering = ['-created_at']

    def __str__(self):
        if self.role_template:
            return f"{self.user.username} - {self.organization.name} ({self.role_template.name})"
        return f"{self.user.username} - {self.organization.name} ({self.get_role_display()})"

    def get_permissions(self):
        """Get permissions object (RoleTemplate or create on-the-fly from simple role)."""
        if self.role_template:
            return self.role_template

        # Fall back to simple role - create temporary permission object
        from types import SimpleNamespace
        if self.role == Role.OWNER:
            return SimpleNamespace(
                vault_view=True, vault_create=True, vault_edit=True, vault_delete=True,
                vault_export=True, vault_view_password=True,
                vault_manage_access_rules=True,
                vault_extension_use=True, vault_extension_offline_cache=True,
                assets_view=True, assets_create=True, assets_edit=True, assets_delete=True,
                docs_view=True, docs_create=True, docs_edit=True, docs_delete=True, docs_publish=True,
                files_view=True, files_upload=True, files_delete=True,
                monitoring_view=True, monitoring_create=True, monitoring_edit=True,
                monitoring_delete=True, monitoring_trigger=True,
                integrations_view=True, integrations_configure=True, integrations_sync=True,
                audit_view=True, audit_export=True,
                org_view_members=True, org_invite_members=True, org_manage_members=True,
                org_manage_settings=True,
                api_access=True, api_keys_manage=True,
                # KB
                kb_view_articles=True, kb_edit_articles=True, kb_move_articles=True,
                kb_manage_categories=True, kb_publish_articles=True,
                # Reports + financials (v3.17.145) — Owner: all True
                reports_view_dashboards=True, reports_view_financial=True,
                reports_view_sla=True, reports_view_capacity=True,
                reports_manage_dashboards=True, reports_manage_scheduled=True,
                resourcing_view_team=True, resourcing_manage_cost_rates=True,
                resourcing_approve_leave=True, resourcing_manage_holidays=True,
                billing_view_invoices=True, billing_send_invoices=True,
                billing_record_payments=True, billing_view_aging=True,
                # Procurement (Phase 4) — Owner: all True
                procurement_view=True, procurement_create_pr=True,
                procurement_approve_pr=True, procurement_create_po=True,
                procurement_send_po=True,
                # CRM (Phase 5) — Owner: all True
                crm_view=True, crm_create_lead=True,
                crm_manage_pipeline=True, crm_manage_campaigns=True,
                crm_view_forecast=True,
                # Change management (Phase 6.1) — Owner: all True
                change_view=True, change_create=True,
                change_approve_cab=True, change_implement=True,
                # Problem management (Phase 6.2) — Owner: all True
                problem_view=True, problem_create=True,
                problem_assign=True, problem_resolve=True,
                # Release + catalog governance (Phase 6.3) — Owner: all True
                release_view=True, release_manage=True, release_freeze=True,
                catalog_propose_change=True, catalog_approve_change=True,
                # PSA Tickets (v3.17.477) — Owner: all True
                tickets_view=True, tickets_create=True, tickets_edit=True,
                tickets_assign=True, tickets_view_all=True,
                tickets_close=True, tickets_delete=True,
            )
        elif self.role == Role.ADMIN:
            return SimpleNamespace(
                vault_view=True, vault_create=True, vault_edit=True, vault_delete=True,
                vault_export=True, vault_view_password=True,
                vault_manage_access_rules=True,
                vault_extension_use=True, vault_extension_offline_cache=True,
                assets_view=True, assets_create=True, assets_edit=True, assets_delete=True,
                docs_view=True, docs_create=True, docs_edit=True, docs_delete=True, docs_publish=True,
                files_view=True, files_upload=True, files_delete=True,
                monitoring_view=True, monitoring_create=True, monitoring_edit=True,
                monitoring_delete=True, monitoring_trigger=True,
                integrations_view=True, integrations_configure=True, integrations_sync=True,
                audit_view=True, audit_export=True,
                org_view_members=True, org_invite_members=True, org_manage_members=False,
                org_manage_settings=False,
                api_access=True, api_keys_manage=False,
                # KB
                kb_view_articles=True, kb_edit_articles=True, kb_move_articles=True,
                kb_manage_categories=True, kb_publish_articles=True,
                # Reports + financials (v3.17.145) — Admin: all True except
                # reports_manage_scheduled (admins typically delegate that).
                reports_view_dashboards=True, reports_view_financial=True,
                reports_view_sla=True, reports_view_capacity=True,
                reports_manage_dashboards=True, reports_manage_scheduled=False,
                resourcing_view_team=True, resourcing_manage_cost_rates=True,
                resourcing_approve_leave=True, resourcing_manage_holidays=True,
                billing_view_invoices=True, billing_send_invoices=True,
                billing_record_payments=True, billing_view_aging=True,
                # Procurement (Phase 4) — Admin: all True
                procurement_view=True, procurement_create_pr=True,
                procurement_approve_pr=True, procurement_create_po=True,
                procurement_send_po=True,
                # CRM (Phase 5) — Admin: all True
                crm_view=True, crm_create_lead=True,
                crm_manage_pipeline=True, crm_manage_campaigns=True,
                crm_view_forecast=True,
                # Change management (Phase 6.1) — Admin: all True
                change_view=True, change_create=True,
                change_approve_cab=True, change_implement=True,
                # Problem management (Phase 6.2) — Admin: all True
                problem_view=True, problem_create=True,
                problem_assign=True, problem_resolve=True,
                # Release + catalog governance (Phase 6.3) — Admin: all True
                release_view=True, release_manage=True, release_freeze=True,
                catalog_propose_change=True, catalog_approve_change=True,
                # PSA Tickets (v3.17.477) — Admin: all True
                tickets_view=True, tickets_create=True, tickets_edit=True,
                tickets_assign=True, tickets_view_all=True,
                tickets_close=True, tickets_delete=True,
            )
        elif self.role == Role.EDITOR:
            return SimpleNamespace(
                vault_view=True, vault_create=True, vault_edit=True, vault_delete=False,
                vault_export=False, vault_view_password=True,
                vault_manage_access_rules=False,
                vault_extension_use=True, vault_extension_offline_cache=False,
                assets_view=True, assets_create=True, assets_edit=True, assets_delete=False,
                docs_view=True, docs_create=True, docs_edit=True, docs_delete=False, docs_publish=False,
                files_view=True, files_upload=True, files_delete=False,
                monitoring_view=True, monitoring_create=True, monitoring_edit=True,
                monitoring_delete=False, monitoring_trigger=True,
                integrations_view=False, integrations_configure=False, integrations_sync=False,
                audit_view=False, audit_export=False,
                org_view_members=True, org_invite_members=False, org_manage_members=False,
                org_manage_settings=False,
                api_access=True, api_keys_manage=False,
                # KB — Editor can view/edit/move/publish, but NOT manage_categories
                kb_view_articles=True, kb_edit_articles=True, kb_move_articles=True,
                kb_manage_categories=False, kb_publish_articles=True,
                # Reports + financials (v3.17.145) — Editor (techs):
                # dashboards-only, no financial/sla/capacity/billing.
                reports_view_dashboards=True, reports_view_financial=False,
                reports_view_sla=False, reports_view_capacity=False,
                reports_manage_dashboards=False, reports_manage_scheduled=False,
                resourcing_view_team=False, resourcing_manage_cost_rates=False,
                resourcing_approve_leave=False, resourcing_manage_holidays=False,
                billing_view_invoices=False, billing_send_invoices=False,
                billing_record_payments=False, billing_view_aging=False,
                # Procurement (Phase 4) — Editor (techs):
                # can view + file PRs; cannot approve PRs or create/send POs.
                procurement_view=True, procurement_create_pr=True,
                procurement_approve_pr=False, procurement_create_po=False,
                procurement_send_po=False,
                # CRM (Phase 5) — Editor: view + create_lead + manage_pipeline,
                # campaigns + forecast off.
                crm_view=True, crm_create_lead=True,
                crm_manage_pipeline=True, crm_manage_campaigns=False,
                crm_view_forecast=False,
                # Change management (Phase 6.1) — Editor: view + create only.
                change_view=True, change_create=True,
                change_approve_cab=False, change_implement=False,
                # Problem management (Phase 6.2) — Editor: view + create only.
                problem_view=True, problem_create=True,
                problem_assign=False, problem_resolve=False,
                # Release + catalog governance (Phase 6.3) — Editor: view + propose.
                release_view=True, release_manage=False, release_freeze=False,
                catalog_propose_change=True, catalog_approve_change=False,
                # PSA Tickets (v3.17.477) — Editor (techs): file + work,
                # no reassign or hard-delete.
                tickets_view=True, tickets_create=True, tickets_edit=True,
                tickets_assign=False, tickets_view_all=False,
                tickets_close=True, tickets_delete=False,
            )
        else:  # READONLY
            return SimpleNamespace(
                vault_view=True, vault_create=False, vault_edit=False, vault_delete=False,
                vault_export=False, vault_view_password=False,
                vault_manage_access_rules=False,
                vault_extension_use=False, vault_extension_offline_cache=False,
                assets_view=True, assets_create=False, assets_edit=False, assets_delete=False,
                docs_view=True, docs_create=False, docs_edit=False, docs_delete=False, docs_publish=False,
                files_view=True, files_upload=False, files_delete=False,
                monitoring_view=True, monitoring_create=False, monitoring_edit=False,
                monitoring_delete=False, monitoring_trigger=False,
                integrations_view=False, integrations_configure=False, integrations_sync=False,
                audit_view=False, audit_export=False,
                org_view_members=True, org_invite_members=False, org_manage_members=False,
                org_manage_settings=False,
                api_access=False, api_keys_manage=False,
                # KB — read-only sees articles but cannot mutate
                kb_view_articles=True, kb_edit_articles=False, kb_move_articles=False,
                kb_manage_categories=False, kb_publish_articles=False,
                # Reports + financials (v3.17.145) — Read-Only:
                # dashboards only, nothing else.
                reports_view_dashboards=True, reports_view_financial=False,
                reports_view_sla=False, reports_view_capacity=False,
                reports_manage_dashboards=False, reports_manage_scheduled=False,
                resourcing_view_team=False, resourcing_manage_cost_rates=False,
                resourcing_approve_leave=False, resourcing_manage_holidays=False,
                billing_view_invoices=False, billing_send_invoices=False,
                billing_record_payments=False, billing_view_aging=False,
                # Procurement (Phase 4) — Read-Only: only view.
                procurement_view=True, procurement_create_pr=False,
                procurement_approve_pr=False, procurement_create_po=False,
                procurement_send_po=False,
                # CRM (Phase 5) — Read-Only: only crm_view.
                crm_view=True, crm_create_lead=False,
                crm_manage_pipeline=False, crm_manage_campaigns=False,
                crm_view_forecast=False,
                # Change management (Phase 6.1) — Read-Only: view only.
                change_view=True, change_create=False,
                change_approve_cab=False, change_implement=False,
                # Problem management (Phase 6.2) — Read-Only: view only.
                problem_view=True, problem_create=False,
                problem_assign=False, problem_resolve=False,
                # Release + catalog governance (Phase 6.3) — Read-Only: view only.
                release_view=True, release_manage=False, release_freeze=False,
                catalog_propose_change=False, catalog_approve_change=False,
                # PSA Tickets (v3.17.477) — Read-Only: view only.
                tickets_view=True, tickets_create=False, tickets_edit=False,
                tickets_assign=False, tickets_view_all=False,
                tickets_close=False, tickets_delete=False,
            )

    def can_read(self):
        return True  # All roles can read

    def can_write(self):
        """Generic write permission check."""
        perms = self.get_permissions()
        return any([
            perms.vault_create, perms.assets_create, perms.docs_create,
            perms.files_upload, perms.monitoring_create
        ])

    def can_admin(self):
        """Check if user has admin privileges (can manage roles and organization settings)."""
        # OWNER and ADMIN roles always have admin privileges
        if self.role in [Role.OWNER, Role.ADMIN]:
            return True
        # Otherwise check granular permissions
        perms = self.get_permissions()
        return perms.org_manage_settings

    def can_manage_users(self):
        perms = self.get_permissions()
        return perms.org_manage_members

    def can_manage_integrations(self):
        perms = self.get_permissions()
        return perms.integrations_configure

    def has_permission(self, permission_name):
        """Check if user has a specific permission."""
        perms = self.get_permissions()
        return getattr(perms, permission_name, False)


class UserType(models.TextChoices):
    """
    User type definitions for MSP model.
    """
    ORG_USER = 'org_user', 'Organization User (Client)'
    STAFF = 'staff', 'Staff User (MSP Tech)'


class UserProfile(BaseModel):
    """
    Extended user profile with additional information.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # User Type (MSP Model)
    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.ORG_USER,
        help_text='Staff users have global access across all organizations. Org users only see their assigned organizations.'
    )

    # Global Role Template (for Staff Users only)
    global_role_template = models.ForeignKey(
        'RoleTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_users',
        help_text='For staff users: role template that applies globally across all organizations'
    )

    # Name fields
    phone = models.CharField(max_length=50, blank=True)
    title = models.CharField(max_length=100, blank=True, help_text='Job title')
    department = models.CharField(max_length=100, blank=True)
    
    # Avatar
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    
    # Preferences
    timezone = models.CharField(max_length=50, default='UTC')
    time_format = models.CharField(max_length=2, default='24', choices=[
        ('12', '12-hour (AM/PM)'),
        ('24', '24-hour'),
    ])
    LOCALE_CHOICES = [
        ('en-us', 'English (US)'),
        ('es',    'Spanish'),
        ('fr',    'French'),
        ('de',    'German'),
        ('pt-br', 'Portuguese (Brazil)'),
    ]
    locale = models.CharField(max_length=10, default='en-us', choices=LOCALE_CHOICES)
    theme = models.CharField(max_length=30, default='default', choices=[
        ('dark', 'Dark Mode'),
        ('default', 'Default Blue'),
        ('dracula', 'Dracula'),
        ('green', 'Forest Green'),
        ('gruvbox', 'Gruvbox'),
        ('monokai', 'Monokai'),
        ('nord', 'Nord (Arctic)'),
        ('ocean', 'Ocean Blue'),
        ('purple', 'Purple Haze'),
        ('solarized', 'Solarized Light'),
        ('sunset', 'Sunset Orange'),
    ])

    # Background Settings
    background_mode = models.CharField(max_length=20, default='none', choices=[
        ('custom', 'Custom Upload'),
        ('none', 'No Background Image'),
        ('preset', 'Preset Abstract Backgrounds'),
        ('random', 'Random from Internet'),
        ('solid_color', 'Solid Color'),
    ])
    background_image = models.ImageField(
        upload_to='backgrounds/',
        null=True,
        blank=True,
        help_text='Custom background image for your profile'
    )
    background_color = models.CharField(
        max_length=7,
        default='#1a1a2e',
        blank=True,
        help_text='Solid background color (hex code)'
    )
    preset_background = models.CharField(
        max_length=50,
        default=DEFAULT_PRESET,
        blank=True,
        # Was a hand-maintained copy of this list; the URLs lived separately in
        # the context processor and nothing kept the two in step.
        choices=PRESET_CHOICES,
        help_text='Select a preset abstract background'
    )

    # 2FA Settings
    two_factor_enabled = models.BooleanField(default=False)
    two_factor_method = models.CharField(max_length=20, choices=[
        ('totp', 'Authenticator App'),
        ('email', 'Email'),
        ('sms', 'SMS'),
    ], default='totp', blank=True)
    
    # Security
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    account_locked_until = models.DateTimeField(null=True, blank=True)
    
    # Notifications
    email_notifications = models.BooleanField(default=True)
    notification_frequency = models.CharField(max_length=20, choices=[
        ('daily', 'Daily Digest'),
        ('hourly', 'Hourly Digest'),
        ('realtime', 'Real-time'),
        ('weekly', 'Weekly Digest'),
    ], default='realtime')

    # Tech notification preferences (PSA dispatch)
    notify_assigned_email = models.BooleanField(
        default=True,
        help_text='Send me an email when a PSA ticket is assigned to me.',
    )
    notify_assigned_sms = models.BooleanField(
        default=False,
        help_text='Text my UserProfile.phone when a PSA ticket is assigned to me. '
                  'Requires SMS to be configured globally and a phone number on '
                  'this profile.',
    )
    notify_scheduled_email = models.BooleanField(
        default=True,
        help_text='Send me an email when an assigned ticket gets a due date '
                  '(or a new one).',
    )
    notify_scheduled_sms = models.BooleanField(
        default=False,
        help_text='Text me when an assigned ticket gets a due date.',
    )

    # Organization Preferences
    preferred_organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text='Default organization to load on login'
    )

    # UI Preferences
    tooltips_enabled = models.BooleanField(
        default=True,
        help_text='Show helpful tooltips throughout the interface'
    )

    # v3.17.230 — editable Quick Actions on the dashboard.
    # JSON list of action keys (from QUICK_ACTIONS_REGISTRY) in user-preferred
    # order. Empty list = use the registry defaults. Unknown keys are silently
    # ignored at render time so a removed registry entry doesn't break the page.
    quick_actions_config = models.JSONField(
        default=list, blank=True,
        help_text='Ordered list of quick-action keys the user wants on their '
                  'dashboard. Empty = use defaults.',
    )

    # v3.17.233 — Customer-portal notification preferences.
    portal_notify_ticket_reply = models.BooleanField(
        default=True,
        help_text='Send me an email when a staff member replies to one of my tickets.',
    )
    portal_notify_status_change = models.BooleanField(
        default=True,
        help_text='Send me an email when one of my tickets changes status.',
    )
    portal_notify_csat_invite = models.BooleanField(
        default=True,
        help_text='Email me a CSAT survey link when one of my tickets is resolved.',
    )
    portal_notify_sms_status_change = models.BooleanField(
        default=False,
        help_text='v3.17.238: text my profile phone when one of my tickets '
                  'changes status. Requires SMS to be enabled globally and a '
                  'phone number on file. Off by default since SMS often costs.',
    )

    # Authentication Source (for SSO tracking)
    auth_source = models.CharField(
        max_length=20,
        choices=[
            ('azure_ad', 'Azure AD / Microsoft Entra ID'),
            ('ldap', 'LDAP/Active Directory'),
            ('local', 'Local'),
        ],
        default='local',
        help_text='Authentication source for this user'
    )
    azure_ad_oid = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Azure AD Object ID (OID)'
    )

    class Meta:
        db_table = 'user_profiles'

    def __str__(self):
        return f"{self.user.username}'s profile"

    def is_staff_user(self):
        """Check if this is a staff user (MSP tech)."""
        return self.user_type == UserType.STAFF

    def is_org_user(self):
        """Check if this is an organization user (client)."""
        return self.user_type == UserType.ORG_USER

    def get_global_permissions(self):
        """Get global permissions for staff users."""
        if not self.is_staff_user():
            return None
        return self.global_role_template
    
    @property
    def full_name(self):
        """Get user's full name."""
        if self.user.first_name or self.user.last_name:
            return f"{self.user.first_name} {self.user.last_name}".strip()
        return self.user.username
    
    @property
    def is_locked(self):
        """Check if account is currently locked."""
        if not self.account_locked_until:
            return False
        from django.utils import timezone
        return timezone.now() < self.account_locked_until

    def is_working_now(self):
        """True if the user has an active WorkingHours window covering 'now'
        in their profile timezone. Returns True if no WorkingHours rows exist
        (no constraint = always working — backwards-compatible default).

        Used by capacity reporting (Phase 3) and GPS off-shift suppression
        (Phase 8.5)."""
        from django.utils import timezone
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(self.timezone or 'UTC')
        except Exception:
            tz = zoneinfo.ZoneInfo('UTC')
        now = timezone.now().astimezone(tz)
        weekday = now.weekday()
        rows = self.user.resourcing_working_hours.filter(weekday=weekday, is_active=True)
        if not rows.exists():
            # If the user has any WorkingHours at all (other days), assume they don't work today
            if self.user.resourcing_working_hours.exists():
                return False
            return True  # No WorkingHours configured: backwards-compatible "always"
        t = now.time()
        return any(r.start_time <= t <= r.end_time for r in rows)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Automatically create profile when user is created."""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save profile when user is saved."""
    if hasattr(instance, 'profile'):
        instance.profile.save()


@receiver(post_save, sender=User)
def create_default_membership(sender, instance, created, **kwargs):
    """
    Auto-attach a newly-created user to the default org.

    Disabled by default — the previous behaviour silently bound every
    non-superuser to the first active org, polluting org "Members" lists with
    users that were never explicitly invited. The org-admin Add Member flow
    creates the Membership row itself, so the signal is no longer needed
    there. To re-enable for a specific code path, set the thread-local flag:
        from accounts.models import _enable_auto_membership
        with _enable_auto_membership():
            User.objects.create(...)
    """
    if not created or instance.is_superuser:
        return
    if not getattr(_auto_membership_state, 'enabled', False):
        return

    from core.models import Organization
    default_org = Organization.objects.filter(is_active=True).first()
    if not default_org:
        return
    if Membership.objects.filter(user=instance, organization=default_org).exists():
        return
    Membership.objects.create(
        user=instance,
        organization=default_org,
        role=Role.READONLY,
        is_active=True,
    )


class RoleTemplate(BaseModel):
    """
    Role template with granular permissions.
    Can be system-defined or custom per organization.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='role_templates',
        null=True,
        blank=True,
        help_text='If null, this is a system-wide template'
    )
    is_system_template = models.BooleanField(
        default=False,
        help_text='System templates cannot be deleted or modified by users'
    )

    # Vault Permissions
    vault_view = models.BooleanField(default=True, help_text='View passwords and secrets')
    vault_create = models.BooleanField(default=False, help_text='Create passwords and secrets')
    vault_edit = models.BooleanField(default=False, help_text='Edit passwords and secrets')
    vault_delete = models.BooleanField(default=False, help_text='Delete passwords and secrets')
    vault_export = models.BooleanField(default=False, help_text='Export passwords')
    vault_view_password = models.BooleanField(default=True, help_text='View actual password values')
    vault_manage_access_rules = models.BooleanField(
        default=False,
        help_text='Create / edit / delete vault GeoIP / IP / time access rules.',
    )
    # Phase 28 (v3.17.328) — browser-extension permissions
    vault_extension_use = models.BooleanField(
        default=False,
        help_text='Use the browser extension (autofill / TOTP / reveal '
                  'via Authorization: Bearer token).',
    )
    vault_extension_offline_cache = models.BooleanField(
        default=False,
        help_text='Allow the browser extension to bulk-sync the visible '
                  'vault as encrypted blobs for offline access.',
    )

    # Assets Permissions
    assets_view = models.BooleanField(default=True, help_text='View assets')
    assets_create = models.BooleanField(default=False, help_text='Create assets')
    assets_edit = models.BooleanField(default=False, help_text='Edit assets')
    assets_delete = models.BooleanField(default=False, help_text='Delete assets')

    # Documents Permissions
    docs_view = models.BooleanField(default=True, help_text='View documents')
    docs_create = models.BooleanField(default=False, help_text='Create documents')
    docs_edit = models.BooleanField(default=False, help_text='Edit documents')
    docs_delete = models.BooleanField(default=False, help_text='Delete documents')
    docs_publish = models.BooleanField(default=False, help_text='Publish/unpublish documents')

    # Files Permissions
    files_view = models.BooleanField(default=True, help_text='View files')
    files_upload = models.BooleanField(default=False, help_text='Upload files')
    files_delete = models.BooleanField(default=False, help_text='Delete files')

    # Monitoring Permissions
    monitoring_view = models.BooleanField(default=True, help_text='View monitors')
    monitoring_create = models.BooleanField(default=False, help_text='Create monitors')
    monitoring_edit = models.BooleanField(default=False, help_text='Edit monitors')
    monitoring_delete = models.BooleanField(default=False, help_text='Delete monitors')
    monitoring_trigger = models.BooleanField(default=False, help_text='Manually trigger checks')

    # Integrations Permissions
    integrations_view = models.BooleanField(default=False, help_text='View integrations')
    integrations_configure = models.BooleanField(default=False, help_text='Configure integrations')
    integrations_sync = models.BooleanField(default=False, help_text='Trigger sync operations')

    # Audit Permissions
    audit_view = models.BooleanField(default=False, help_text='View audit logs')
    audit_export = models.BooleanField(default=False, help_text='Export audit logs')

    # Organization Permissions
    org_view_members = models.BooleanField(default=True, help_text='View organization members')
    org_invite_members = models.BooleanField(default=False, help_text='Invite new members')
    org_manage_members = models.BooleanField(default=False, help_text='Edit/remove members')
    org_manage_settings = models.BooleanField(default=False, help_text='Change organization settings')

    # API Permissions
    api_access = models.BooleanField(default=False, help_text='Access API endpoints')
    api_keys_manage = models.BooleanField(default=False, help_text='Create/manage API keys')

    # PSA AI Permissions (Workstream 10)
    # Risk-tiered for replies and actions, plus admin/billing carve-outs.
    # Permission resolver: psa_ai/permissions.py
    psa_ai_view = models.BooleanField(default=True,
        help_text='View AI suggestions and the AI inbox')
    psa_ai_send_low_risk = models.BooleanField(default=False,
        help_text='Send low-risk AI replies as public ticket comments')
    psa_ai_send_high_risk = models.BooleanField(default=False,
        help_text='Send medium- or high-risk AI replies (requires admin in most orgs)')
    psa_ai_approve_reply = models.BooleanField(default=False,
        help_text='Approve another user\'s pending AI reply')
    psa_ai_apply_low_risk = models.BooleanField(default=False,
        help_text='Apply low-risk AI actions (e.g. set priority, add internal note)')
    psa_ai_apply_high_risk = models.BooleanField(default=False,
        help_text='Apply medium- or high-risk AI actions (state changes, assignment)')
    psa_ai_approve_action = models.BooleanField(default=False,
        help_text='Approve another user\'s pending AI action')
    psa_ai_run_script = models.BooleanField(default=False,
        help_text='Run an AI-suggested RMM script against an asset')
    psa_ai_create_workflow = models.BooleanField(default=False,
        help_text='Create or assign a workflow from an AI suggestion')
    psa_ai_billing = models.BooleanField(default=False,
        help_text='Modify financial fields (invoiced amount, contract usage) via AI')
    psa_ai_admin = models.BooleanField(default=False,
        help_text='Configure AI (model, threshold, allow/blocklist, voice)')
    psa_ai_request_triage = models.BooleanField(default=True,
        help_text='Request read-only AI triage guidance for a ticket (advisory output only)')

    # Knowledge Base (KB) Permissions — see psa.kb_browse + docs.global_kb_*
    kb_view_articles = models.BooleanField(default=True,
        help_text='View KB articles (browse the knowledge base)')
    kb_edit_articles = models.BooleanField(default=False,
        help_text='Create / edit / delete KB articles')
    kb_move_articles = models.BooleanField(default=False,
        help_text='Move KB articles between categories (bulk move)')
    kb_manage_categories = models.BooleanField(default=False,
        help_text='Create / edit / delete KB categories (global or org)')
    kb_publish_articles = models.BooleanField(default=False,
        help_text='Publish/unpublish KB articles (toggle is_published)')

    # --- Reports + financials (Phase 3 reports + dashboards) — v3.17.145 ---
    reports_view_dashboards = models.BooleanField(default=True)
    reports_view_financial = models.BooleanField(
        default=False,
        help_text='Profitability, effective hourly rate, revenue leakage, '
                  'margin analytics — surfaces revenue + cost numbers.',
    )
    reports_view_sla = models.BooleanField(default=False,
        help_text='SLA trend report. Defaults off because techs don\'t need it.')
    reports_view_capacity = models.BooleanField(default=False,
        help_text='Capacity / utilization report — exposes target hours + '
                  'realization % per tech across the team.')
    reports_manage_dashboards = models.BooleanField(default=False,
        help_text='Create / edit / delete dashboards + widgets.')
    reports_manage_scheduled = models.BooleanField(default=False,
        help_text='Configure scheduled reports.')

    # --- Resource management — v3.17.145 ---
    resourcing_view_team = models.BooleanField(default=False,
        help_text='See the staff tech roster + cost rates list.')
    resourcing_manage_cost_rates = models.BooleanField(default=False,
        help_text='Edit per-tech loaded $/hr rates. Drives all profitability math.')
    resourcing_approve_leave = models.BooleanField(default=False,
        help_text='Approve / deny LeaveRequest.')
    resourcing_manage_holidays = models.BooleanField(default=False)

    # --- Billing / financial — v3.17.145 ---
    billing_view_invoices = models.BooleanField(default=False)
    billing_send_invoices = models.BooleanField(default=False)
    billing_record_payments = models.BooleanField(default=False)
    billing_view_aging = models.BooleanField(default=False,
        help_text='See the cross-client aging report.')

    # --- Procurement (Phase 4) — v3.17.148 ---
    procurement_view = models.BooleanField(default=True,
        help_text='View Purchase Requisitions and Purchase Orders.')
    procurement_create_pr = models.BooleanField(default=True,
        help_text='Create / edit Purchase Requisitions (techs file these).')
    procurement_approve_pr = models.BooleanField(default=False,
        help_text='Approve / reject submitted Purchase Requisitions.')
    procurement_create_po = models.BooleanField(default=False,
        help_text='Create / edit Purchase Orders and convert PR to PO.')
    procurement_send_po = models.BooleanField(default=False,
        help_text='Email PO PDF to vendor and mark as sent.')

    # --- CRM (Phase 5) — v3.17.152 ---
    crm_view = models.BooleanField(default=False,
        help_text='View leads, opportunities, campaigns, and the pipeline.')
    crm_create_lead = models.BooleanField(default=False,
        help_text='Create / edit leads (file inbound prospects).')
    crm_manage_pipeline = models.BooleanField(default=False,
        help_text='Move opportunities through stages, convert leads, '
                  'create / edit opportunities.')
    crm_manage_campaigns = models.BooleanField(default=False,
        help_text='Create / edit marketing campaigns and view ROI.')
    crm_view_forecast = models.BooleanField(default=False,
        help_text='See $-weighted pipeline forecast (revenue projections).')

    # --- Change management (Phase 6.1) — v3.17.158 ---
    change_view = models.BooleanField(default=True)
    change_create = models.BooleanField(default=True,
        help_text='Submit a change request for CAB review.')
    change_approve_cab = models.BooleanField(default=False,
        help_text='Sit on the CAB and vote on changes.')
    change_implement = models.BooleanField(default=False,
        help_text='Move an approved change into Implementing.')

    # --- Problem management (Phase 6.2) — v3.17.160 ---
    problem_view = models.BooleanField(default=True)
    problem_create = models.BooleanField(default=True)
    problem_assign = models.BooleanField(default=False,
        help_text='Assign problems to investigators / reassign owners.')
    problem_resolve = models.BooleanField(default=False,
        help_text='Move a problem to resolved/closed status.')

    # --- Phase 6.3 release + catalog governance — v3.17.165 ---
    release_view = models.BooleanField(default=True)
    release_manage = models.BooleanField(default=False,
        help_text='Create / edit release windows + bundle changes.')
    release_freeze = models.BooleanField(default=False,
        help_text='Flip a release to frozen/completed/rolled_back.')
    catalog_propose_change = models.BooleanField(default=True,
        help_text='Propose edits to a service catalog item that requires approval.')
    catalog_approve_change = models.BooleanField(default=False,
        help_text='Approve / reject ServiceCatalogChange proposals.')

    # --- Phase 7 outsourcing — v3.17.166 ---
    outsourcing_share_tickets = models.BooleanField(default=False,
        help_text='Share a ticket with an outsourcing partner via HMAC-signed webhook.')

    # --- Phase 9 security alert ingestion — v3.17.168 ---
    security_alerts_view = models.BooleanField(default=True,
        help_text='View the security alert triage list and alert detail.')
    security_alerts_manage_connections = models.BooleanField(default=False,
        help_text='Create / edit / delete EDR / AV / firewall connections.')
    security_alerts_acknowledge = models.BooleanField(default=False,
        help_text='Acknowledge / dismiss / resolve alerts and convert to PSA tickets.')
    security_alerts_create_rules = models.BooleanField(default=False,
        help_text='Create / edit / delete auto-ticket rules + suppression windows.')

    # --- PSA Tickets (v3.17.477) ---
    # Until v3.17.477 ticket actions in the PSA / mobile surfaces were
    # gated only by membership + assignment. Now that the mobile app can
    # reassign tickets to another user and file tickets without a client,
    # we surface explicit perm flags here so role templates can grant
    # them (or hold them back from rank-and-file).
    tickets_view = models.BooleanField(default=True,
        help_text='View tickets in the PSA / mobile surfaces.')
    tickets_create = models.BooleanField(default=True,
        help_text='File new tickets.')
    tickets_edit = models.BooleanField(default=True,
        help_text='Edit ticket subject / description / status / priority.')
    tickets_assign = models.BooleanField(default=False,
        help_text='Assign a ticket to another user (re-assignment).')
    tickets_view_all = models.BooleanField(default=False,
        help_text='View tickets across all organizations (not just '
                  'tickets in orgs the user is a member of).')
    tickets_close = models.BooleanField(default=True,
        help_text='Move a ticket to a terminal status (resolved / closed).')
    tickets_delete = models.BooleanField(default=False,
        help_text='Hard-delete a ticket.')

    class Meta:
        db_table = 'role_templates'
        ordering = ['name']
        unique_together = [['name', 'organization']]

    def __str__(self):
        if self.organization:
            return f"{self.name} ({self.organization.name})"
        return f"{self.name} (System)"

    @classmethod
    def get_or_create_system_templates(cls):
        """Create default system role templates."""
        # Build "all booleans default False" base, then override per role.
        # When new RoleTemplate booleans are added later, they default to
        # False for these sample roles automatically — no maintenance.
        ALL_FALSE = {
            f.name: False
            for f in cls._meta.get_fields()
            if isinstance(f, models.BooleanField) and f.name != 'is_system_template'
        }

        def _build(name, description, **overrides):
            data = dict(ALL_FALSE)
            data['is_system_template'] = True
            data['name'] = name
            data['description'] = description
            data.update(overrides)
            return data

        templates = [
            {
                'name': 'Owner',
                'description': 'Full access to everything including user management and billing',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': True,
                'vault_edit': True,
                'vault_delete': True,
                'vault_export': True,
                'vault_view_password': True,
                'vault_manage_access_rules': True,
                'assets_view': True,
                'assets_create': True,
                'assets_edit': True,
                'assets_delete': True,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': True,
                'docs_delete': True,
                'docs_publish': True,
                'files_view': True,
                'files_upload': True,
                'files_delete': True,
                'monitoring_view': True,
                'monitoring_create': True,
                'monitoring_edit': True,
                'monitoring_delete': True,
                'monitoring_trigger': True,
                'integrations_view': True,
                'integrations_configure': True,
                'integrations_sync': True,
                'audit_view': True,
                'audit_export': True,
                'org_view_members': True,
                'org_invite_members': True,
                'org_manage_members': True,
                'org_manage_settings': True,
                'api_access': True,
                'api_keys_manage': True,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': True,
                'psa_ai_send_high_risk': True,
                'psa_ai_approve_reply': True,
                'psa_ai_apply_low_risk': True,
                'psa_ai_apply_high_risk': True,
                'psa_ai_approve_action': True,
                'psa_ai_run_script': True,
                'psa_ai_create_workflow': True,
                'psa_ai_billing': True,
                'psa_ai_admin': True,
                # KB
                'kb_view_articles': True,
                'kb_edit_articles': True,
                'kb_move_articles': True,
                'kb_manage_categories': True,
                'kb_publish_articles': True,
                # Reports + financials (v3.17.145) — Owner: all True
                'reports_view_dashboards': True,
                'reports_view_financial': True,
                'reports_view_sla': True,
                'reports_view_capacity': True,
                'reports_manage_dashboards': True,
                'reports_manage_scheduled': True,
                'resourcing_view_team': True,
                'resourcing_manage_cost_rates': True,
                'resourcing_approve_leave': True,
                'resourcing_manage_holidays': True,
                'billing_view_invoices': True,
                'billing_send_invoices': True,
                'billing_record_payments': True,
                'billing_view_aging': True,
                # Procurement (Phase 4) — Owner: all True
                'procurement_view': True,
                'procurement_create_pr': True,
                'procurement_approve_pr': True,
                'procurement_create_po': True,
                'procurement_send_po': True,
                # CRM (Phase 5) — Owner: all True
                'crm_view': True,
                'crm_create_lead': True,
                'crm_manage_pipeline': True,
                'crm_manage_campaigns': True,
                'crm_view_forecast': True,
                # Change management (Phase 6.1) — Owner: all True
                'change_view': True,
                'change_create': True,
                'change_approve_cab': True,
                'change_implement': True,
                # Problem management (Phase 6.2) — Owner: all True
                'problem_view': True,
                'problem_create': True,
                'problem_assign': True,
                'problem_resolve': True,
                # Release + catalog governance (Phase 6.3) — Owner: all True
                'release_view': True,
                'release_manage': True,
                'release_freeze': True,
                'catalog_propose_change': True,
                'catalog_approve_change': True,
                # Phase 7 outsourcing — Owner: True
                'outsourcing_share_tickets': True,
                # Phase 9 security alerts — Owner: all True
                'security_alerts_view': True,
                'security_alerts_manage_connections': True,
                'security_alerts_acknowledge': True,
                'security_alerts_create_rules': True,
                # PSA Tickets (v3.17.477) — Owner: all True
                'tickets_view': True,
                'tickets_create': True,
                'tickets_edit': True,
                'tickets_assign': True,
                'tickets_view_all': True,
                'tickets_close': True,
                'tickets_delete': True,
            },
            {
                'name': 'Administrator',
                'description': 'Manage all content and settings, but cannot manage users or billing',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': True,
                'vault_edit': True,
                'vault_delete': True,
                'vault_export': True,
                'vault_view_password': True,
                'vault_manage_access_rules': True,
                'assets_view': True,
                'assets_create': True,
                'assets_edit': True,
                'assets_delete': True,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': True,
                'docs_delete': True,
                'docs_publish': True,
                'files_view': True,
                'files_upload': True,
                'files_delete': True,
                'monitoring_view': True,
                'monitoring_create': True,
                'monitoring_edit': True,
                'monitoring_delete': True,
                'monitoring_trigger': True,
                'integrations_view': True,
                'integrations_configure': True,
                'integrations_sync': True,
                'audit_view': True,
                'audit_export': True,
                'org_view_members': True,
                'org_invite_members': True,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': True,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': True,
                'psa_ai_send_high_risk': True,
                'psa_ai_approve_reply': True,
                'psa_ai_apply_low_risk': True,
                'psa_ai_apply_high_risk': True,
                'psa_ai_approve_action': True,
                'psa_ai_run_script': True,
                'psa_ai_create_workflow': True,
                'psa_ai_billing': True,
                'psa_ai_admin': False,
                # KB
                'kb_view_articles': True,
                'kb_edit_articles': True,
                'kb_move_articles': True,
                'kb_manage_categories': True,
                'kb_publish_articles': True,
                # Reports + financials (v3.17.145) — Administrator: all True
                # except reports_manage_scheduled (admins delegate that).
                'reports_view_dashboards': True,
                'reports_view_financial': True,
                'reports_view_sla': True,
                'reports_view_capacity': True,
                'reports_manage_dashboards': True,
                'reports_manage_scheduled': False,
                'resourcing_view_team': True,
                'resourcing_manage_cost_rates': True,
                'resourcing_approve_leave': True,
                'resourcing_manage_holidays': True,
                'billing_view_invoices': True,
                'billing_send_invoices': True,
                'billing_record_payments': True,
                'billing_view_aging': True,
                # Procurement (Phase 4) — Administrator: all True
                'procurement_view': True,
                'procurement_create_pr': True,
                'procurement_approve_pr': True,
                'procurement_create_po': True,
                'procurement_send_po': True,
                # CRM (Phase 5) — Administrator: all True
                'crm_view': True,
                'crm_create_lead': True,
                'crm_manage_pipeline': True,
                'crm_manage_campaigns': True,
                'crm_view_forecast': True,
                # Change management (Phase 6.1) — Administrator: all True
                'change_view': True,
                'change_create': True,
                'change_approve_cab': True,
                'change_implement': True,
                # Problem management (Phase 6.2) — Administrator: all True
                'problem_view': True,
                'problem_create': True,
                'problem_assign': True,
                'problem_resolve': True,
                # Release + catalog governance (Phase 6.3) — Administrator: all True
                'release_view': True,
                'release_manage': True,
                'release_freeze': True,
                'catalog_propose_change': True,
                'catalog_approve_change': True,
                # Phase 7 outsourcing — Administrator: True
                'outsourcing_share_tickets': True,
                # Phase 9 security alerts — Administrator: all True
                'security_alerts_view': True,
                'security_alerts_manage_connections': True,
                'security_alerts_acknowledge': True,
                'security_alerts_create_rules': True,
                # PSA Tickets (v3.17.477) — Administrator: all True
                'tickets_view': True,
                'tickets_create': True,
                'tickets_edit': True,
                'tickets_assign': True,
                'tickets_view_all': True,
                'tickets_close': True,
                'tickets_delete': True,
            },
            {
                'name': 'Editor',
                'description': 'Create and edit content, but cannot delete or manage settings',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': True,
                'vault_edit': True,
                'vault_delete': False,
                'vault_export': False,
                'vault_view_password': True,
                'vault_manage_access_rules': False,
                'assets_view': True,
                'assets_create': True,
                'assets_edit': True,
                'assets_delete': False,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': True,
                'docs_delete': False,
                'docs_publish': False,
                'files_view': True,
                'files_upload': True,
                'files_delete': False,
                'monitoring_view': True,
                'monitoring_create': True,
                'monitoring_edit': True,
                'monitoring_delete': False,
                'monitoring_trigger': True,
                'integrations_view': False,
                'integrations_configure': False,
                'integrations_sync': False,
                'audit_view': False,
                'audit_export': False,
                'org_view_members': True,
                'org_invite_members': False,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': True,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': True,
                'psa_ai_send_high_risk': True,
                'psa_ai_approve_reply': True,
                'psa_ai_apply_low_risk': True,
                'psa_ai_apply_high_risk': True,
                'psa_ai_approve_action': False,
                'psa_ai_run_script': True,
                'psa_ai_create_workflow': True,
                'psa_ai_billing': False,
                'psa_ai_admin': False,
                # KB — Editor: no manage_categories
                'kb_view_articles': True,
                'kb_edit_articles': True,
                'kb_move_articles': True,
                'kb_manage_categories': False,
                'kb_publish_articles': True,
                # Reports + financials (v3.17.145) — Editor (techs):
                # dashboards only, no financial/sla/capacity/billing.
                'reports_view_dashboards': True,
                'reports_view_financial': False,
                'reports_view_sla': False,
                'reports_view_capacity': False,
                'reports_manage_dashboards': False,
                'reports_manage_scheduled': False,
                'resourcing_view_team': False,
                'resourcing_manage_cost_rates': False,
                'resourcing_approve_leave': False,
                'resourcing_manage_holidays': False,
                'billing_view_invoices': False,
                'billing_send_invoices': False,
                'billing_record_payments': False,
                'billing_view_aging': False,
                # Procurement (Phase 4) — Editor (techs): can file PRs,
                # cannot approve PRs / create / send POs.
                'procurement_view': True,
                'procurement_create_pr': True,
                'procurement_approve_pr': False,
                'procurement_create_po': False,
                'procurement_send_po': False,
                # CRM (Phase 5) — Editor: view + create_lead + manage_pipeline.
                'crm_view': True,
                'crm_create_lead': True,
                'crm_manage_pipeline': True,
                'crm_manage_campaigns': False,
                'crm_view_forecast': False,
                # Change management (Phase 6.1) — Editor: view + create only.
                'change_view': True,
                'change_create': True,
                'change_approve_cab': False,
                'change_implement': False,
                # Problem management (Phase 6.2) — Editor: view + create only.
                'problem_view': True,
                'problem_create': True,
                'problem_assign': False,
                'problem_resolve': False,
                # Release + catalog governance (Phase 6.3) — Editor: view + propose.
                'release_view': True,
                'release_manage': False,
                'release_freeze': False,
                'catalog_propose_change': True,
                'catalog_approve_change': False,
                # Phase 9 security alerts — Editor: view + acknowledge.
                'security_alerts_view': True,
                'security_alerts_manage_connections': False,
                'security_alerts_acknowledge': True,
                'security_alerts_create_rules': False,
                # PSA Tickets (v3.17.477) — Editor: file + work, can't reassign or hard-delete.
                'tickets_view': True,
                'tickets_create': True,
                'tickets_edit': True,
                'tickets_assign': False,
                'tickets_view_all': False,
                'tickets_close': True,
                'tickets_delete': False,
            },
            {
                'name': 'Help Desk',
                'description': 'View and create tickets, view passwords, cannot edit or delete',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': False,
                'vault_edit': False,
                'vault_delete': False,
                'vault_export': False,
                'vault_view_password': True,
                'vault_manage_access_rules': False,
                'assets_view': True,
                'assets_create': False,
                'assets_edit': False,
                'assets_delete': False,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': False,
                'docs_delete': False,
                'docs_publish': False,
                'files_view': True,
                'files_upload': True,
                'files_delete': False,
                'monitoring_view': True,
                'monitoring_create': False,
                'monitoring_edit': False,
                'monitoring_delete': False,
                'monitoring_trigger': False,
                'integrations_view': False,
                'integrations_configure': False,
                'integrations_sync': False,
                'audit_view': False,
                'audit_export': False,
                'org_view_members': True,
                'org_invite_members': False,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': False,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': True,
                'psa_ai_send_high_risk': False,
                'psa_ai_approve_reply': False,
                'psa_ai_apply_low_risk': True,
                'psa_ai_apply_high_risk': False,
                'psa_ai_approve_action': False,
                'psa_ai_run_script': False,
                'psa_ai_create_workflow': False,
                'psa_ai_billing': False,
                'psa_ai_admin': False,
                # KB — Help Desk: view + minimal edit (matches docs_create=True)
                'kb_view_articles': True,
                'kb_edit_articles': False,
                'kb_move_articles': False,
                'kb_manage_categories': False,
                'kb_publish_articles': False,
                # Reports + financials (v3.17.145) — Help Desk:
                # dashboards only.
                'reports_view_dashboards': True,
                'reports_view_financial': False,
                'reports_view_sla': False,
                'reports_view_capacity': False,
                'reports_manage_dashboards': False,
                'reports_manage_scheduled': False,
                'resourcing_view_team': False,
                'resourcing_manage_cost_rates': False,
                'resourcing_approve_leave': False,
                'resourcing_manage_holidays': False,
                'billing_view_invoices': False,
                'billing_send_invoices': False,
                'billing_record_payments': False,
                'billing_view_aging': False,
                # Procurement (Phase 4) — Help Desk: view + file PRs.
                'procurement_view': True,
                'procurement_create_pr': True,
                'procurement_approve_pr': False,
                'procurement_create_po': False,
                'procurement_send_po': False,
                # CRM (Phase 5) — Help Desk: view only (so they can see
                # leads/opps without manipulating pipeline).
                'crm_view': True,
                'crm_create_lead': False,
                'crm_manage_pipeline': False,
                'crm_manage_campaigns': False,
                'crm_view_forecast': False,
                # Change management (Phase 6.1) — Help Desk: view + create.
                'change_view': True,
                'change_create': True,
                'change_approve_cab': False,
                'change_implement': False,
                # Problem management (Phase 6.2) — Help Desk: view + create.
                'problem_view': True,
                'problem_create': True,
                'problem_assign': False,
                'problem_resolve': False,
                # Release + catalog governance (Phase 6.3) — Help Desk: view + propose.
                'release_view': True,
                'release_manage': False,
                'release_freeze': False,
                'catalog_propose_change': True,
                'catalog_approve_change': False,
                # Phase 9 security alerts — Help Desk: view + acknowledge.
                'security_alerts_view': True,
                'security_alerts_manage_connections': False,
                'security_alerts_acknowledge': True,
                'security_alerts_create_rules': False,
                # PSA Tickets (v3.17.477) — Help Desk: file + work, no assign / delete.
                'tickets_view': True,
                'tickets_create': True,
                'tickets_edit': True,
                'tickets_assign': False,
                'tickets_view_all': False,
                'tickets_close': True,
                'tickets_delete': False,
            },
            {
                'name': 'IT Manager',
                'description': 'Manage assets, monitoring, and infrastructure but limited password access',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': False,
                'vault_edit': False,
                'vault_delete': False,
                'vault_export': False,
                'vault_view_password': False,
                'vault_manage_access_rules': False,
                'assets_view': True,
                'assets_create': True,
                'assets_edit': True,
                'assets_delete': True,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': True,
                'docs_delete': False,
                'docs_publish': True,
                'files_view': True,
                'files_upload': True,
                'files_delete': True,
                'monitoring_view': True,
                'monitoring_create': True,
                'monitoring_edit': True,
                'monitoring_delete': True,
                'monitoring_trigger': True,
                'integrations_view': True,
                'integrations_configure': False,
                'integrations_sync': True,
                'audit_view': True,
                'audit_export': False,
                'org_view_members': True,
                'org_invite_members': True,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': True,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': True,
                'psa_ai_send_high_risk': True,
                'psa_ai_approve_reply': True,
                'psa_ai_apply_low_risk': True,
                'psa_ai_apply_high_risk': True,
                'psa_ai_approve_action': False,
                'psa_ai_run_script': True,
                'psa_ai_create_workflow': True,
                'psa_ai_billing': False,
                'psa_ai_admin': False,
                # KB — IT Manager: full KB access
                'kb_view_articles': True,
                'kb_edit_articles': True,
                'kb_move_articles': True,
                'kb_manage_categories': True,
                'kb_publish_articles': True,
                # Reports + financials (v3.17.145) — IT Manager:
                # dashboards + financial + sla + capacity, but NOT
                # manage_cost_rates (owner-only).
                'reports_view_dashboards': True,
                'reports_view_financial': True,
                'reports_view_sla': True,
                'reports_view_capacity': True,
                'reports_manage_dashboards': True,
                'reports_manage_scheduled': False,
                'resourcing_view_team': True,
                'resourcing_manage_cost_rates': False,
                'resourcing_approve_leave': True,
                'resourcing_manage_holidays': True,
                'billing_view_invoices': True,
                'billing_send_invoices': False,
                'billing_record_payments': False,
                'billing_view_aging': True,
                # Procurement (Phase 4) — IT Manager: full procurement.
                'procurement_view': True,
                'procurement_create_pr': True,
                'procurement_approve_pr': True,
                'procurement_create_po': True,
                'procurement_send_po': True,
                # CRM (Phase 5) — IT Manager: full pipeline + forecast,
                # but no campaign management (sales/marketing keeps that).
                'crm_view': True,
                'crm_create_lead': True,
                'crm_manage_pipeline': True,
                'crm_manage_campaigns': False,
                'crm_view_forecast': True,
                # Change management (Phase 6.1) — IT Manager: all four.
                'change_view': True,
                'change_create': True,
                'change_approve_cab': True,
                'change_implement': True,
                # Problem management (Phase 6.2) — IT Manager: all four.
                'problem_view': True,
                'problem_create': True,
                'problem_assign': True,
                'problem_resolve': True,
                # Release + catalog governance (Phase 6.3) — IT Manager: all True
                'release_view': True,
                'release_manage': True,
                'release_freeze': True,
                'catalog_propose_change': True,
                'catalog_approve_change': True,
                # Phase 9 security alerts — IT Manager: all True
                'security_alerts_view': True,
                'security_alerts_manage_connections': True,
                'security_alerts_acknowledge': True,
                'security_alerts_create_rules': True,
                # PSA Tickets (v3.17.477) — IT Manager: all True
                'tickets_view': True,
                'tickets_create': True,
                'tickets_edit': True,
                'tickets_assign': True,
                'tickets_view_all': True,
                'tickets_close': True,
                'tickets_delete': True,
            },
            {
                'name': 'Documentation Writer',
                'description': 'Full access to documentation, read-only for everything else',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': False,
                'vault_edit': False,
                'vault_delete': False,
                'vault_export': False,
                'vault_view_password': False,
                'vault_manage_access_rules': False,
                'assets_view': True,
                'assets_create': False,
                'assets_edit': False,
                'assets_delete': False,
                'docs_view': True,
                'docs_create': True,
                'docs_edit': True,
                'docs_delete': True,
                'docs_publish': True,
                'files_view': True,
                'files_upload': True,
                'files_delete': True,
                'monitoring_view': True,
                'monitoring_create': False,
                'monitoring_edit': False,
                'monitoring_delete': False,
                'monitoring_trigger': False,
                'integrations_view': False,
                'integrations_configure': False,
                'integrations_sync': False,
                'audit_view': False,
                'audit_export': False,
                'org_view_members': True,
                'org_invite_members': False,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': False,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': False,
                'psa_ai_send_high_risk': False,
                'psa_ai_approve_reply': False,
                'psa_ai_apply_low_risk': False,
                'psa_ai_apply_high_risk': False,
                'psa_ai_approve_action': False,
                'psa_ai_run_script': False,
                'psa_ai_create_workflow': False,
                'psa_ai_billing': False,
                'psa_ai_admin': False,
                # KB — Documentation Writer: full KB access
                'kb_view_articles': True,
                'kb_edit_articles': True,
                'kb_move_articles': True,
                'kb_manage_categories': True,
                'kb_publish_articles': True,
                # Reports + financials (v3.17.145) — Documentation Writer:
                # dashboards only.
                'reports_view_dashboards': True,
                'reports_view_financial': False,
                'reports_view_sla': False,
                'reports_view_capacity': False,
                'reports_manage_dashboards': False,
                'reports_manage_scheduled': False,
                'resourcing_view_team': False,
                'resourcing_manage_cost_rates': False,
                'resourcing_approve_leave': False,
                'resourcing_manage_holidays': False,
                'billing_view_invoices': False,
                'billing_send_invoices': False,
                'billing_record_payments': False,
                'billing_view_aging': False,
                # Procurement (Phase 4) — Documentation Writer: view only.
                'procurement_view': True,
                'procurement_create_pr': False,
                'procurement_approve_pr': False,
                'procurement_create_po': False,
                'procurement_send_po': False,
                # CRM (Phase 5) — Documentation Writer: no CRM access.
                'crm_view': False,
                'crm_create_lead': False,
                'crm_manage_pipeline': False,
                'crm_manage_campaigns': False,
                'crm_view_forecast': False,
                # Change management (Phase 6.1) — Documentation Writer: view only.
                'change_view': True,
                'change_create': False,
                'change_approve_cab': False,
                'change_implement': False,
                # Problem management (Phase 6.2) — Documentation Writer: view only.
                'problem_view': True,
                'problem_create': False,
                'problem_assign': False,
                'problem_resolve': False,
                # Release + catalog governance (Phase 6.3) — Documentation Writer: view only.
                'release_view': True,
                'release_manage': False,
                'release_freeze': False,
                'catalog_propose_change': False,
                'catalog_approve_change': False,
                # Phase 9 security alerts — Documentation Writer: view only.
                'security_alerts_view': True,
                'security_alerts_manage_connections': False,
                'security_alerts_acknowledge': False,
                'security_alerts_create_rules': False,
                # PSA Tickets (v3.17.477) — Documentation Writer: view only.
                'tickets_view': True,
                'tickets_create': False,
                'tickets_edit': False,
                'tickets_assign': False,
                'tickets_view_all': False,
                'tickets_close': False,
                'tickets_delete': False,
            },
            {
                'name': 'Read-Only',
                'description': 'View-only access to all content, cannot make any changes',
                'is_system_template': True,
                'vault_view': True,
                'vault_create': False,
                'vault_edit': False,
                'vault_delete': False,
                'vault_export': False,
                'vault_view_password': False,
                'vault_manage_access_rules': False,
                'assets_view': True,
                'assets_create': False,
                'assets_edit': False,
                'assets_delete': False,
                'docs_view': True,
                'docs_create': False,
                'docs_edit': False,
                'docs_delete': False,
                'docs_publish': False,
                'files_view': True,
                'files_upload': False,
                'files_delete': False,
                'monitoring_view': True,
                'monitoring_create': False,
                'monitoring_edit': False,
                'monitoring_delete': False,
                'monitoring_trigger': False,
                'integrations_view': False,
                'integrations_configure': False,
                'integrations_sync': False,
                'audit_view': False,
                'audit_export': False,
                'org_view_members': True,
                'org_invite_members': False,
                'org_manage_members': False,
                'org_manage_settings': False,
                'api_access': False,
                'api_keys_manage': False,
                'psa_ai_view': True,
                'psa_ai_send_low_risk': False,
                'psa_ai_send_high_risk': False,
                'psa_ai_approve_reply': False,
                'psa_ai_apply_low_risk': False,
                'psa_ai_apply_high_risk': False,
                'psa_ai_approve_action': False,
                'psa_ai_run_script': False,
                'psa_ai_create_workflow': False,
                'psa_ai_billing': False,
                'psa_ai_admin': False,
                # KB — Read-Only: view only
                'kb_view_articles': True,
                'kb_edit_articles': False,
                'kb_move_articles': False,
                'kb_manage_categories': False,
                'kb_publish_articles': False,
                # Reports + financials (v3.17.145) — Read-Only:
                # dashboards only, no mutations.
                'reports_view_dashboards': True,
                'reports_view_financial': False,
                'reports_view_sla': False,
                'reports_view_capacity': False,
                'reports_manage_dashboards': False,
                'reports_manage_scheduled': False,
                'resourcing_view_team': False,
                'resourcing_manage_cost_rates': False,
                'resourcing_approve_leave': False,
                'resourcing_manage_holidays': False,
                'billing_view_invoices': False,
                'billing_send_invoices': False,
                'billing_record_payments': False,
                'billing_view_aging': False,
                # Procurement (Phase 4) — Read-Only: view only.
                'procurement_view': True,
                'procurement_create_pr': False,
                'procurement_approve_pr': False,
                'procurement_create_po': False,
                'procurement_send_po': False,
                # CRM (Phase 5) — Read-Only: only crm_view.
                'crm_view': True,
                'crm_create_lead': False,
                'crm_manage_pipeline': False,
                'crm_manage_campaigns': False,
                'crm_view_forecast': False,
                # Change management (Phase 6.1) — Read-Only: view only.
                'change_view': True,
                'change_create': False,
                'change_approve_cab': False,
                'change_implement': False,
                # Problem management (Phase 6.2) — Read-Only: view only.
                'problem_view': True,
                'problem_create': False,
                'problem_assign': False,
                'problem_resolve': False,
                # Release + catalog governance (Phase 6.3) — Read-Only: view only.
                'release_view': True,
                'release_manage': False,
                'release_freeze': False,
                'catalog_propose_change': False,
                'catalog_approve_change': False,
                # Phase 9 security alerts — Read-Only: view only.
                'security_alerts_view': True,
                'security_alerts_manage_connections': False,
                'security_alerts_acknowledge': False,
                'security_alerts_create_rules': False,
                # PSA Tickets (v3.17.477) — Read-Only: view only.
                'tickets_view': True,
                'tickets_create': False,
                'tickets_edit': False,
                'tickets_assign': False,
                'tickets_view_all': False,
                'tickets_close': False,
                'tickets_delete': False,
            },
            # --- MSP-named sample roles (v3.17.164) -----------------------
            # Built via _build() so they only flip the listed perms; every
            # other RoleTemplate boolean defaults False, which means new
            # permission fields added later are safely off by default for
            # these sample roles. Users can edit them at /accounts/roles/
            # like any other role template — they're starting points.
            _build(
                'Client',
                'Customer portal user — files tickets and views items their org admin has shared.',
                vault_view=True,
                vault_view_password=True,
                assets_view=True,
                docs_view=True,
                files_view=True,
                kb_view_articles=True,
                change_view=True,
                procurement_view=True,
                # Phase 6.3 — view only
                release_view=True,
                # PSA Tickets (v3.17.477) — Client: file own tickets.
                tickets_view=True,
                tickets_create=True,
            ),
            _build(
                'Client Admin',
                "Customer org admin — manages who at their organization can see shared vault items + invite other portal users.",
                # Inherits Client's view perms
                vault_view=True,
                vault_view_password=True,
                assets_view=True,
                docs_view=True,
                files_view=True,
                kb_view_articles=True,
                change_view=True,
                procurement_view=True,
                # + own-org user/vault management
                vault_create=True,
                vault_edit=True,
                docs_create=True,
                docs_edit=True,
                org_view_members=True,
                org_invite_members=True,
                org_manage_members=True,
                # Phase 6.3 — view only
                release_view=True,
                # PSA Tickets (v3.17.477) — Client Admin: file + edit own-org tickets.
                tickets_view=True,
                tickets_create=True,
                tickets_edit=True,
                tickets_close=True,
            ),
            _build(
                'Technician',
                'Internal tech doing day-to-day support work — tickets, time, asset edits, KB contributions.',
                vault_view=True,
                vault_create=True,
                vault_edit=True,
                vault_view_password=True,
                assets_view=True,
                assets_create=True,
                assets_edit=True,
                docs_view=True,
                docs_create=True,
                docs_edit=True,
                files_view=True,
                files_upload=True,
                monitoring_view=True,
                monitoring_create=True,
                monitoring_edit=True,
                monitoring_trigger=True,
                integrations_view=True,
                org_view_members=True,
                kb_view_articles=True,
                kb_edit_articles=True,
                kb_move_articles=True,
                reports_view_dashboards=True,
                procurement_view=True,
                procurement_create_pr=True,
                change_view=True,
                change_create=True,
                problem_view=True,
                problem_create=True,
                psa_ai_request_triage=True,
                # Phase 6.3 — Technician: view + propose only
                release_view=True,
                catalog_propose_change=True,
                # Phase 9 — Technician: view + acknowledge
                security_alerts_view=True,
                security_alerts_acknowledge=True,
                # PSA Tickets (v3.17.477) — Technician: file + work, no reassign.
                tickets_view=True,
                tickets_create=True,
                tickets_edit=True,
                tickets_close=True,
            ),
            _build(
                'Tech Manager',
                'Supervises technicians — approves leave, dispatches work, approves change requests + procurement requisitions.',
                # Everything Technician has
                vault_view=True,
                vault_create=True,
                vault_edit=True,
                vault_view_password=True,
                assets_view=True,
                assets_create=True,
                assets_edit=True,
                docs_view=True,
                docs_create=True,
                docs_edit=True,
                files_view=True,
                files_upload=True,
                monitoring_view=True,
                monitoring_create=True,
                monitoring_edit=True,
                monitoring_trigger=True,
                integrations_view=True,
                org_view_members=True,
                kb_view_articles=True,
                kb_edit_articles=True,
                kb_move_articles=True,
                reports_view_dashboards=True,
                procurement_view=True,
                procurement_create_pr=True,
                change_view=True,
                change_create=True,
                problem_view=True,
                problem_create=True,
                psa_ai_request_triage=True,
                # + Tech Manager additions
                vault_delete=True,
                docs_delete=True,
                docs_publish=True,
                monitoring_delete=True,
                audit_view=True,
                org_invite_members=True,
                kb_publish_articles=True,
                kb_manage_categories=True,
                reports_view_capacity=True,
                reports_view_sla=True,
                resourcing_view_team=True,
                resourcing_approve_leave=True,
                procurement_approve_pr=True,
                change_approve_cab=True,
                change_implement=True,
                problem_assign=True,
                problem_resolve=True,
                # Phase 6.3 — Tech Manager: full release + catalog governance
                release_view=True,
                release_manage=True,
                release_freeze=True,
                catalog_propose_change=True,
                catalog_approve_change=True,
                # Phase 7 outsourcing — Tech Manager: True
                outsourcing_share_tickets=True,
                # Phase 9 — Tech Manager: full
                security_alerts_view=True,
                security_alerts_manage_connections=True,
                security_alerts_acknowledge=True,
                security_alerts_create_rules=True,
                # PSA Tickets (v3.17.477) — Tech Manager: full incl. assign.
                tickets_view=True,
                tickets_create=True,
                tickets_edit=True,
                tickets_assign=True,
                tickets_view_all=True,
                tickets_close=True,
            ),
            _build(
                'Office Manager',
                'Financial + operations — sends invoices, records payments, sees aging, manages cost rates + CRM pipeline.',
                # Everything Tech Manager has
                vault_view=True,
                vault_create=True,
                vault_edit=True,
                vault_view_password=True,
                assets_view=True,
                assets_create=True,
                assets_edit=True,
                docs_view=True,
                docs_create=True,
                docs_edit=True,
                files_view=True,
                files_upload=True,
                monitoring_view=True,
                monitoring_create=True,
                monitoring_edit=True,
                monitoring_trigger=True,
                integrations_view=True,
                org_view_members=True,
                kb_view_articles=True,
                kb_edit_articles=True,
                kb_move_articles=True,
                reports_view_dashboards=True,
                procurement_view=True,
                procurement_create_pr=True,
                change_view=True,
                change_create=True,
                problem_view=True,
                problem_create=True,
                psa_ai_request_triage=True,
                vault_delete=True,
                docs_delete=True,
                docs_publish=True,
                monitoring_delete=True,
                audit_view=True,
                org_invite_members=True,
                kb_publish_articles=True,
                kb_manage_categories=True,
                reports_view_capacity=True,
                reports_view_sla=True,
                resourcing_view_team=True,
                resourcing_approve_leave=True,
                procurement_approve_pr=True,
                change_approve_cab=True,
                change_implement=True,
                problem_assign=True,
                problem_resolve=True,
                # + Office Manager additions
                vault_export=True,
                vault_manage_access_rules=True,
                integrations_configure=True,
                integrations_sync=True,
                audit_export=True,
                api_access=True,
                billing_view_invoices=True,
                billing_send_invoices=True,
                billing_record_payments=True,
                billing_view_aging=True,
                reports_view_financial=True,
                reports_manage_dashboards=True,
                reports_manage_scheduled=True,
                resourcing_manage_cost_rates=True,
                resourcing_manage_holidays=True,
                procurement_create_po=True,
                procurement_send_po=True,
                crm_view=True,
                crm_create_lead=True,
                crm_manage_pipeline=True,
                crm_manage_campaigns=True,
                crm_view_forecast=True,
                # Phase 6.3 — Office Manager: full release + catalog governance
                release_view=True,
                release_manage=True,
                release_freeze=True,
                catalog_propose_change=True,
                catalog_approve_change=True,
                # Phase 7 outsourcing — Office Manager: True
                outsourcing_share_tickets=True,
                # Phase 9 — Office Manager: full
                security_alerts_view=True,
                security_alerts_manage_connections=True,
                security_alerts_acknowledge=True,
                security_alerts_create_rules=True,
                # PSA Tickets (v3.17.477) — Office Manager: full incl. assign / delete.
                tickets_view=True,
                tickets_create=True,
                tickets_edit=True,
                tickets_assign=True,
                tickets_view_all=True,
                tickets_close=True,
                tickets_delete=True,
            ),
            _build(
                'Full Admin',
                'Full access to everything (alias for Owner).',
                **{k: True for k in ALL_FALSE.keys()},
            ),
        ]

        for template_data in templates:
            template, created = cls.objects.get_or_create(
                name=template_data['name'],
                organization=None,
                defaults=template_data
            )
            if created:
                print(f"Created system role template: {template.name}")
