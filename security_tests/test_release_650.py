"""v3.17.650 security fixes that aren't covered by an app's own tests."""
from django.conf import settings
from django.contrib.auth.hashers import get_hasher, make_password
from django.test import TestCase

from accounts.models import RoleTemplate
from core.models import Organization


class PasswordHasherTests(TestCase):
    def test_argon2_is_the_active_hasher(self):
        # The list used to be assigned to AUTH_PASSWORD_HASHERS, which Django
        # ignores, so PBKDF2 was used while the docs said Argon2.
        self.assertFalse(hasattr(settings, 'AUTH_PASSWORD_HASHERS'))
        self.assertEqual(get_hasher().algorithm, 'argon2')
        self.assertTrue(make_password('correct horse battery staple').startswith('argon2$'))

    def test_existing_pbkdf2_hashes_still_verify_and_upgrade(self):
        from django.contrib.auth.models import User
        from django.contrib.auth.hashers import PBKDF2PasswordHasher
        u = User.objects.create_user('legacy-hash')
        u.password = PBKDF2PasswordHasher().encode('legacy-pass-123!', PBKDF2PasswordHasher().salt())
        u.save()
        self.assertTrue(u.check_password('legacy-pass-123!'))
        u.refresh_from_db()
        self.assertTrue(u.password.startswith('argon2$'))


class CustomRoleRevealDefaultTests(TestCase):
    def test_new_custom_role_cannot_reveal_credentials_by_default(self):
        org = Organization.objects.create(name='Example Law', slug='ex-law')
        role = RoleTemplate.objects.create(name='Front desk', organization=org)
        self.assertFalse(role.vault_view_password)
        self.assertTrue(role.vault_view)  # titles stay visible; secrets don't
