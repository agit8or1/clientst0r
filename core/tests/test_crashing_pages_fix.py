"""Two pages found crashing by the 113.4 page check.

* Roles -> "Why" (accounts:access_explain) raised "Cannot combine a unique
  query with a non-unique query" for superusers and group managers.
* Assets -> Relationships (assets:relationship_map) had no template.
"""
from django.urls import reverse

from assets.models import Asset, Relationship
from core.tests.test_page_budgets import PageBudgetBase


class CrashingPagesTests(PageBudgetBase):

    def setUp(self):
        super().setUp()
        self.login(self.superuser, self.orgs[0])

    def test_access_explain_opens_for_superuser(self):
        r = self.client.get(reverse('accounts:access_explain'))
        self.assertEqual(r.status_code, 200)

    def test_relationship_map_lists_links(self):
        org = self.orgs[0]
        a = Asset.objects.create(organization=org, name='Map source host')
        b = Asset.objects.create(organization=org, name='Map target host')
        Relationship.objects.create(organization=org, source_type='asset', source_id=a.pk,
                                    target_type='asset', target_id=b.pk, relation_type='depends')
        r = self.client.get(reverse('assets:relationship_map'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Map source host')
        self.assertContains(r, 'Map target host')
        r = self.client.get(reverse('assets:relationship_map') + f'?type=asset&id={a.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Map target host')

    def test_relationship_map_empty_state(self):
        r = self.client.get(reverse('assets:relationship_map'))
        self.assertEqual(r.status_code, 200)
