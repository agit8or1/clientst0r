"""Opt-in real-tenant suite for Microsoft 365 documents. NOT RUN so far.

Skipped unless every variable below is set. Point it at a disposable test
folder: it creates files there (named clientst0r-e2e-*) and deletes them at
the end with DELETE /drives/{id}/items/{id} (no sharing endpoints).

    OFFICE_E2E_M365_TENANT          tenant ID
    OFFICE_E2E_M365_CLIENT_ID       app registration (client) ID
    OFFICE_E2E_M365_CLIENT_SECRET   client secret
    OFFICE_E2E_M365_REFRESH_TOKEN   a delegated refresh token for a test user,
                                    obtained with the scopes for read-write +
                                    SharePoint 'all' (Files.ReadWrite,
                                    Files.ReadWrite.All, offline_access)
    OFFICE_E2E_M365_DRIVE_ID        drive of the test folder
    OFFICE_E2E_M365_FOLDER_ID       the test folder's item ID
    OFFICE_E2E_M365_SHAREPOINT_HOST e.g. contoso.sharepoint.com

Run:
    manage.py test integrations.tests_m365docs_e2e
"""
import os
import shutil
import tempfile
import unittest
import uuid

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Membership, Role
from core.models import Organization

ENV = ('OFFICE_E2E_M365_TENANT', 'OFFICE_E2E_M365_CLIENT_ID', 'OFFICE_E2E_M365_CLIENT_SECRET',
       'OFFICE_E2E_M365_REFRESH_TOKEN', 'OFFICE_E2E_M365_DRIVE_ID',
       'OFFICE_E2E_M365_FOLDER_ID', 'OFFICE_E2E_M365_SHAREPOINT_HOST')
CONFIGURED = all(os.environ.get(k) for k in ENV)


@unittest.skipUnless(CONFIGURED, 'Real Microsoft 365 tenant not configured (OFFICE_E2E_M365_*)')
class RealTenantTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='m365-e2e-')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from integrations.models import M365AllowedLocation, M365Connection, M365DocsGrant
        e = os.environ
        self.org = Organization.objects.create(name='E2E', slug='m365-e2e')
        self.user = User.objects.create_user('m365-e2e', 'e2e@example.com', 'x')
        Membership.objects.create(user=self.user, organization=self.org, role=Role.OWNER,
                                  is_active=True)
        self.conn = M365Connection(organization=self.org, name='E2E',
                                   tenant_id=e['OFFICE_E2E_M365_TENANT'], docs_enabled=True,
                                   docs_access='readwrite', docs_sharepoint='all',
                                   docs_sharepoint_host=e['OFFICE_E2E_M365_SHAREPOINT_HOST'])
        self.conn.set_credentials({'client_id': e['OFFICE_E2E_M365_CLIENT_ID'],
                                   'client_secret': e['OFFICE_E2E_M365_CLIENT_SECRET']})
        self.conn.save()
        self.grant = M365DocsGrant.objects.create(
            connection=self.conn, user=self.user,
            refresh_token=e['OFFICE_E2E_M365_REFRESH_TOKEN'])
        self.drive = e['OFFICE_E2E_M365_DRIVE_ID']
        self.folder = e['OFFICE_E2E_M365_FOLDER_ID']
        self.loc = M365AllowedLocation.objects.create(
            connection=self.conn, organization=self.org, kind='folder', drive_id=self.drive,
            item_id=self.folder, display_name='E2E folder')
        self.created = []

    def tearDown(self):
        from integrations.m365docs import graph
        client = graph.GraphClient(self.grant)
        for item_id in self.created:
            try:
                client.request('DELETE', f'/drives/{self.drive}/items/{item_id}')
            except Exception:
                pass

    def test_full_checklist(self):
        from integrations.m365docs import access, graph, http, services
        from office import creation, storage

        # Refresh: obtains an access token and a rotated refresh token.
        client = graph.GraphClient(self.grant)
        children = client.children(self.drive, self.folder)
        self.assertIsInstance(children, list)
        self.grant.refresh_from_db()
        self.assertTrue(self.grant.access_token)

        # Create with conflictBehavior=fail, twice: the second must be a 409.
        name = f'clientst0r-e2e-{uuid.uuid4().hex[:8]}'
        link = services.create(self.user, self.conn, self.loc, self.drive, self.folder,
                               'docx', name)
        self.created.append(link.item_id)
        with self.assertRaises(graph.GraphError) as cm:
            client.upload_new(self.drive, self.folder, f'{name}.docx',
                              creation.blank_bytes('docx'))
        self.assertEqual(cm.exception.status, 409)

        # Allowlist: the folder's parent is outside.
        meta = client.item(self.drive, self.folder)
        parent = (meta.get('parentReference') or {}).get('id')
        if parent:
            with self.assertRaises(access.NotPermitted):
                access.locate(client, self.conn, self.drive, parent)

        # Open: a fresh webUrl on the tenant's SharePoint host.
        url = services.open_url(self.user, link)
        self.assertTrue(http.is_allowed(url, http.sharepoint_hosts(self.conn)))

        # Import a copy, then export it back under a new name.
        target = services.import_copy(self.user, self.conn, self.drive, link.item_id)
        self.assertEqual(storage.current(target).source, 'import')
        exported = services.export_copy(self.user, target, self.conn, self.loc, self.drive,
                                        self.folder, f'{name}-export.docx')
        self.created.append(exported['id'])
        self.assertEqual(exported['name'], f'{name}-export.docx')
