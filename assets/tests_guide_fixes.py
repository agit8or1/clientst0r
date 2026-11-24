"""Fixes found while writing the Assets guide (roadmap 112.3)."""
import io
import json

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from accounts.models import Membership, Role
from assets.models import Asset, Relationship
from assets.tests import TEST_MIDDLEWARE, _login_in_org
from core.models import Organization


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class AssetGuideFixTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Guide Org', slug='guide-org')
        self.user = User.objects.create_user('guide-owner', password='pw')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER, is_active=True)
        self.fw = Asset.objects.create(organization=self.org, name='GW-FW01', asset_type='firewall',
                                       serial_number='SN-FW-1')
        self.sw = Asset.objects.create(organization=self.org, name='GW-SW01', asset_type='switch')
        self.client = Client()
        _login_in_org(self.client, self.user, self.org)

    def test_network_scan_upload_matches_devices(self):
        scan = {'scan_date': '2026-11-24', 'devices': [
            {'ip': '10.0.0.1', 'hostname': 'GW-FW01', 'mac': '00:11:22:33:44:55'},
            {'ip': '10.0.0.9', 'hostname': 'new-printer'}]}
        upload = SimpleUploadedFile('scan.json', json.dumps(scan).encode(), content_type='application/json')
        r = self.client.post('/assets/network-scan/upload/', {'scan_file': upload})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['success'])
        self.assertEqual(self.client.session['pending_scan_import']['device_count'], 2)

    def test_scanner_script_downloads(self):
        r = self.client.get('/assets/network-scan/scanner.py')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment; filename="network_scanner.py"', r['Content-Disposition'])
        self.assertIn(b'nmap', b''.join(r.streaming_content))

    def test_relationships_show_names_and_links(self):
        Relationship.objects.create(organization=self.org, source_type='asset', source_id=self.fw.pk,
                                    target_type='asset', target_id=self.sw.pk, relation_type='depends')
        Relationship.objects.create(organization=self.org, source_type='asset', source_id=self.fw.pk,
                                    target_type='asset', target_id=999999, relation_type='related')
        r = self.client.get(f'/assets/{self.fw.pk}/')
        self.assertContains(r, f'href="/assets/{self.sw.pk}/"')
        self.assertContains(r, 'GW-SW01')
        self.assertContains(r, 'asset #999999')
        self.assertNotContains(r, f'asset:{self.sw.pk}')
        self.assertContains(r, f'source_type=asset&amp;source_id={self.fw.pk}')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class SubnetListVlanTests(TestCase):

    def test_subnet_list_shows_the_vlan_number_and_name(self):
        from monitoring.models import VLAN, Subnet
        org = Organization.objects.create(name='Net Org', slug='net-org')
        user = User.objects.create_user('net-owner', password='pw')
        Membership.objects.create(user=user, organization=org, role=Role.OWNER, is_active=True)
        vlan = VLAN.objects.create(organization=org, vlan_id=10, name='Office LAN')
        Subnet.objects.create(organization=org, name='Office', network='10.10.0.0/24', vlan=vlan)
        self.assertNotEqual(vlan.pk, 10)
        c = Client()
        _login_in_org(c, user, org)
        r = c.get('/monitoring/ipam/')
        self.assertContains(r, 'VLAN 10')
        self.assertContains(r, 'Office LAN')
        self.assertNotContains(r, f'VLAN {vlan.pk}<')
