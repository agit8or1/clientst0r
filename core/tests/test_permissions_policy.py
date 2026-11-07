"""Permissions-Policy lists only features browsers still recognise — v3.17.631."""
from django.conf import settings
from django.test import SimpleTestCase

# Features browsers have retired; sending them logs a console error on every page.
RETIRED = {'interest-cohort', 'browsing-topics', 'document-domain', 'vibrate', 'speaker'}


class PermissionsPolicyTests(SimpleTestCase):
    def test_no_retired_features(self):
        self.assertFalse(RETIRED & set(settings.PERMISSIONS_POLICY))

    def test_sensitive_features_stay_disabled(self):
        for feature in ('geolocation', 'microphone', 'camera', 'payment', 'usb'):
            self.assertEqual(settings.PERMISSIONS_POLICY[feature], [])
