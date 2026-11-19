from django.test import SimpleTestCase

from monitoring.check_errors import describe


class CheckErrorTextTests(SimpleTestCase):
    def test_dns_failure(self):
        raw = ("_GuardedHTTPSConnectionPool(host='admin.acme.demo', port=443): Max retries exceeded with url: / "
               "(Caused by NameResolutionError(\"_GuardedHTTPSConnection(host='admin.acme.demo', port=443): "
               "Failed to resolve 'admin.acme.demo' ([Errno -2] Name or service not known)\"))")
        msg = describe(Exception(raw), 'admin.acme.demo')
        self.assertEqual(msg, "Couldn't find the server: the name admin.acme.demo does not resolve (DNS).")
        self.assertNotIn('Pool', msg)

    def test_refused_and_certificate(self):
        self.assertIn('Connection refused', describe(Exception('[Errno 111] Connection refused'), 'h', 8443))
        self.assertIn("certificate isn't trusted",
                      describe(Exception('SSLError(SSLCertVerificationError(1, "certificate verify failed"))'), 'h'))

    def test_unknown_error_is_short(self):
        self.assertTrue(describe(Exception('x' * 1000), 'h').startswith('The check failed: '))
        self.assertLess(len(describe(Exception('x' * 1000), 'h')), 230)
