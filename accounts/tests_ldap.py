"""
LDAP / Active Directory sign-in (accounts.ldap_backend).

The directory is faked at the python-ldap connection layer: `ldap.initialize`
is patched to return an in-memory LDAPObject stand-in, so django-auth-ldap and
our backend run their real code paths against it.
"""
import io
import logging
import re
from unittest import mock

import ldap
from django.conf import settings as django_settings
from django.contrib.auth import authenticate, get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import UserType
from core.models import SystemSetting

User = get_user_model()

BIND_DN = 'cn=svc-clientst0r,ou=service,dc=example,dc=com'
BIND_PASSWORD = 'svc-Bind-S3cret-xyz!'
ALICE_PASSWORD = 'alice-Dir-Pw-111'
BOB_PASSWORD = 'bob-Dir-Pw-222'
CAROL_PASSWORD = 'carol-Dir-Pw-333'
APP_USERS = 'cn=app users,ou=groups,dc=example,dc=com'
NESTED = 'cn=nested team,ou=groups,dc=example,dc=com'
STAFF = 'cn=msp techs,ou=groups,dc=example,dc=com'
ALICE_DN = 'cn=alice anderson,ou=users,dc=example,dc=com'
BOB_DN = 'cn=bob brown,ou=users,dc=example,dc=com'
CAROL_DN = 'cn=carol chen,ou=users,dc=example,dc=com'
IN_CHAIN = '1.2.840.113556.1.4.1941'

MIDDLEWARE_NO_AXES = [m for m in django_settings.MIDDLEWARE if 'AxesMiddleware' not in m]
TEST_MIDDLEWARE = [m for m in MIDDLEWARE_NO_AXES if 'Enforce2FAMiddleware' not in m]


# ---------------------------------------------------------------------------
# Fake directory
# ---------------------------------------------------------------------------

def _unescape(value):
    return re.sub(r'\\([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), value)


def _parse_filter(s, i=0):
    assert s[i] == '(', s
    i += 1
    if s[i] in '&|':
        op, i, kids = s[i], i + 1, []
        while s[i] == '(':
            node, i = _parse_filter(s, i)
            kids.append(node)
        assert s[i] == ')'
        return (op, kids), i + 1
    if s[i] == '!':
        node, i = _parse_filter(s, i + 1)
        assert s[i] == ')'
        return ('!', node), i + 1
    j = s.index(')', i)
    attr, value = s[i:j].split('=', 1)
    return ('eq', attr, _unescape(value)), j + 1


class FakeDirectory:
    def __init__(self):
        self.down = False
        self.passwords = {}
        self.entries = {}
        self.initialize_calls = 0
        self.options = {}

    def add(self, dn, password=None, **attrs):
        self.entries[dn.lower()] = {k: (v if isinstance(v, list) else [v]) for k, v in attrs.items()}
        if password:
            self.passwords[dn.lower()] = password

    def _values(self, dn, attr):
        for k, v in self.entries.get(dn.lower(), {}).items():
            if k.lower() == attr.lower():
                return v
        return []

    def _member_in_chain(self, group_dn, member_dn, seen=None):
        seen = seen or set()
        if group_dn.lower() in seen:
            return False
        seen.add(group_dn.lower())
        for m in self._values(group_dn, 'member'):
            if m.lower() == member_dn.lower():
                return True
            if m.lower() in self.entries and self._member_in_chain(m, member_dn, seen):
                return True
        return False

    def matches(self, dn, node):
        kind = node[0]
        if kind == '&':
            return all(self.matches(dn, k) for k in node[1])
        if kind == '|':
            return any(self.matches(dn, k) for k in node[1])
        if kind == '!':
            return not self.matches(dn, node[1])
        _, attr, value = node
        if attr.lower() == f'member:{IN_CHAIN}:':
            return self._member_in_chain(dn, value)
        values = self._values(dn, attr)
        if value == '*':
            return bool(values)
        return any(v.lower() == value.lower() for v in values)


class FakeLDAPObject:
    def __init__(self, directory, uri):
        self.d = directory
        self.uri = uri
        self.bound_dn = None

    def set_option(self, opt, value):
        self.d.options[opt] = value

    def start_tls_s(self):
        if self.d.down:
            raise ldap.SERVER_DOWN({'desc': "Can't contact LDAP server"})

    def simple_bind_s(self, who='', cred=''):
        if self.d.down:
            raise ldap.SERVER_DOWN({'desc': "Can't contact LDAP server"})
        if not who:
            self.bound_dn = ''
            return
        if self.d.passwords.get(who.lower()) != cred or not cred:
            raise ldap.INVALID_CREDENTIALS({'desc': 'Invalid credentials',
                                            'info': '80090308: LdapErr: data 52e'})
        self.bound_dn = who.lower()

    def search_s(self, base, scope, filterstr='(objectClass=*)', attrlist=None, attrsonly=0):
        if self.d.down:
            raise ldap.SERVER_DOWN({'desc': "Can't contact LDAP server"})
        node, _ = _parse_filter(filterstr)
        base = base.lower()
        out = []
        for dn, attrs in self.d.entries.items():
            if scope == ldap.SCOPE_BASE and dn != base:
                continue
            if scope != ldap.SCOPE_BASE and not (dn == base or dn.endswith(',' + base)):
                continue
            if not self.d.matches(dn, node):
                continue
            wanted = None if attrlist is None else {a.lower() for a in attrlist}
            out.append((dn, {k: [v.encode() for v in vals] for k, vals in attrs.items()
                             if wanted is None or k.lower() in wanted}))
        return out

    def compare_s(self, dn, attr, value):
        if dn.lower() not in self.d.entries:
            raise ldap.NO_SUCH_OBJECT({'desc': 'No such object'})
        value = value.decode() if isinstance(value, bytes) else value
        return any(v.lower() == value.lower() for v in self.d._values(dn, attr))

    def unbind_s(self):
        self.bound_dn = None


def build_directory():
    d = FakeDirectory()
    d.add(BIND_DN, password=BIND_PASSWORD, cn='svc-clientst0r')
    d.add(ALICE_DN, password=ALICE_PASSWORD, sAMAccountName='alice', mail='alice@example.com',
          givenName='Alice', sn='Anderson')
    d.add(BOB_DN, password=BOB_PASSWORD, sAMAccountName='bob', mail='bob@example.com',
          givenName='Bob', sn='Brown')
    d.add(CAROL_DN, password=CAROL_PASSWORD, sAMAccountName='carol', mail='carol@example.com',
          givenName='Carol', sn='Chen')
    d.add(NESTED, cn='nested team', member=[CAROL_DN])
    d.add(APP_USERS, cn='app users', member=[ALICE_DN, NESTED])
    d.add(STAFF, cn='msp techs', member=[ALICE_DN])
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class LDAPTestBase(TestCase):
    enable = True

    def setUp(self):
        self.directory = build_directory()
        patcher = mock.patch('ldap.initialize', side_effect=self._initialize)
        self.initialize = patcher.start()
        self.addCleanup(patcher.stop)
        s = SystemSetting.get_settings()
        s.ldap_enabled = self.enable
        s.ldap_server_uri = 'ldaps://dc1.example.com ldaps://dc2.example.com'
        s.ldap_start_tls = True
        s.ldap_bind_dn = BIND_DN
        s.ldap_bind_password = BIND_PASSWORD  # EncryptedTextField encrypts on save
        s.ldap_user_search_base = 'ou=users,dc=example,dc=com'
        s.ldap_user_search_filter = '(sAMAccountName=%(user)s)'
        s.ldap_group_type = 'active_directory'
        s.save()
        self.factory = RequestFactory()

    def _initialize(self, uri, **kwargs):
        self.directory.initialize_calls += 1
        return FakeLDAPObject(self.directory, uri)

    def configure(self, **fields):
        s = SystemSetting.get_settings()
        for k, v in fields.items():
            setattr(s, k, v)
        s.save()

    def auth(self, username, password):
        request = self.factory.post('/account/login/')
        return authenticate(request, username=username, password=password)


class LDAPDisabledTests(LDAPTestBase):
    enable = False

    def test_disabled_never_consults_ldap(self):
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))
        self.assertEqual(self.initialize.call_count, 0)
        self.assertFalse(User.objects.filter(username='alice').exists())

    def test_local_login_unaffected_when_disabled(self):
        User.objects.create_user('localuser', password='local-Pw-12345')
        self.assertIsNotNone(self.auth('localuser', 'local-Pw-12345'))
        self.assertEqual(self.initialize.call_count, 0)


class LDAPSignInTests(LDAPTestBase):

    def test_valid_credentials_create_user_with_mapped_attributes(self):
        user = self.auth('Alice', ALICE_PASSWORD)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, 'alice')
        self.assertEqual(user.email, 'alice@example.com')
        self.assertEqual(user.first_name, 'Alice')
        self.assertEqual(user.last_name, 'Anderson')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        user.refresh_from_db()
        self.assertEqual(user.profile.auth_source, 'ldap')
        self.assertEqual(user.profile.user_type, UserType.ORG_USER)
        self.assertEqual(user.backend, 'accounts.ldap_backend.ClientSt0rLDAPBackend')
        # ldaps:// URIs -> StartTLS is not attempted; cert verification on.
        self.assertEqual(self.directory.options[ldap.OPT_X_TLS_REQUIRE_CERT], ldap.OPT_X_TLS_DEMAND)

    def test_attributes_refresh_on_next_sign_in(self):
        self.auth('alice', ALICE_PASSWORD)
        self.directory.entries[ALICE_DN.lower()]['mail'] = ['alice.new@example.com']
        user = self.auth('alice', ALICE_PASSWORD)
        self.assertEqual(user.email, 'alice.new@example.com')
        self.assertEqual(User.objects.filter(username='alice').count(), 1)

    def test_settings_changes_apply_without_restart(self):
        self.assertIsNotNone(self.auth('alice', ALICE_PASSWORD))
        self.configure(ldap_enabled=False)
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))

    def test_wrong_password_fails(self):
        self.assertIsNone(self.auth('alice', 'nope-wrong'))
        self.assertFalse(User.objects.filter(username='alice').exists())

    def test_unknown_user_fails(self):
        self.assertIsNone(self.auth('mallory', 'whatever-123'))

    def test_filter_injection_is_escaped(self):
        self.assertIsNone(self.auth('*)(sAMAccountName=*', ALICE_PASSWORD))

    @override_settings(MIDDLEWARE=MIDDLEWARE_NO_AXES, SECURE_SSL_REDIRECT=False)
    def test_wrong_password_counts_toward_axes_lockout(self):
        from axes.models import AccessAttempt
        c = Client()
        resp = c.post(reverse('two_factor:login'), {
            'login_view-current_step': 'auth',
            'auth-username': 'alice',
            'auth-password': 'nope-wrong',
        })
        self.assertEqual(resp.status_code, 200)
        attempt = AccessAttempt.objects.get(username='alice')
        self.assertEqual(attempt.failures_since_start, 1)
        self.assertNotIn('_auth_user_id', c.session)

    @override_settings(AXES_FAILURE_LIMIT=2)
    def test_axes_lockout_blocks_ldap_even_with_right_password(self):
        self.assertIsNone(self.auth('alice', 'wrong-1'))
        self.assertIsNone(self.auth('alice', 'wrong-2'))
        calls = self.initialize.call_count
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))
        self.assertEqual(self.initialize.call_count, calls)  # locked out before LDAP

    def test_required_group_missing_is_denied(self):
        self.configure(ldap_require_group=APP_USERS)
        self.assertIsNone(self.auth('bob', BOB_PASSWORD))
        self.assertFalse(User.objects.filter(username='bob').exists())
        self.assertIsNotNone(self.auth('alice', ALICE_PASSWORD))

    def test_required_group_nested_membership_allowed(self):
        self.configure(ldap_require_group=APP_USERS)
        self.assertIsNotNone(self.auth('carol', CAROL_PASSWORD))

    def test_required_group_with_group_of_names_type(self):
        self.configure(ldap_require_group=APP_USERS, ldap_group_type='group_of_names')
        self.assertIsNotNone(self.auth('alice', ALICE_PASSWORD))
        self.assertIsNone(self.auth('bob', BOB_PASSWORD))

    def test_staff_group_sets_user_type_staff(self):
        self.configure(ldap_staff_group=STAFF)
        alice = self.auth('alice', ALICE_PASSWORD)
        bob = self.auth('bob', BOB_PASSWORD)
        self.assertEqual(User.objects.get(pk=alice.pk).profile.user_type, UserType.STAFF)
        self.assertEqual(User.objects.get(pk=bob.pk).profile.user_type, UserType.ORG_USER)

    def test_removed_from_staff_group_is_demoted(self):
        self.configure(ldap_staff_group=STAFF)
        self.auth('alice', ALICE_PASSWORD)
        self.directory.entries[STAFF]['member'] = []
        alice = self.auth('alice', ALICE_PASSWORD)
        self.assertEqual(User.objects.get(pk=alice.pk).profile.user_type, UserType.ORG_USER)

    def test_deactivated_ldap_user_cannot_sign_in(self):
        user = self.auth('alice', ALICE_PASSWORD)
        User.objects.filter(pk=user.pk).update(is_active=False)
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))

    def test_local_account_is_not_taken_over(self):
        local = User.objects.create_user('alice', password='local-Alice-Pw-1')
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))
        local.refresh_from_db()
        self.assertEqual(local.profile.auth_source, 'local')
        self.assertTrue(local.has_usable_password())
        # The local password still works through ModelBackend.
        self.assertEqual(self.auth('alice', 'local-Alice-Pw-1').pk, local.pk)

    def test_ldap_unreachable_superuser_still_logs_in(self):
        admin = User.objects.create_superuser('breakglass', 'bg@example.com', 'Break-Glass-Pw-99')
        self.directory.down = True
        self.assertEqual(self.auth('breakglass', 'Break-Glass-Pw-99').pk, admin.pk)
        # LDAP user: clean failure, no exception.
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))

    @override_settings(MIDDLEWARE=MIDDLEWARE_NO_AXES, SECURE_SSL_REDIRECT=False)
    def test_ldap_unreachable_login_page_does_not_error(self):
        self.directory.down = True
        resp = Client().post(reverse('two_factor:login'), {
            'login_view-current_step': 'auth',
            'auth-username': 'alice',
            'auth-password': ALICE_PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)

    def test_incomplete_config_skips_ldap(self):
        self.configure(ldap_user_search_base='')
        self.assertIsNone(self.auth('alice', ALICE_PASSWORD))
        self.assertEqual(self.initialize.call_count, 0)

    def test_library_missing_path_is_a_clean_noop(self):
        with mock.patch('accounts.ldap_backend.LDAP_AVAILABLE', False):
            self.assertIsNone(self.auth('alice', ALICE_PASSWORD))
        self.assertEqual(self.initialize.call_count, 0)

    def test_session_ends_when_ldap_disabled(self):
        from accounts.ldap_backend import ClientSt0rLDAPBackend
        user = self.auth('alice', ALICE_PASSWORD)
        self.assertEqual(ClientSt0rLDAPBackend().get_user(user.pk).pk, user.pk)
        self.configure(ldap_enabled=False)
        self.assertIsNone(ClientSt0rLDAPBackend().get_user(user.pk))

    def test_passwords_never_logged(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        loggers = [logging.getLogger(n) for n in ('django_auth_ldap', 'accounts.ldap', 'accounts', '')]
        old_levels = [lg.level for lg in loggers]
        for lg in loggers:
            lg.addHandler(handler)
            lg.setLevel(logging.DEBUG)
        try:
            self.configure(ldap_require_group=APP_USERS, ldap_staff_group=STAFF)
            self.auth('alice', ALICE_PASSWORD)
            self.auth('alice', 'Wrong-Pw-Leak-Check')
            self.auth('bob', BOB_PASSWORD)
            self.directory.down = True
            self.auth('alice', ALICE_PASSWORD)
        finally:
            for lg, lvl in zip(loggers, old_levels):
                lg.removeHandler(handler)
                lg.setLevel(lvl)
        output = stream.getvalue()
        self.assertIn('alice', output)  # sanity: logging was captured
        for secret in (BIND_PASSWORD, ALICE_PASSWORD, BOB_PASSWORD, 'Wrong-Pw-Leak-Check'):
            self.assertNotIn(secret, output)


@override_settings(MIDDLEWARE=MIDDLEWARE_NO_AXES, SECURE_SSL_REDIRECT=False, REQUIRE_2FA=True)
class LDAPTwoFactorTests(LDAPTestBase):

    def _login(self, client, username, password):
        return client.post(reverse('two_factor:login'), {
            'login_view-current_step': 'auth',
            'auth-username': username,
            'auth-password': password,
        })

    def test_ldap_user_without_device_is_forced_to_2fa_setup(self):
        c = Client()
        resp = self._login(c, 'alice', ALICE_PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', c.session)
        resp = c.get('/core/secure-notes/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('two_factor:setup'))

    def test_ldap_user_with_device_must_pass_token_step(self):
        self.auth('alice', ALICE_PASSWORD)
        alice = User.objects.get(username='alice')
        TOTPDevice.objects.create(user=alice, name='default', confirmed=True)
        c = Client()
        resp = self._login(c, 'alice', ALICE_PASSWORD)
        self.assertEqual(resp.status_code, 200, (resp.get("Location"), dict(c.session)))  # token step rendered
        self.assertContains(resp, 'token')
        self.assertNotIn('_auth_user_id', c.session)

    def test_ldap_password_only_session_with_device_is_ended(self):
        # Same rule as local users: a device that never got verified this
        # session means the session is ended by Enforce2FAMiddleware.
        self.auth('alice', ALICE_PASSWORD)
        alice = User.objects.get(username='alice')
        TOTPDevice.objects.create(user=alice, name='phone', confirmed=True)
        c = Client()
        self._login(c, 'alice', ALICE_PASSWORD)
        resp = c.get('/core/secure-notes/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/account/login/'))
        self.assertNotIn('_auth_user_id', c.session)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class LDAPSettingsPageTests(LDAPTestBase):
    enable = False

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root-admin', 'r@example.com', 'Root-Admin-Pw-1')
        self.client = Client()
        self.client.force_login(self.admin)

    def _form(self, **overrides):
        data = {
            'ldap_enabled': 'on',
            'ldap_server_uri': 'ldaps://dc1.example.com',
            'ldap_bind_dn': BIND_DN,
            'ldap_bind_password': '',
            'ldap_user_search_base': 'ou=users,dc=example,dc=com',
            'ldap_user_search_filter': '(sAMAccountName=%(user)s)',
            'ldap_require_group': '',
            'ldap_staff_group': STAFF,
            'ldap_group_type': 'active_directory',
            'ldap_verify_cert': 'on',
            'ldap_attr_username': 'sAMAccountName',
            'ldap_attr_email': 'mail',
            'ldap_attr_first_name': 'givenName',
            'ldap_attr_last_name': 'sn',
            'ldap_ca_cert_file': '',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def test_page_renders_without_secret(self):
        resp = self.client.get(reverse('core:settings_directory'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test connection')
        self.assertNotContains(resp, BIND_PASSWORD)
        self.assertNotContains(resp, SystemSetting.get_settings().ldap_bind_password)

    def test_enable_with_valid_settings(self):
        resp = self.client.post(reverse('core:settings_directory'), self._form())
        self.assertEqual(resp.status_code, 302)
        s = SystemSetting.get_settings()
        self.assertTrue(s.ldap_enabled)
        self.assertEqual(s.ldap_staff_group, STAFF)
        self.assertEqual(s.get_ldap_bind_password_decrypted(), BIND_PASSWORD)  # kept

    def test_enable_with_missing_fields_stays_off(self):
        resp = self.client.post(reverse('core:settings_directory'),
                                self._form(ldap_user_search_base='', ldap_user_search_filter='(uid=x)'),
                                follow=True)
        s = SystemSetting.get_settings()
        self.assertFalse(s.ldap_enabled)
        self.assertContains(resp, 'User Search Base is required')
        self.assertContains(resp, '%(user)s')

    def test_new_bind_password_is_stored_encrypted(self):
        self.client.post(reverse('core:settings_directory'),
                         self._form(ldap_bind_password='Another-Secret-55'))
        s = SystemSetting.get_settings()
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(f'SELECT ldap_bind_password FROM {SystemSetting._meta.db_table} WHERE id = %s', [s.pk])
            raw = cur.fetchone()[0]
        self.assertNotIn('Another-Secret-55', raw)
        self.assertEqual(s.get_ldap_bind_password_decrypted(), 'Another-Secret-55')

    def test_test_connection_success_with_user_lookup(self):
        resp = self.client.post(reverse('core:settings_directory_ldap_test'),
                                self._form(test_username='alice'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'], data)
        joined = ' '.join(data['steps'])
        self.assertIn(ALICE_DN, joined)
        self.assertIn('alice@example.com', joined)
        self.assertIn('MSP staff', joined)
        self.assertNotIn(BIND_PASSWORD, resp.content.decode())
        # Testing never changes stored settings.
        self.assertFalse(SystemSetting.get_settings().ldap_enabled)

    def test_test_connection_bad_bind_password(self):
        resp = self.client.post(reverse('core:settings_directory_ldap_test'),
                                self._form(ldap_bind_password='Typed-Wrong-Secret-9'))
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertIn('rejected', data['message'])
        body = resp.content.decode()
        self.assertNotIn('Typed-Wrong-Secret-9', body)
        self.assertNotIn(BIND_PASSWORD, body)
        self.assertEqual(SystemSetting.get_settings().get_ldap_bind_password_decrypted(), BIND_PASSWORD)

    def test_test_connection_unreachable(self):
        self.directory.down = True
        data = self.client.post(reverse('core:settings_directory_ldap_test'), self._form()).json()
        self.assertFalse(data['ok'])
        self.assertIn('Could not reach', data['message'])

    def test_test_connection_validation_errors(self):
        data = self.client.post(reverse('core:settings_directory_ldap_test'),
                                self._form(ldap_server_uri='http://dc')).json()
        self.assertFalse(data['ok'])
        self.assertIn('ldap://', data['message'])
        self.assertEqual(self.initialize.call_count, 0)

    def test_test_connection_requires_superuser(self):
        user = User.objects.create_user('plain', password='Plain-User-Pw-1')
        c = Client()
        c.force_login(user)
        resp = c.post(reverse('core:settings_directory_ldap_test'), self._form())
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(self.initialize.call_count, 0)

    def test_library_missing_message_shown(self):
        with mock.patch('accounts.ldap_backend.LDAP_AVAILABLE', False):
            resp = self.client.get(reverse('core:settings_directory'))
            self.assertContains(resp, 'python-ldap')
            resp = self.client.post(reverse('core:settings_directory'), self._form(), follow=True)
        self.assertFalse(SystemSetting.get_settings().ldap_enabled)
        self.assertContains(resp, 'not installed')
