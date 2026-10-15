"""
LDAP / Active Directory sign-in backend.

Optional and off by default. Configuration lives in core.SystemSetting
(Settings -> Directory Services) and is re-read on every sign-in attempt, so
changes apply without a restart.

Built on django-auth-ldap (python-ldap). When those packages are missing the
backend stays importable and simply never authenticates anyone; the settings
page shows why.

Rules:
- Registered after ModelBackend, so local accounts (including a local
  superuser break-glass account) never depend on the directory being up.
- LDAP users get a local User with an unusable password, refreshed from the
  directory on each sign-in. A local account that was not created by LDAP is
  never taken over by a directory entry with the same name.
- A locally deactivated user cannot sign in through LDAP; directory-disabled
  accounts fail the bind.
- The bind password and user passwords are never logged or returned.
"""
import logging
import os
import re
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model

logger = logging.getLogger('accounts.ldap')

try:  # pragma: no cover - exercised implicitly by import
    import ldap
    import ldap.filter
    from django_auth_ldap.backend import LDAPBackend as _BaseLDAPBackend
    from django_auth_ldap.backend import _LDAPUser, populate_user
    from django_auth_ldap.config import LDAPSearch, LDAPSettings
    LDAP_AVAILABLE = True
    LDAP_IMPORT_ERROR = ''
except ImportError as exc:  # pragma: no cover - depends on the host
    ldap = None
    _BaseLDAPBackend = object
    _LDAPUser = None
    populate_user = None
    LDAPSearch = LDAPSettings = None
    LDAP_AVAILABLE = False
    LDAP_IMPORT_ERROR = str(exc)

LDAP_MISSING_MESSAGE = (
    'LDAP sign-in needs the optional python-ldap and django-auth-ldap packages, '
    'which are not installed on this server. Install them with '
    '"pip install -r requirements-optional.txt" (needs libldap2-dev and '
    'libsasl2-dev), then restart the app.'
)

GROUP_TYPES = ('active_directory', 'group_of_names', 'group_of_unique_names', 'posix')
# AD "LDAP_MATCHING_RULE_IN_CHAIN": membership through nested groups in one query.
_AD_IN_CHAIN = '1.2.840.113556.1.4.1941'
LDAP_TIMEOUT_SECONDS = 10
# Never read our settings from django.conf: everything comes from SystemSetting.
_SETTINGS_PREFIX = 'CLIENTST0R_LDAP_NOT_A_DJANGO_SETTING_'


@dataclass
class LDAPConfig:
    enabled: bool = False
    server_uris: list = field(default_factory=list)
    start_tls: bool = True
    verify_cert: bool = True
    ca_cert_file: str = ''
    bind_dn: str = ''
    bind_password: str = field(default='', repr=False)
    user_search_base: str = ''
    user_search_filter: str = '(sAMAccountName=%(user)s)'
    attr_username: str = 'sAMAccountName'
    attr_email: str = 'mail'
    attr_first_name: str = 'givenName'
    attr_last_name: str = 'sn'
    require_group: str = ''
    staff_group: str = ''
    group_type: str = 'active_directory'

    @staticmethod
    def parse_uris(value):
        return [u for u in re.split(r'[\s,]+', (value or '').strip()) if u]

    @property
    def uses_ldaps(self):
        return any(u.lower().startswith('ldaps://') for u in self.server_uris)

    @property
    def effective_start_tls(self):
        # StartTLS is meaningless (and fails) on an ldaps:// connection.
        return bool(self.start_tls) and not self.uses_ldaps

    @property
    def attrlist(self):
        attrs = [self.attr_username, self.attr_email, self.attr_first_name,
                 self.attr_last_name]
        return [a for a in dict.fromkeys(attrs) if a]

    def validate(self):
        """Return (errors, warnings) as lists of human-readable strings."""
        errors, warnings = [], []
        if not self.server_uris:
            errors.append('Server URI is required.')
        schemes = set()
        for uri in self.server_uris:
            low = uri.lower()
            if low.startswith('ldaps://'):
                schemes.add('ldaps')
            elif low.startswith('ldap://'):
                schemes.add('ldap')
            else:
                errors.append(f'Server URI "{uri}" must start with ldap:// or ldaps://.')
        if len(schemes) > 1:
            errors.append('Use either ldap:// or ldaps:// for every server URI, not a mix.')
        if schemes == {'ldap'} and not self.start_tls:
            warnings.append('ldap:// without StartTLS sends passwords unencrypted. '
                            'Turn on StartTLS or use ldaps://.')
        if not self.user_search_base.strip():
            errors.append('User Search Base is required.')
        flt = self.user_search_filter.strip()
        if '%(user)s' not in flt:
            errors.append('User Search Filter must contain %(user)s.')
        elif not (flt.startswith('(') and flt.endswith(')')):
            errors.append('User Search Filter must be wrapped in parentheses, '
                          'e.g. (sAMAccountName=%(user)s).')
        else:
            try:
                flt % {'user': 'x'}
            except (KeyError, ValueError, TypeError):
                errors.append('User Search Filter may only use the %(user)s placeholder '
                              '(write a literal % as %%).')
        if self.bind_dn and not self.bind_password:
            errors.append('A bind password is required when a Bind DN is set.')
        if self.bind_password and not self.bind_dn:
            errors.append('A Bind DN is required when a bind password is set.')
        if self.group_type not in GROUP_TYPES:
            errors.append('Unknown group type.')
        if self.ca_cert_file and not os.path.isfile(self.ca_cert_file):
            errors.append('CA certificate file was not found on the server.')
        if not self.verify_cert:
            warnings.append('TLS certificate verification is off; the connection can be intercepted.')
        return errors, warnings

    def connection_options(self):
        opts = {
            ldap.OPT_PROTOCOL_VERSION: 3,
            ldap.OPT_REFERRALS: 0,  # AD referrals break simple binds
            ldap.OPT_NETWORK_TIMEOUT: LDAP_TIMEOUT_SECONDS,
            ldap.OPT_TIMEOUT: LDAP_TIMEOUT_SECONDS,
            ldap.OPT_X_TLS_REQUIRE_CERT: (ldap.OPT_X_TLS_DEMAND if self.verify_cert
                                          else ldap.OPT_X_TLS_NEVER),
        }
        if self.ca_cert_file:
            opts[ldap.OPT_X_TLS_CACERTFILE] = self.ca_cert_file
        # Must be last: builds a fresh TLS context with the options above.
        opts[ldap.OPT_X_TLS_NEWCTX] = 0
        return opts

    def to_ldap_settings(self):
        attr_map = {}
        for django_field, attr in (('email', self.attr_email),
                                   ('first_name', self.attr_first_name),
                                   ('last_name', self.attr_last_name)):
            if attr:
                attr_map[django_field] = attr
        return LDAPSettings(_SETTINGS_PREFIX, {
            'SERVER_URI': ' '.join(self.server_uris),
            'START_TLS': self.effective_start_tls,
            'CONNECTION_OPTIONS': self.connection_options(),
            'BIND_DN': self.bind_dn,
            'BIND_PASSWORD': self.bind_password,
            'USER_SEARCH': LDAPSearch(self.user_search_base, ldap.SCOPE_SUBTREE,
                                      self.user_search_filter, self.attrlist),
            'USER_ATTRLIST': self.attrlist,
            'USER_ATTR_MAP': attr_map,
            'ALWAYS_UPDATE_USER': True,
            'CACHE_TIMEOUT': 0,
            'REQUIRE_GROUP': None,   # enforced in get_or_build_user (nested-aware)
            'DENY_GROUP': None,
            'MIRROR_GROUPS': None,
            'FIND_GROUP_PERMS': False,
            'NO_NEW_USERS': False,
            'PERMIT_EMPTY_PASSWORD': False,
        })


def config_from_settings(system_settings=None, overrides=None):
    """Build an LDAPConfig from SystemSetting, optionally overlaid with form values."""
    if system_settings is None:
        from core.models import SystemSetting
        system_settings = SystemSetting.get_settings()
    s = system_settings
    cfg = LDAPConfig(
        enabled=bool(s.ldap_enabled),
        server_uris=LDAPConfig.parse_uris(s.ldap_server_uri),
        start_tls=bool(s.ldap_start_tls),
        verify_cert=bool(getattr(s, 'ldap_verify_cert', True)),
        ca_cert_file=(getattr(s, 'ldap_ca_cert_file', '') or '').strip(),
        bind_dn=(s.ldap_bind_dn or '').strip(),
        bind_password=s.get_ldap_bind_password_decrypted() if s.ldap_bind_password else '',
        user_search_base=(s.ldap_user_search_base or '').strip(),
        user_search_filter=(s.ldap_user_search_filter or '').strip(),
        attr_username=(getattr(s, 'ldap_attr_username', '') or '').strip(),
        attr_email=(getattr(s, 'ldap_attr_email', '') or '').strip(),
        attr_first_name=(getattr(s, 'ldap_attr_first_name', '') or '').strip(),
        attr_last_name=(getattr(s, 'ldap_attr_last_name', '') or '').strip(),
        require_group=(s.ldap_require_group or '').strip(),
        staff_group=(getattr(s, 'ldap_staff_group', '') or '').strip(),
        group_type=(getattr(s, 'ldap_group_type', '') or 'active_directory').strip(),
    )
    for key, value in (overrides or {}).items():
        if key == 'server_uris' and isinstance(value, str):
            value = LDAPConfig.parse_uris(value)
        setattr(cfg, key, value)
    return cfg


def is_group_member(conn, cfg, group_dn, user_dn, uid=''):
    """Membership test against a bound connection. Missing groups count as 'no'."""
    try:
        if cfg.group_type == 'active_directory':
            flt = '(member:%s:=%s)' % (_AD_IN_CHAIN, ldap.filter.escape_filter_chars(user_dn))
            results = conn.search_s(group_dn, ldap.SCOPE_BASE, flt, ['1.1'])
            return any(dn for dn, _attrs in (results or []))
        if cfg.group_type == 'posix':
            return bool(uid) and bool(conn.compare_s(group_dn, 'memberUid', uid.encode()))
        attr = 'uniqueMember' if cfg.group_type == 'group_of_unique_names' else 'member'
        return bool(conn.compare_s(group_dn, attr, user_dn.encode()))
    except (ldap.NO_SUCH_OBJECT, ldap.NO_SUCH_ATTRIBUTE, ldap.UNDEFINED_TYPE,
            ldap.INAPPROPRIATE_MATCHING, ldap.INVALID_DN_SYNTAX):
        return False


def _first(attrs, name):
    if not attrs or not name:
        return ''
    values = attrs.get(name) or []
    value = values[0] if values else ''
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'replace')
    return (value or '').strip()


class ClientSt0rLDAPBackend(_BaseLDAPBackend):
    """Authenticates username/password against the configured directory."""

    _cfg = None

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            cfg = config_from_settings()
        except Exception as exc:
            logger.warning('LDAP sign-in skipped: could not load settings (%s)', type(exc).__name__)
            return None
        if not cfg.enabled:
            return None
        if not LDAP_AVAILABLE:
            logger.warning('LDAP sign-in is enabled but python-ldap/django-auth-ldap are not installed')
            return None
        errors, _warnings = cfg.validate()
        if errors:
            logger.warning('LDAP sign-in skipped: configuration is incomplete (%d problem(s))', len(errors))
            return None

        self._cfg = cfg
        self.settings = cfg.to_ldap_settings()
        try:
            return super().authenticate(request, username=username, password=password)
        except Exception as exc:
            # Never let a directory problem turn the login page into a 500.
            logger.warning('LDAP sign-in failed for %s: %s', username, type(exc).__name__)
            return None

    def authenticate_ldap_user(self, ldap_user, password):
        user = ldap_user.authenticate(password)
        if user is None:
            return None
        if not user.is_active:
            return None
        self._sync_profile(user, getattr(ldap_user, '_cs_is_staff', None))
        logger.info('LDAP sign-in succeeded for %s', user.get_username())
        return user

    def get_or_build_user(self, username, ldap_user):
        cfg = self._cfg
        model = self.get_user_model()
        attrs = ldap_user.attrs
        django_username = (_first(attrs, cfg.attr_username) or username).strip().lower()
        if not django_username or len(django_username) > 150:
            raise _LDAPUser.AuthenticationFailed('directory username is not usable locally')

        conn = ldap_user.connection  # re-bound as the service account
        uid = _first(attrs, cfg.attr_username) or username
        if cfg.require_group and not is_group_member(conn, cfg, cfg.require_group, ldap_user.dn, uid):
            raise _LDAPUser.AuthenticationFailed('user is not in the required group')
        ldap_user._cs_is_staff = (
            is_group_member(conn, cfg, cfg.staff_group, ldap_user.dn, uid)
            if cfg.staff_group else None
        )

        user = model.objects.filter(**{f'{model.USERNAME_FIELD}__iexact': django_username}).first()
        if user is not None:
            profile = getattr(user, 'profile', None)
            if profile is None or profile.auth_source != 'ldap':
                logger.warning('LDAP sign-in refused for %s: a local (non-LDAP) account '
                               'with that username already exists', django_username)
                raise _LDAPUser.AuthenticationFailed('local account exists')
            if not user.is_active:
                raise _LDAPUser.AuthenticationFailed('local account is deactivated')
            return user, False
        return model(**{model.USERNAME_FIELD: django_username}), True

    def _sync_profile(self, user, is_staff_member):
        from accounts.models import UserProfile, UserType
        profile, _ = UserProfile.objects.get_or_create(user=user)
        update = []
        if profile.auth_source != 'ldap':
            profile.auth_source = 'ldap'
            update.append('auth_source')
        if is_staff_member is not None:
            wanted = UserType.STAFF if is_staff_member else UserType.ORG_USER
            if profile.user_type != wanted:
                profile.user_type = wanted
                update.append('user_type')
        if update:
            profile.save(update_fields=update + ['updated_at'])

    # Sessions: an LDAP session ends when LDAP is turned off or the user is
    # deactivated locally.
    def get_user(self, user_id):
        try:
            from core.models import SystemSetting
            if not SystemSetting.get_settings().ldap_enabled:
                return None
        except Exception:
            return None
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            return None
        return user

    # Permissions come from ModelBackend / the app's own RBAC, not LDAP groups.
    def has_perm(self, user, perm, obj=None):
        return False

    def has_module_perms(self, user, app_label):
        return False

    def get_all_permissions(self, user, obj=None):
        return set()

    def get_group_permissions(self, user, obj=None):
        return set()


if LDAP_AVAILABLE:
    def _trim_populated_fields(sender, user=None, ldap_user=None, **kwargs):
        for name in ('first_name', 'last_name', 'email'):
            value = getattr(user, name, None)
            if isinstance(value, str):
                limit = user._meta.get_field(name).max_length or 254
                setattr(user, name, value.strip()[:limit])

    populate_user.connect(_trim_populated_fields, sender=ClientSt0rLDAPBackend,
                          dispatch_uid='clientst0r_ldap_trim_fields')


def _scrub(text, secret):
    text = str(text or '')
    if secret:
        text = text.replace(secret, '***')
    return text[:300]


def _describe_ldap_error(exc, secret=''):
    if isinstance(exc, ldap.SERVER_DOWN):
        return 'Could not reach the LDAP server (check the URI, port, firewall and TLS settings).'
    if isinstance(exc, ldap.INVALID_CREDENTIALS):
        return 'The server rejected the Bind DN or bind password.'
    if isinstance(exc, ldap.CONNECT_ERROR):
        return 'Could not establish a secure connection (StartTLS / certificate problem).'
    if isinstance(exc, ldap.TIMEOUT):
        return 'The LDAP server did not answer in time.'
    detail = exc.args[0] if exc.args else {}
    if isinstance(detail, dict):
        parts = [detail.get('desc', ''), detail.get('info', '')]
        msg = ' - '.join(p for p in parts if p)
    else:
        msg = str(detail)
    return _scrub(f'{type(exc).__name__}: {msg}', secret)


def check_ldap_connection(cfg, username=''):
    """
    Connect, bind as the service account and optionally look up `username`.
    Never touches the user's password and never returns the bind password.
    Returns {'ok': bool, 'message': str, 'steps': [str], 'warnings': [str]}.
    """
    result = {'ok': False, 'message': '', 'steps': [], 'warnings': []}
    if not LDAP_AVAILABLE:
        result['message'] = LDAP_MISSING_MESSAGE
        return result
    errors, warnings = cfg.validate()
    result['warnings'] = warnings
    if errors:
        result['message'] = 'Fix these settings first: ' + ' '.join(errors)
        return result

    secret = cfg.bind_password
    conn = None
    try:
        conn = ldap.initialize(' '.join(cfg.server_uris), bytes_mode=False)
        for opt, value in cfg.connection_options().items():
            conn.set_option(opt, value)
        if cfg.effective_start_tls:
            conn.start_tls_s()
            result['steps'].append('StartTLS negotiated.')
        conn.simple_bind_s(cfg.bind_dn, cfg.bind_password)
        result['steps'].append(
            f'Bound as {cfg.bind_dn}.' if cfg.bind_dn else 'Bound anonymously.')

        username = (username or '').strip()
        if not username:
            result['ok'] = True
            result['message'] = 'Connected and bound successfully. Enter a username to test a user lookup too.'
            return result

        flt = cfg.user_search_filter % {'user': ldap.filter.escape_filter_chars(username)}
        found = [r for r in (conn.search_s(cfg.user_search_base, ldap.SCOPE_SUBTREE, flt,
                                           cfg.attrlist) or []) if r[0]]
        if not found:
            result['message'] = f'Bound successfully, but no directory entry matched "{username}".'
            return result
        if len(found) > 1:
            result['message'] = (f'"{username}" matched {len(found)} entries; the search filter '
                                 'must match exactly one user.')
            return result
        user_dn, raw_attrs = found[0]
        attrs = ldap.cidict.cidict(raw_attrs or {})
        result['steps'].append(f'Found {user_dn}.')
        mapped = {
            'username': _first(attrs, cfg.attr_username) or username.lower(),
            'email': _first(attrs, cfg.attr_email),
            'first name': _first(attrs, cfg.attr_first_name),
            'last name': _first(attrs, cfg.attr_last_name),
        }
        result['steps'].append('Mapped: ' + ', '.join(
            f'{k} = {v or "(empty)"}' for k, v in mapped.items()))
        uid = _first(attrs, cfg.attr_username) or username
        ok = True
        if cfg.require_group:
            member = is_group_member(conn, cfg, cfg.require_group, user_dn, uid)
            result['steps'].append('Required group: ' + ('member.' if member else 'NOT a member - sign-in would be refused.'))
            ok = ok and member
        if cfg.staff_group:
            staff = is_group_member(conn, cfg, cfg.staff_group, user_dn, uid)
            result['steps'].append('Staff group: ' + ('member - signs in as MSP staff.' if staff
                                                     else 'not a member - signs in as an organization user.'))
        result['ok'] = ok
        result['message'] = ('Lookup succeeded.' if ok
                             else 'Lookup succeeded, but this user would not be allowed to sign in.')
        return result
    except ldap.LDAPError as exc:
        result['message'] = _describe_ldap_error(exc, secret)
        return result
    except Exception as exc:
        result['message'] = _scrub(f'Unexpected error: {type(exc).__name__}', secret)
        return result
    finally:
        if conn is not None:
            try:
                conn.unbind_s()
            except Exception:
                pass
