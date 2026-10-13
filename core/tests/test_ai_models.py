"""
Settings → AI offers current Claude models (issue #149, v3.17.596).

The dropdown topped out at Claude Opus/Sonnet 4.5 and still listed two retired
Claude 3.5 models. Newer models also reject `temperature`, which the property
URL importer and the triage generator always sent.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.ai_models import (
    CLAUDE_MODEL_IDS, CURRENT_CLAUDE_MODELS, accepts_sampling_params,
    is_valid_claude_model, sampling_kwargs,
)

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


class ModelListTests(SimpleTestCase):

    def test_current_models_are_offered_first(self):
        ids = [m for m, _ in CURRENT_CLAUDE_MODELS]
        self.assertEqual(ids[0], 'claude-opus-5-5')
        for model in ('claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1'):
            self.assertIn(model, ids)

    def test_retired_models_are_gone(self):
        self.assertNotIn('claude-3-5-sonnet-20241022', CLAUDE_MODEL_IDS)
        self.assertNotIn('claude-3-5-haiku-20241022', CLAUDE_MODEL_IDS)

    def test_ids_saved_by_earlier_releases_still_match(self):
        self.assertIn('claude-sonnet-4-5-20250929', CLAUDE_MODEL_IDS)
        self.assertIn('claude-opus-4-5-20251101', CLAUDE_MODEL_IDS)

    def test_model_id_validation(self):
        self.assertTrue(is_valid_claude_model('claude-opus-5-5'))
        self.assertTrue(is_valid_claude_model('claude-opus-4-1-20250805'))
        self.assertFalse(is_valid_claude_model(''))
        self.assertFalse(is_valid_claude_model('gpt-4o'))
        self.assertFalse(is_valid_claude_model('claude-opus-5-5\nANTHROPIC_API_KEY=x'))


class SamplingParamTests(SimpleTestCase):

    def test_models_that_reject_temperature_get_none(self):
        for model in ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5',
                      'claude-fable-5-1', 'claude-opus-5', 'claude-sonnet-5',
                      'claude-opus-4-8', 'claude-opus-4-7', 'some-future-model'):
            self.assertFalse(accepts_sampling_params(model), model)
            self.assertEqual(sampling_kwargs(model, temperature=0), {}, model)

    def test_older_models_keep_temperature(self):
        for model in ('claude-haiku-4-5-20251001', 'claude-sonnet-4-5-20250929',
                      'claude-sonnet-4-6', 'claude-opus-4-6'):
            self.assertEqual(sampling_kwargs(model, temperature=0.3),
                             {'temperature': 0.3}, model)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SettingsAiViewTests(TestCase):
    """BASE_DIR points at a temp dir so the view's .env is a scratch file, and
    subprocess.run is stubbed so a save never signals the real gunicorn."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / '.env'
        override = override_settings(BASE_DIR=Path(self.tmp.name))
        override.enable()
        self.addCleanup(override.disable)
        ps = mock.patch('subprocess.run',
                        return_value=mock.Mock(stdout='', returncode=0))
        ps.start()
        self.addCleanup(ps.stop)
        user = get_user_model().objects.create_user(
            'ai_su', 'a@x.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(user)

    def html(self):
        r = self.client.get(reverse('core:settings_ai'))
        self.assertEqual(r.status_code, 200)
        return r.content.decode()

    def test_dropdown_lists_current_models(self):
        html = self.html()
        self.assertIn('value="claude-opus-5-5"', html)
        self.assertIn('Claude Sonnet 5.5', html)
        self.assertNotIn('claude-3-5-haiku-20241022', html)

    def test_a_saved_model_outside_the_list_stays_selected(self):
        self.env.write_text('CLAUDE_MODEL=claude-opus-4-1-20250805\n')
        self.assertIn('value="claude-opus-4-1-20250805" selected', self.html())

    def test_saving_a_listed_model_writes_it(self):
        self.client.post(reverse('core:settings_ai'), {'claude_model': 'claude-sonnet-5-5'})
        self.assertIn('CLAUDE_MODEL=claude-sonnet-5-5\n', self.env.read_text())

    def test_a_malformed_model_is_not_written_to_env(self):
        self.env.write_text('CLAUDE_MODEL=claude-opus-5-5\n')
        self.client.post(reverse('core:settings_ai'),
                         {'claude_model': 'claude-x\nEVIL=1'})
        text = self.env.read_text()
        self.assertIn('CLAUDE_MODEL=claude-opus-5-5\n', text)
        self.assertNotIn('EVIL', text)
