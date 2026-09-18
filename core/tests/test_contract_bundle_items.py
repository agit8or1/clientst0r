"""Bundled services survive a contract save — issue #147.

The editor's submit handler was bound with `document.querySelector('form')`,
which returns the first form in the *document*, not the nearest one.
`base.html` renders the navbar — which contains the search form — before
`{% block content %}`, so the handler attached to the search box and never ran
on the contract form. `bundle_items_json` posted empty every time.

That is the reported half: new bundle rows were never saved.

The unreported half is worse. The view reconciles by deleting rows not present
in the submitted JSON:

    item.bundle_items.exclude(pk__in=seen_pks).delete()

With the field empty, `seen_pks` is empty, so **every existing bundle item was
deleted on any save** — and `psa_auto_renew_contracts` copies bundle items
onto renewal contracts, so rows exist that this form never created. Editing a
renewed contract's name silently wiped its bundle.
"""
from datetime import date
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Organization, SystemSetting
from psa.models import Contract, ContractBundleItem


TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class BundleItemsSurviveSaveTests(TestCase):

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.save()
        self.org = Organization.objects.create(name='Acme', slug='bundle-acme')
        self.user = get_user_model().objects.create_user(
            'bundle_su', 'b@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.contract = Contract.objects.create(
            organization=self.org, client_org=self.org, name='Managed Services',
            status='active', contract_type='managed_services',
            billing_frequency='monthly', start_date=date.today())
        self.bundle = ContractBundleItem.objects.create(
            contract=self.contract, name='Backup — per server',
            quantity=Decimal('10'), unit_price=Decimal('12.00'),
            recurring_period='monthly', sort_order=0)

    def _post(self, **extra):
        data = {
            'name': self.contract.name,
            'client_org': str(self.org.pk),
            'contract_type': 'managed_services',
            'status': 'active',
            'start_date': date.today().isoformat(),
        }
        data.update(extra)
        return self.client.post(
            reverse('psa:contract_edit', kwargs={'pk': self.contract.pk}), data)

    def test_saving_without_the_field_keeps_existing_bundle_items(self):
        """
        The data-loss half: a submission that never carried the field at all
        must not be read as "the user removed every row".
        """
        self._post()  # no bundle_items_json, exactly as the broken JS produced
        self.assertEqual(self.contract.bundle_items.count(), 1)
        self.assertTrue(
            ContractBundleItem.objects.filter(pk=self.bundle.pk).exists())

    def test_an_explicit_empty_list_still_clears_them(self):
        """A user who deletes every row means it, and the editor sends `[]`."""
        self._post(bundle_items_json='[]')
        self.assertEqual(self.contract.bundle_items.count(), 0)

    def test_submitted_rows_are_saved(self):
        import json
        rows = [{'pk': '', 'name': 'Monitoring — per device', 'quantity': '25',
                 'unit_label': 'device', 'unit_price': '3.50',
                 'recurring_period': 'monthly'}]
        self._post(bundle_items_json=json.dumps(rows))
        names = set(self.contract.bundle_items.values_list('name', flat=True))
        self.assertIn('Monitoring — per device', names)
        self.assertNotIn('Backup — per server', names)  # replaced, as intended

    def test_existing_rows_are_updated_not_duplicated(self):
        import json
        rows = [{'pk': str(self.bundle.pk), 'name': 'Backup — per server',
                 'quantity': '20', 'unit_label': '', 'unit_price': '12.00',
                 'recurring_period': 'monthly'}]
        self._post(bundle_items_json=json.dumps(rows))
        self.assertEqual(self.contract.bundle_items.count(), 1)
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.quantity, Decimal('20'))

    def test_malformed_json_does_not_wipe_the_bundle(self):
        """Garbage in the field used to fall through to `[]` and delete everything."""
        self._post(bundle_items_json='{not json at all')
        self.assertEqual(self.contract.bundle_items.count(), 1)

    def test_a_renewed_contracts_bundle_is_not_lost_by_an_unrelated_edit(self):
        """
        `psa_auto_renew_contracts` copies bundle items onto the renewal, so
        they exist without this form having created them — the case where the
        deletion did real damage.
        """
        renewal = Contract.objects.create(
            organization=self.org, client_org=self.org, name='Managed Services',
            status='active', contract_type='managed_services',
            billing_frequency='monthly', start_date=date.today(),
            parent_contract=self.contract)
        ContractBundleItem.objects.create(
            contract=renewal, name='Backup — per server', quantity=Decimal('10'),
            unit_price=Decimal('12.00'), recurring_period='monthly')

        self.client.post(
            reverse('psa:contract_edit', kwargs={'pk': renewal.pk}),
            {'name': 'Managed Services (renewed)', 'client_org': str(self.org.pk),
             'contract_type': 'managed_services', 'status': 'active',
             'start_date': date.today().isoformat()})

        renewal.refresh_from_db()
        self.assertEqual(renewal.name, 'Managed Services (renewed)')
        self.assertEqual(renewal.bundle_items.count(), 1)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class EditorBindsToTheContractFormTests(TestCase):
    """The reported half — checked on the rendered page, not the source file."""

    def setUp(self):
        row = SystemSetting.get_settings()
        row.psa_enabled = True
        row.save()
        self.org = Organization.objects.create(name='Acme', slug='bundle-form')
        self.user = get_user_model().objects.create_user(
            'bundle_form_su', 'bf@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _html(self):
        # The bundle editor only renders on edit — it needs a parent contract
        # pk to hang the rows off — so the create page never contains it.
        from datetime import date

        from psa.models import Contract

        contract = Contract.objects.create(
            organization=self.org, client_org=self.org, name='Managed',
            status='active', contract_type='managed_services',
            billing_frequency='monthly', start_date=date.today())
        r = self.client.get(
            reverse('psa:contract_edit', kwargs={'pk': contract.pk}))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_the_handler_is_not_bound_to_the_first_form_in_the_document(self):
        # The binding specifically — the comment above it quotes the old code
        # on purpose, so a bare substring search would match that instead.
        self.assertNotIn("const form = document.querySelector('form');",
                         self._html())

    def test_the_handler_is_bound_to_the_editors_own_form(self):
        self.assertIn("hidden.closest('form')", self._html())

    def test_the_page_really_does_contain_an_earlier_form(self):
        """
        Without this, the bug is not reproducible and the fix looks arbitrary:
        the navbar's search form is rendered before the contract form.
        """
        html = self._html()
        first_form = html.index('<form')
        contract_form = html.index('<form method="post" class="card"')
        self.assertLess(first_form, contract_form,
                        'expected an earlier form from base.html')


class NoTemplateGrabsTheFirstFormInTheDocumentTests(TestCase):
    """Guards the shape across every template — issue #147 twice over.

    `document.querySelector('form')` returns the first form in the document.
    Every page extends `base.html`, whose navbar renders a search form before
    the content block, so that call never returns the page's own form. It bit
    `psa/contract_form.html` (bundled services silently lost) and
    `core/settings_ai.html` (restart overlay and double-submit guard never
    bound).
    """

    def test_no_template_binds_to_the_first_form_in_the_document(self):
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[2] / 'templates'
        pattern = re.compile(r"""=\s*document\.querySelector\((['"])form\1\)""")
        offenders = []
        for path in root.rglob('*.html'):
            for lineno, line in enumerate(
                    path.read_text(errors='replace').splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f'{path.relative_to(root)}:{lineno}')
        self.assertEqual(
            offenders, [],
            'a template binds to the document\'s first form, which is the '
            'navbar search box, not its own form — use `el.closest("form")`:\n  '
            + '\n  '.join(offenders))
