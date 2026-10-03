"""Offline tests for vault capability checks and trusted proxy resolution.

Run: python -m unittest discover -s security_tests -v
Uses Django responses and the actual helpers; database records are test doubles.
Handler tests load the function AST without decorators to isolate authorization
from the application's unrelated integrations and middleware.
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY='offline-test-only', DEFAULT_CHARSET='utf-8',
                       TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '::1/128'])
from django.http import JsonResponse
from django.test import override_settings
from rest_framework import status
from rest_framework.response import Response
from accounts.permission_utils import user_has_org_perm
from vault.permissions import can_access_password
from core.client_ip import get_client_ip

ROOT = Path(__file__).resolve().parents[1]


def user(*memberships, **kwargs):
    manager = Mock()
    manager.filter.return_value.select_related.return_value = list(memberships)
    fields = dict(pk=1, username='test', is_authenticated=True, is_active=True,
                  is_superuser=False, profile=None, memberships=manager)
    fields.update(kwargs)
    return NS(**fields)


def membership(org, **permissions):
    return NS(organization_id=org, get_permissions=lambda: NS(**permissions))


def load_handler(path, name, globals_):
    node = next(n for n in ast.parse((ROOT / path).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    scope = {'__name__': 'vault.views', **globals_}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope[name]


class VaultPermissions(unittest.TestCase):
    def setUp(self):
        self.descendants = patch('core.utils.descendant_org_ids', side_effect=lambda org: {org, org + 100})
        self.descendants.start()
        self.addCleanup(self.descendants.stop)
        self.password = NS(pk=3, is_personal=False, organization_id=10)

    def test_readonly_cannot_reveal(self):
        reader = user(membership(10, vault_view_password=False))
        self.assertFalse(can_access_password(reader, self.password))

    def test_other_org_permission_cannot_authorize_target(self):
        mixed = user(membership(10, vault_edit=False), membership(20, vault_edit=True))
        self.assertFalse(can_access_password(mixed, self.password, 'vault_edit'))

    def test_member_and_parent_permissions_work(self):
        member = user(membership(10, vault_view_password=True))
        self.assertTrue(can_access_password(member, self.password))
        self.password.organization_id = 110
        self.assertTrue(can_access_password(member, self.password))

    def test_personal_secret_requires_owner_even_for_admin(self):
        self.password.is_personal = True
        self.password.personal_owner_id = 1
        self.assertTrue(can_access_password(user(), self.password))
        self.assertFalse(can_access_password(user(pk=2, is_superuser=True), self.password))

    def test_disabled_admin_is_denied(self):
        self.assertFalse(can_access_password(user(is_superuser=True, is_active=False), self.password))

    def test_staff_status_does_not_bypass_global_vault_role(self):
        profile = NS(is_staff_user=lambda: True,
                     get_global_permissions=lambda: NS(vault_view_password=False))
        self.assertFalse(can_access_password(user(profile=profile), self.password))
        profile.get_global_permissions = lambda: NS(vault_view_password=True)
        self.assertTrue(can_access_password(user(profile=profile), self.password))

    def test_all_browser_secret_paths_deny_readonly_before_decryption(self):
        request = NS(user=user(membership(10, vault_view_password=False)), META={}, method='POST')
        globals_ = dict(can_access_password=can_access_password, JsonResponse=JsonResponse,
                        get_request_organization=lambda r: 10, Password=object,
                        get_org_object_or_404=lambda *a, **k: self.password)
        for name in ['password_reveal', 'password_request_reveal', 'password_break_glass',
                     'password_test_breach', 'generate_otp_api', 'password_qrcode']:
            with self.subTest(name=name):
                response = load_handler('vault/views.py', name, globals_)(request, 3)
                self.assertEqual(403, response.status_code)

    def mobile_reveal(self, permitted, decision=None, error=None):
        password = NS(**vars(self.password), requires_reveal_approval=False,
                      get_password=Mock(return_value='synthetic-secret'))
        manager = Mock()
        manager.select_related.return_value.get.return_value = password
        model = NS(objects=manager, DoesNotExist=LookupError)
        request = NS(user=user(membership(10, vault_view_password=permitted)), META={})
        evaluate = Mock(return_value=decision, side_effect=error)
        modules = {'vault.models': NS(Password=model), 'audit.models': NS(AuditLog=Mock()),
                   'vault.access_rules': NS(evaluate=evaluate)}
        handler = load_handler('api_mobile/views_vault.py', 'vault_reveal_view',
                    dict(can_access_password=can_access_password, accessible_org_ids=lambda u: {10},
                         Response=Response, status=status))
        with patch.dict('sys.modules', modules):
            response = handler(request, 3)
        password.get_password.assert_not_called()
        return response

    def test_mobile_denies_readonly(self):
        self.assertEqual(403, self.mobile_reveal(False).status_code)

    def test_otp_and_qr_honor_vault_policy(self):
        request = NS(user=user(membership(10, vault_view_password=True)), META={}, method='GET')
        for name in ['generate_otp_api', 'password_qrcode']:
            for decision, code in [(Mock(return_value={'allowed': False}), 403),
                                   (Mock(side_effect=RuntimeError('policy unavailable')), 503)]:
                with self.subTest(name=name, code=code):
                    globals_ = dict(can_access_password=can_access_password, JsonResponse=JsonResponse,
                                    get_request_organization=lambda r: 10, Password=object,
                                    get_org_object_or_404=lambda *a, **k: self.password,
                                    _evaluate_vault_access=decision)
                    response = load_handler('vault/views.py', name, globals_)(request, 3)
                    self.assertEqual(code, response.status_code)

    def test_policy_failure_does_not_release_secret(self):
        self.assertEqual(503, self.mobile_reveal(True, error=RuntimeError('policy unavailable')).status_code)

    def test_invalid_policy_result_does_not_release_secret(self):
        self.assertEqual(403, self.mobile_reveal(True, decision={}).status_code)


class ProxyResolution(unittest.TestCase):
    def resolve(self, peer, xff='', real=''):
        return get_client_ip(NS(META={'REMOTE_ADDR': peer, 'HTTP_X_FORWARDED_FOR': xff,
                                     'HTTP_X_REAL_IP': real}))

    def test_untrusted_sender_cannot_supply_address(self):
        self.assertEqual('8.8.8.8', self.resolve('8.8.8.8', '127.0.0.1', '127.0.0.1'))

    def test_forged_prefix_is_ignored(self):
        self.assertEqual('8.8.8.8', self.resolve('127.0.0.1', '127.0.0.1, 8.8.8.8'))

    def test_malformed_chain_fails_closed(self):
        self.assertIsNone(self.resolve('127.0.0.1', 'malformed, 8.8.8.8'))
        self.assertIsNone(self.resolve('invalid'))

    @override_settings(TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '10.0.0.0/24'])
    def test_explicit_multiple_proxies(self):
        self.assertEqual('8.8.4.4', self.resolve('127.0.0.1', '8.8.4.4, 10.0.0.5'))

    def test_direct_ipv6_is_preserved(self):
        self.assertEqual('2001:4860:4860::8888', self.resolve('2001:4860:4860::8888', '::1'))


if __name__ == '__main__':
    unittest.main()
