"""
Single sign-on with a generic OpenID Connect provider (Keycloak or any
certified OP).

One ClientSt0r install serves one MSP. A provider row pins the OP issuer and
(by default) the MSP's organization at the OP; tokens for any other issuer or
organization are refused. Accounts are found strictly by (issuer, sub) in
OIDCIdentity, never by e-mail.

Authorization stays local: a token's roles are only looked up in the mapping
tables below at sign-in. Memberships created from a mapping are tagged
(OIDCManagedMembership) and only those are ever changed by SSO, like
accounts.Membership.ldap_group_mapping does for LDAP.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from vault.secret_fields import EncryptedTextField

# Signature algorithms an ID / logout token may use. Never 'none', never HS*.
ALLOWED_ALGORITHMS = ('RS256', 'PS256', 'ES256', 'EdDSA')

KEYCLOAK_ROLES_CLAIM = 'resource_access.{client_id}.roles'


class OIDCProvider(models.Model):
    AUTH_PRIVATE_KEY_JWT = 'private_key_jwt'
    AUTH_CLIENT_SECRET_BASIC = 'client_secret_basic'
    CLIENT_AUTH_CHOICES = [
        (AUTH_PRIVATE_KEY_JWT, 'Signed JWT with a key pair generated here (private_key_jwt, recommended)'),
        (AUTH_CLIENT_SECRET_BASIC, 'Client secret (client_secret_basic)'),
    ]

    name = models.CharField(max_length=100, help_text='Shown on the sign-in button: "Sign in with <name>".')
    slug = models.SlugField(max_length=50, unique=True,
                            help_text='Part of the redirect and back-channel logout URLs.')
    enabled = models.BooleanField(default=False,
                                  help_text='Off: no sign-in button, and every endpoint of this provider returns 404.')

    issuer = models.URLField(max_length=500,
                             help_text='Exact issuer, e.g. https://id.example.com/realms/agit8or. '
                                       'Discovery is read from <issuer>/.well-known/openid-configuration.')
    client_id = models.CharField(max_length=255)
    client_auth_method = models.CharField(max_length=30, choices=CLIENT_AUTH_CHOICES,
                                          default=AUTH_PRIVATE_KEY_JWT)
    client_secret = EncryptedTextField(blank=True, help_text='Only for client_secret_basic. Never shown again.')
    # private_key_jwt: generated here, the private half never leaves the
    # database (encrypted); the public JWK is shown for registration at the OP.
    private_key_pem = EncryptedTextField(blank=True, editable=False)
    key_id = models.CharField(max_length=100, blank=True, editable=False)
    key_created_at = models.DateTimeField(null=True, blank=True, editable=False)

    scopes = models.CharField(max_length=500, default='openid email profile organization',
                              help_text='Space separated. "openid" is always sent.')
    allowed_algorithms = models.CharField(max_length=100, default=' '.join(ALLOWED_ALGORITHMS),
                                          help_text='ID / logout token signature algorithms accepted '
                                                    '(subset of RS256 PS256 ES256 EdDSA).')
    use_userinfo = models.BooleanField(default=False,
                                       help_text='Also read the userinfo endpoint (server side) and merge '
                                                 'its claims when its sub matches the ID token.')

    # MSP pin: the organization at the OP this install belongs to.
    org_claim = models.CharField(max_length=200, default='organization', blank=True,
                                 help_text='Claim listing the user\'s organizations (Keycloak Organizations: '
                                           '"organization"). Blank only for an OP / realm dedicated to this MSP.')
    msp_org_alias = models.CharField(max_length=100, blank=True,
                                     help_text='The MSP\'s organization alias at the OP. Tokens without it are '
                                               'refused; roles are read with the "<alias>:" prefix.')
    msp_org_id = models.CharField(max_length=100, blank=True,
                                  help_text='Optional organization id (UUID). When set, the org claim must carry '
                                            'this id for the alias.')
    roles_claim = models.CharField(max_length=200, default=KEYCLOAK_ROLES_CLAIM,
                                   help_text='Dotted path to the role list; {client_id} is replaced. '
                                             'Roles are "<alias>:<role>" and "<alias>:customer:<key>:<role>".')

    # Accounts
    jit_provisioning = models.BooleanField(default=False,
                                           help_text='Create an account at first sign-in for an unknown user '
                                                     'with a verified e-mail and a mapped MSP staff role.')
    require_email_verified = models.BooleanField(default=True,
                                                 help_text='Only create accounts when email_verified is true.')

    # MFA
    accept_idp_mfa = models.BooleanField(default=False,
                                         help_text='Let the OP\'s MFA stand in for ClientSt0r\'s 2FA when the '
                                                   'token\'s acr / amr say so. Off: local 2FA as today.')
    mfa_acr_values = models.CharField(max_length=500, blank=True,
                                      default='urn:agit8or:acr:mfa urn:agit8or:acr:phr',
                                      help_text='Space separated acr values that mean MFA was performed.')
    mfa_amr_values = models.CharField(max_length=200, blank=True, default='mfa otp hwk swk',
                                      help_text='Space separated amr values that mean a second factor.')
    login_acr_values = models.CharField(max_length=500, blank=True,
                                        help_text='Optional acr_values sent with every sign-in.')
    stepup_acr_values = models.CharField(max_length=500, blank=True,
                                         help_text='Optional acr_values sent with "Confirm it\'s you".')

    # Network
    allow_private_network = models.BooleanField(
        default=False,
        help_text='The OP is on a private network (RFC 1918 / ULA). Off: only public addresses. Cloud '
                  'metadata addresses are refused regardless; loopback also needs '
                  'ALLOW_PRIVATE_IP_INTEGRATIONS. Also allows http:// (testing only).')
    ca_bundle_pem = models.TextField(blank=True,
                                     help_text='Optional PEM CA certificate(s) for an OP with a private CA.')

    # Logout
    rp_logout = models.BooleanField(default=True,
                                    help_text='Signing out here also ends the session at the OP '
                                              '(end_session_endpoint).')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'oidc_providers'
        ordering = ['name']

    def __str__(self):
        return self.name

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _words(value):
        return [w for w in (value or '').replace(',', ' ').split() if w]

    def scope_list(self):
        scopes = self._words(self.scopes)
        if 'openid' not in scopes:
            scopes.insert(0, 'openid')
        return scopes

    def algorithm_list(self):
        return [a for a in self._words(self.allowed_algorithms) if a in ALLOWED_ALGORITHMS] or ['RS256']

    def mfa_acr_list(self):
        return self._words(self.mfa_acr_values)

    def mfa_amr_list(self):
        return self._words(self.mfa_amr_values)

    @property
    def issuer_normalized(self):
        return (self.issuer or '').strip()


class OIDCRoleMapping(models.Model):
    """A role key from the token -> a local role.

    staff:     "<alias>:<role_key>" makes an SSO-managed account MSP staff with
               this global role (client scope as set here).
    customer:  "<alias>:customer:<key>:<role_key>" gives a membership with this
               role in the customer mapped to <key> (OIDCCustomerMapping).
    """
    TARGET_STAFF, TARGET_CUSTOMER = 'staff', 'customer'
    TARGET_CHOICES = [(TARGET_STAFF, 'MSP staff global role'), (TARGET_CUSTOMER, 'Customer membership role')]
    SCOPE_CHOICES = [('all', 'All clients'), ('assigned', 'Clients with a technician access assignment')]

    provider = models.ForeignKey(OIDCProvider, on_delete=models.CASCADE, related_name='role_mappings')
    role_key = models.CharField(max_length=100, help_text='Role name after the "<alias>:" prefix, e.g. technician.')
    target = models.CharField(max_length=10, choices=TARGET_CHOICES, default=TARGET_STAFF)
    role_template = models.ForeignKey('accounts.RoleTemplate', on_delete=models.PROTECT, related_name='+')
    client_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='all',
                                    help_text='Staff only. Customer claims in the token can narrow it further, '
                                              'never widen it.')
    priority = models.PositiveIntegerField(default=100,
                                           help_text='Staff: when several staff roles match, the lowest wins.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'oidc_role_mappings'
        ordering = ['target', 'priority', 'role_key', 'pk']
        unique_together = [['provider', 'target', 'role_key']]

    def __str__(self):
        return f'{self.role_key} ({self.get_target_display()}) -> {self.role_template.name}'


class OIDCCustomerMapping(models.Model):
    """A customer key used in "<alias>:customer:<key>:<role>" -> a customer."""
    provider = models.ForeignKey(OIDCProvider, on_delete=models.CASCADE, related_name='customer_mappings')
    customer_key = models.CharField(max_length=100)
    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'oidc_customer_mappings'
        ordering = ['customer_key']
        unique_together = [['provider', 'customer_key'], ['provider', 'organization']]

    def __str__(self):
        return f'{self.customer_key} -> {self.organization}'


class OIDCIdentity(models.Model):
    """An OP account linked to a local user. The key is (issuer, sub)."""
    provider = models.ForeignKey(OIDCProvider, on_delete=models.CASCADE, related_name='identities')
    issuer = models.CharField(max_length=500)
    sub = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='oidc_identities')
    # True for accounts SSO created (JIT): the staff role, user type and
    # client scope follow the token. False (linked / pre-linked accounts):
    # the local role configuration is left alone.
    manages_staff_role = models.BooleanField(default=False)
    email_at_link = models.CharField(max_length=254, blank=True)
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')
    linked_at = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'oidc_identities'
        ordering = ['-linked_at']
        constraints = [
            models.UniqueConstraint(fields=['issuer', 'sub'], name='oidc_identity_issuer_sub_unique'),
            models.UniqueConstraint(fields=['provider', 'user'], name='oidc_identity_provider_user_unique'),
        ]

    def __str__(self):
        return f'{self.user} <- {self.sub} @ {self.issuer}'


class OIDCSession(models.Model):
    """Which Django session belongs to which OP session (sid), for
    back-channel logout."""
    provider = models.ForeignKey(OIDCProvider, on_delete=models.CASCADE, related_name='sessions')
    issuer = models.CharField(max_length=500)
    sid = models.CharField(max_length=255, blank=True, db_index=True)
    sub = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    session_key = models.CharField(max_length=40, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'oidc_sessions'
        ordering = ['-created_at']


class OIDCManagedMembership(models.Model):
    """Marks a membership as created and managed by an SSO mapping."""
    membership = models.OneToOneField('accounts.Membership', on_delete=models.CASCADE,
                                      related_name='oidc_managed')
    provider = models.ForeignKey(OIDCProvider, on_delete=models.CASCADE, related_name='managed_memberships')
    role_mapping = models.ForeignKey(OIDCRoleMapping, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'oidc_managed_memberships'


class OIDCManagedScope(models.Model):
    """The client-scope organizations SSO set on a managed staff profile, so
    a later sign-in can replace exactly those."""
    identity = models.OneToOneField(OIDCIdentity, on_delete=models.CASCADE, related_name='managed_scope')
    organization_ids = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'oidc_managed_scopes'


class ReplayRecord(models.Model):
    """A logout_token jti that has been used. Kept past the token's lifetime."""
    issuer = models.CharField(max_length=500)
    jti = models.CharField(max_length=255)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'oidc_replay_records'
        constraints = [models.UniqueConstraint(fields=['issuer', 'jti'], name='oidc_replay_issuer_jti_unique')]
