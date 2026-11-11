"""RMM data on asset and ticket pages follows `integrations_view` (or RMM
device access) for the customer, technicians only."""
from django.contrib.auth.models import User

from accounts.models import RoleTemplate
from integrations import tests_rmm_association as base
from integrations.rmm_visibility import can_see_rmm_data


class RMMDataVisibilityTests(base.TicketAssetTests):
    """Reuses TicketAssetTests' synced NinjaOne device on Acme's FRONTDESK."""

    def _global_role(self, **flags):
        role = RoleTemplate.objects.create(name=f'RV global {len(flags)}-{sorted(flags.items())}',
                                           assets_view=True, tickets_view=True, **flags)
        profile = self.tech.profile
        profile.global_role_template = role
        profile.save()
        return role

    def test_helper_rules(self):
        self.assertTrue(can_see_rmm_data(self.tech, self.a))          # staff, no global role
        self.assertFalse(can_see_rmm_data(self.customer, self.a))     # customers never
        self.assertFalse(can_see_rmm_data(self.tech, None))
        self._global_role(integrations_view=False)
        self.assertFalse(can_see_rmm_data(User.objects.get(pk=self.tech.pk), self.a))
        self._global_role(integrations_view=True)
        self.assertTrue(can_see_rmm_data(User.objects.get(pk=self.tech.pk), self.a))

    def test_asset_page_rmm_tab_needs_integrations_view(self):
        url = f'/assets/{self.asset_a.pk}/'
        r = self.login(self.tech, self.a).get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(list(r.context['rmm_devices']))
        self._global_role(integrations_view=False)
        r = self.login(User.objects.get(pk=self.tech.pk), self.a).get(url)
        self.assertEqual(list(r.context['rmm_devices']), [])
        self.assertEqual(r.context['rmm_summaries'], [])

    def test_ticket_page_rmm_summary_needs_integrations_view(self):
        t = self._ticket(self.asset_a)
        r = self.login(self.tech, self.a).get(f'/psa/t/{t.ticket_number}/')
        self.assertTrue(r.context['ticket_rmm'])
        self._global_role(integrations_view=False)
        r = self.login(User.objects.get(pk=self.tech.pk), self.a).get(f'/psa/t/{t.ticket_number}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['ticket_rmm'], [])
        self.assertNotIn('rmm-summary', r.content.decode())


# Only the tests above: the inherited ones already run in tests_rmm_association.
for _name in dir(base.TicketAssetTests):
    if _name.startswith('test_') and _name not in RMMDataVisibilityTests.__dict__:
        setattr(RMMDataVisibilityTests, _name, None)
