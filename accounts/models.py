"""
Accounts models - Memberships and Roles
"""
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Organization, BaseModel


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
            )
        elif self.role == Role.ADMIN:
            return SimpleNamespace(
                vault_view=True, vault_create=True, vault_edit=True, vault_delete=True,
                vault_export=True, vault_view_password=True,
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
            )
        elif self.role == Role.EDITOR:
            return SimpleNamespace(
                vault_view=True, vault_create=True, vault_edit=True, vault_delete=False,
                vault_export=False, vault_view_password=True,
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
            )
        else:  # READONLY
            return SimpleNamespace(
                vault_view=True, vault_create=False, vault_edit=False, vault_delete=False,
                vault_export=False, vault_view_password=False,
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
    locale = models.CharField(max_length=10, default='en', choices=[
        ('en', 'English'),
        ('fr', 'French'),
        ('de', 'German'),
        ('es', 'Spanish'),
    ])
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
    ])
    background_image = models.ImageField(
        upload_to='backgrounds/',
        null=True,
        blank=True,
        help_text='Custom background image for your profile'
    )
    preset_background = models.CharField(
        max_length=50,
        default='abstract-1',
        blank=True,
        choices=[
            ('abstract-1', 'Purple Gradient'),
            ('abstract-2', 'Blue Wave'),
            ('abstract-3', 'Orange Sunset'),
            ('abstract-4', 'Green Aurora'),
            ('abstract-5', 'Pink Nebula'),
            ('abstract-6', 'Cyan Fluid'),
            ('abstract-7', 'Red Geometric'),
            ('abstract-8', 'Teal Gradient'),
            ('abstract-9', 'Yellow Light'),
            ('abstract-10', 'Indigo Smoke'),
            ('abstract-11', 'Magenta Flow'),
            ('abstract-12', 'Navy Waves'),
        ],
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
            },
        ]

        for template_data in templates:
            template, created = cls.objects.get_or_create(
                name=template_data['name'],
                organization=None,
                defaults=template_data
            )
            if created:
                print(f"Created system role template: {template.name}")
