"""v3.17.693: responses carry a reference, never exception text
(CodeQL py/stack-trace-exposure)."""
import json
import re
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from core.error_responses import public_error

SECRET = 'sk-SECRET-in-the-exception-text'
REF = re.compile(r'\(reference [0-9a-f]{8}\)\.$')


class PublicErrorTests(SimpleTestCase):
    def test_message_has_summary_and_reference_but_no_exception_text(self):
        with self.assertLogs('clientst0r.errors', level='ERROR') as logs:
            msg = public_error(RuntimeError(SECRET), 'Export failed')
        self.assertTrue(msg.startswith('Export failed. See the server log'))
        self.assertRegex(msg, REF)
        self.assertNotIn(SECRET, msg)
        # The detail goes to the log, under the same reference.
        ref = REF.search(msg).group(0)[11:19]
        self.assertIn(ref, logs.output[0])

    def test_traceback_is_logged(self):
        try:
            raise ValueError(SECRET)
        except ValueError as exc:
            with self.assertLogs('clientst0r.errors', level='ERROR') as logs:
                public_error(exc)
        self.assertIn('Traceback', logs.output[0])
        self.assertIn(SECRET, logs.output[0])

    def test_trailing_period_not_doubled_and_custom_logger(self):
        import logging
        with self.assertLogs('some.app', level='ERROR'):
            msg = public_error(Exception('x'), 'Delete failed.', log=logging.getLogger('some.app'))
        self.assertTrue(msg.startswith('Delete failed. See'))

    def test_references_differ(self):
        with self.assertLogs('clientst0r.errors', level='ERROR'):
            a, b = public_error(Exception()), public_error(Exception())
        self.assertNotEqual(a, b)


class ApiKeyValidatorTests(SimpleTestCase):
    """requests puts the full URL in its exception text, and the Google Maps
    check sends the key as a query parameter."""

    def test_network_error_does_not_echo_the_key(self):
        from core.services.api_key_validator import APIKeyValidator
        exc = requests.exceptions.ConnectionError(
            'HTTPSConnectionPool: Max retries exceeded with url: /maps/api/geocode/json?key=' + SECRET)
        with mock.patch('core.services.api_key_validator.requests.get', side_effect=exc), \
                self.assertLogs('clientst0r.errors', level='ERROR'):
            ok, message, details = APIKeyValidator.validate_google_maps(SECRET)
        self.assertFalse(ok)
        self.assertNotIn(SECRET, message)
        self.assertRegex(message, REF)


class HardwareErrTests(SimpleTestCase):
    def test_non_validation_error_is_generic(self):
        from hardware.views import _err
        with self.assertLogs('clientst0r.errors', level='ERROR'):
            resp = _err(RuntimeError(SECRET))
        body = json.loads(resp.content)
        self.assertNotIn(SECRET, body['error'])
        self.assertRegex(body['error'], REF)

    def test_validation_messages_are_kept(self):
        from django.core.exceptions import ValidationError
        from hardware.views import _err
        resp = _err(ValidationError('Port name is required.'))
        self.assertEqual(json.loads(resp.content)['error'], 'Port name is required.')


class ConnectionTestViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('st', password='x', is_staff=True)
        self.rf = RequestFactory()

    def _call(self, view):
        req = self.rf.post('/x/')
        req.user = self.user
        with mock.patch('integrations.views.get_object_or_404', return_value=mock.Mock()):
            with self.assertLogs('clientst0r.errors', level='ERROR'):
                return view(req, pk=1)

    def test_distributor_test_hides_exception_text(self):
        from integrations import views
        provider = mock.Mock()
        provider.test_connection.side_effect = RuntimeError(SECRET)
        with mock.patch('integrations.providers.distributors.get_distributor_provider',
                        return_value=provider):
            resp = self._call(views.distributor_test)
        body = json.loads(resp.content)
        self.assertFalse(body['ok'])
        self.assertNotIn(SECRET, body['error'])
        self.assertRegex(body['error'], REF)

    def test_accounting_test_hides_exception_text(self):
        from integrations import views
        provider = mock.Mock()
        provider.test_connection.side_effect = RuntimeError(SECRET)
        with mock.patch('integrations.providers.accounting.get_accounting_provider',
                        return_value=provider):
            resp = self._call(views.accounting_test)
        self.assertNotIn(SECRET, resp.content.decode())
