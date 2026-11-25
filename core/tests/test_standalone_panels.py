"""Standalone operation (docs/ux/STANDALONE_REQUIREMENTS.md, rule F6): with no
RMM connected, the RMM alert panels must say that nothing is collected
instead of showing a green "No active RMM alerts", which reads as healthy."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase

from core import dashboard_global as dg
from core import dashboard_widgets as dw
from core.models import Organization

User = get_user_model()


class RMMAlertPanelWithoutRMMTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Standalone Co', slug='standalone-co')
        cls.root = User.objects.create_superuser('standalone_root', 'r@x.com', 'pw')

    def _req(self):
        return SimpleNamespace(user=self.root, current_organization=self.org, session={})

    def test_customer_panel_without_rmm_is_not_shown_as_healthy(self):
        w = dw.build_rmm_alerts(self._req(), self.org)
        self.assertFalse(w['rmm_configured'])
        html = render_to_string('core/dashboard/_w_rmm_alerts.html', {'w': w})
        self.assertIn('data-rmm-not-configured', html)
        self.assertNotIn('fa-check-circle', html)
        self.assertNotIn('No active RMM alerts', html)

    def test_global_panel_without_rmm_is_not_shown_as_healthy(self):
        from unittest import mock
        with mock.patch.object(dg, '_rmm_alerts', return_value=_EmptyQS()):
            w = dg.build_g_rmm_alerts(self._req(), None)
        self.assertFalse(w['rmm_configured'])
        html = render_to_string('core/dashboard/_w_g_rmm_alerts.html', {'w': w})
        self.assertIn('data-rmm-not-configured', html)
        self.assertNotIn('No active RMM alerts', html)

    def test_with_an_rmm_connection_an_empty_list_reads_as_no_alerts(self):
        from integrations.models import RMMConnection
        RMMConnection.objects.create(organization=self.org, name='Tactical', provider_type='tactical_rmm',
                                     base_url='https://rmm.example.com')
        w = dw.build_rmm_alerts(self._req(), self.org)
        self.assertTrue(w['rmm_configured'])
        html = render_to_string('core/dashboard/_w_rmm_alerts.html', {'w': w})
        self.assertIn('No active RMM alerts', html)
        self.assertNotIn('data-rmm-not-configured', html)


class _EmptyQS:
    def select_related(self, *a):
        return self

    def order_by(self, *a):
        return self

    def __getitem__(self, k):
        return []
