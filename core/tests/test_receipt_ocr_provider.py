"""Receipt scanning follows the LLM provider the install configured.

The same feature had two implementations that disagreed about where the data
goes. `api_mobile.views_receipts` went through
`get_configured_provider().extract_receipt_fields(...)`, honouring the
configured provider. `vehicles.services.receipt_ocr` built its own
`anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)` client, so the same
receipt scanned in the web UI went to Anthropic regardless — on an install
running Ollama for data residency, every receipt image still left the network.

The two schemas differ, so the mapping is the part most likely to break
quietly: the provider returns `amount_total` / `amount_tax` /
`category_hint` / `line_items` under `extracted`, while the vehicle receipt
form speaks `amount` / `tax_amount` / `category` / `description`. Getting that
wrong produces a form with blank amounts and OCR that looks like it worked.
"""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from vehicles.services.receipt_ocr import extract_receipt_data


def _image():
    return SimpleUploadedFile('r.jpg', b'bytes', content_type='image/jpeg')


PROVIDER_REPLY = {
    'success': True,
    'extracted': {
        'vendor': 'Shell',
        'date': '2026-09-17',
        'amount_total': 64.20,
        'amount_tax': 5.35,
        'gallons': 12.5,
        'cost_per_gallon': 4.99,
        'odometer': 84213,
        'category_hint': 'fuel',
        'line_items': ['Unleaded 12.5gal', 'Car wash'],
        'raw_text': 'SHELL ...',
    },
}


class ReceiptOcrUsesConfiguredProviderTests(TestCase):

    def test_it_asks_the_configured_provider_not_anthropic_directly(self):
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = PROVIDER_REPLY
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider) as factory:
            result = extract_receipt_data(_image())
        factory.assert_called_once()
        provider.extract_receipt_fields.assert_called_once()
        self.assertTrue(result['success'])

    def test_the_provider_schema_is_mapped_onto_the_forms_fields(self):
        """The mapping this whole change hinges on."""
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = PROVIDER_REPLY
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider):
            data = extract_receipt_data(_image())['data']

        self.assertEqual(data['vendor'], 'Shell')
        self.assertEqual(data['date'], '2026-09-17')
        self.assertEqual(data['amount'], 64.20)      # <- amount_total
        self.assertEqual(data['tax_amount'], 5.35)   # <- amount_tax
        self.assertEqual(data['category'], 'fuel')   # <- category_hint
        self.assertEqual(data['odometer'], 84213)
        self.assertIn('Unleaded', data['description'])  # <- line_items

    def test_fuel_figures_the_old_prompt_never_asked_for_now_arrive(self):
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = PROVIDER_REPLY
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider):
            data = extract_receipt_data(_image())['data']
        self.assertEqual(data['gallons'], 12.5)
        self.assertEqual(data['cost_per_gallon'], 4.99)

    def test_an_unrecognised_category_falls_back_rather_than_reaching_the_form(self):
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = {
            'success': True, 'extracted': {'category_hint': 'spaceship-parts'},
        }
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider):
            data = extract_receipt_data(_image())['data']
        self.assertEqual(data['category'], 'other')

    def test_unreadable_numbers_become_none_not_a_crash(self):
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = {
            'success': True,
            'extracted': {'amount_total': 'about twenty quid', 'odometer': 'n/a'},
        }
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider):
            data = extract_receipt_data(_image())['data']
        self.assertIsNone(data['amount'])
        self.assertIsNone(data['odometer'])

    def test_no_configured_provider_is_reported_not_silently_empty(self):
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=None):
            result = extract_receipt_data(_image())
        self.assertFalse(result['success'])
        self.assertIn('No LLM provider is configured', result['error'])

    def test_a_provider_failure_is_passed_through(self):
        provider = mock.Mock()
        provider.extract_receipt_fields.return_value = {
            'success': False, 'error': 'Model returned non-JSON',
        }
        with mock.patch('docs.services.llm_providers.get_configured_provider',
                        return_value=provider):
            result = extract_receipt_data(_image())
        self.assertFalse(result['success'])
        self.assertIn('non-JSON', result['error'])

    def test_the_module_no_longer_builds_its_own_anthropic_client(self):
        """
        Checked against the parsed module, not its text: the docstring
        explains the old `anthropic.Anthropic(...)` code on purpose, so a
        substring search would trip over the explanation.
        """
        import ast
        import pathlib

        src = pathlib.Path(
            __file__).resolve().parents[2] / 'vehicles/services/receipt_ocr.py'
        tree = ast.parse(src.read_text())

        attrs = {f'{n.value.id}.{n.attr}'
                 for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        self.assertNotIn('anthropic.Anthropic', attrs)
        self.assertNotIn('settings.ANTHROPIC_API_KEY', attrs)

        imported = {a.name for n in ast.walk(tree)
                    if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn('anthropic', imported)
