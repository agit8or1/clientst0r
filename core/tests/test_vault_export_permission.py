"""`vault_export` grants nothing, and now says so.

The permission is defined on every role template, is a labelled checkbox in
the role editor, and is displayed in the role list. Nothing anywhere checks
it: Client St0r has no bulk password export — no view, no URL. Granting or
denying it changed nothing at all.

Building the export was deliberately not done. A bulk password export is a
path that decrypts every credential in an organization and hands it over as a
file; it needs master-key handling, per-record audit, and probably
re-authentication and an approval step. That is a feature to design, not
something to add while fixing adjacent bugs.

These tests pin the honest state: the flag still stores, still grants
nothing, and the UI says which.
"""
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Membership, RoleTemplate
from core.models import Organization


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class VaultExportIsNotImplementedTests(TestCase):

    def test_no_url_resolves_to_a_vault_export(self):
        """If someone builds one, this test should be the thing that fails."""
        from django.urls import get_resolver

        names = []

        def walk(resolver, ns=''):
            for p in resolver.url_patterns:
                if hasattr(p, 'url_patterns'):
                    walk(p, (ns + ':' + p.namespace) if p.namespace else ns)
                elif p.name:
                    names.append(f'{ns.strip(":")}:{p.name}' if ns else p.name)

        walk(get_resolver())
        exports = [n for n in names
                   if 'vault' in n.lower() and 'export' in n.lower()]
        self.assertEqual(exports, [])

    def test_nothing_in_the_codebase_gates_on_the_permission(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2]
        gating = []
        for path in root.rglob('*.py'):
            sp = str(path)
            if '/migrations/' in sp or '/tests' in sp or '/venv/' in sp:
                continue
            for line in path.read_text(errors='ignore').splitlines():
                # A real gate reads the flag off a user or permission object;
                # assigning or declaring it is not a gate.
                if re.search(r"(user_has_perm\(.*vault_export|perms\.vault_export|"
                             r"require_perm\(['\"]vault_export)", line):
                    gating.append(f'{path.relative_to(root)}: {line.strip()}')
        self.assertEqual(gating, [], 'a gate exists — update this test and the UI copy')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RoleEditorSaysSoTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Co', slug='ve-co')
        self.su = get_user_model().objects.create_user(
            've_su', 'v@x.com', 'pw', is_staff=True, is_superuser=True)
        # `role_create` gates on an active admin membership, not on the
        # superuser flag, so the user needs one to reach the form.
        Membership.objects.create(
            user=self.su, organization=self.org, role='admin', is_active=True)
        self.client.force_login(self.su)
        session = self.client.session
        session['current_organization_id'] = self.org.pk
        session.save()

    def test_the_role_editor_marks_it_unimplemented(self):
        r = self.client.get(reverse('accounts:role_create'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Not yet implemented')
        self.assertContains(r, 'no bulk password export')

    def test_the_flag_still_stores(self):
        """Kept rather than dropped, so stored intent survives."""
        rt = RoleTemplate.objects.create(name='VEKeeps', vault_export=True)
        self.assertTrue(RoleTemplate.objects.get(pk=rt.pk).vault_export)
