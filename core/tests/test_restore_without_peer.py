"""P0-5 (docs/ux/STANDALONE_REQUIREMENTS.md, rule I6; matrix O): restoring a
backup that contains peer rows, with no peer reachable.

What runs for real: ``core.upgrade.snapshot.create()`` (SQLite online backup of
the test database, media, keys), ``snapshot.verify()`` and
``snapshot.restore(code=False)`` (page-level restore into a SQLite file),
all under no_network(). The test database (in memory) is first written to a
file, which plays the live database; after the restore the file is loaded back
into the test database, and pages are rendered from the restored data.

Not covered here (needs a real install): the ``code=True`` step (``git reset``
and ``pip install``), the MariaDB restore path (mysql client), and the
``manage.py upgrade_backup`` / Apply-button wrappers.
"""
import sqlite3
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from core.tests.standalone import no_network, peer_unreachable
from core.tests.test_navbar_grouping import TEST_MIDDLEWARE
from core.upgrade import snapshot

User = get_user_model()
SHA = 'a' * 40


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['*'],
                   AGIT8OR_CONNECT_ENABLED=True)
class RestoreWithoutPeerTests(TransactionTestCase):
    # Without this, the flush after each test re-creates content types and
    # permissions (post_migrate), and a later serialized-rollback suite
    # (psa.routing ConcurrencyTests) then fails to load its saved rows on top
    # of them: UNIQUE constraint failed on django_content_type.
    serialized_rollback = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='restore-no-peer-'))
        self.addCleanup(__import__('shutil').rmtree, self.tmp, True)
        (self.tmp / 'base').mkdir()
        (self.tmp / 'media').mkdir()
        self.live = self.tmp / 'live.sqlite3'

    # -- data -----------------------------------------------------------
    def _make_data(self):
        from accounts.models import Membership, Role
        from assets.models import Asset
        from connect.models import Connection
        from core.models import Organization
        from docs.models import Document
        from integrations.models import RMMConnection, RMMDevice
        from integrations.rem0te import testing as rem0te_testing
        from psa.tests._base import _enable_psa_for, _make_msp_tech, _setup_seed
        from tech_access.testing import make_ticket
        from vault.models import Password

        _setup_seed()
        self.org = Organization.objects.create(name='Restore Co', slug='restore-co')
        _enable_psa_for(self.org)
        self.su = _make_msp_tech(User.objects.create_user('restore_root', 'r@x.test', 'pw',
                                                          is_staff=True, is_superuser=True))
        Membership.objects.create(user=self.su, organization=self.org, role=Role.OWNER, is_active=True)
        self.ticket = make_ticket(self.org, assigned_to=self.su, subject='Restore me please')
        self.asset = Asset.objects.create(organization=self.org, name='Restore PC', hostname='RESTORE-01',
                                          asset_type='desktop')
        self.doc = Document.objects.create(organization=self.org, title='Restore runbook', slug='restore-runbook',
                                           body='<p>Steps after a restore</p>', created_by=self.su)
        pw = Password.objects.create(organization=self.org, title='Restore router', username='admin')
        pw.set_password('s3cret-value')
        pw.save()
        self.password = pw
        self.rmm = RMMConnection.objects.create(organization=self.org, provider_type='tactical_rmm',
                                                name='Restore Tactical', base_url='https://rmm.example.com')
        RMMDevice.objects.create(organization=self.org, connection=self.rmm, external_id='d-1',
                                 device_name='RESTORE-01', device_type='workstation', linked_asset=self.asset)
        self.rem0te = rem0te_testing.make_connection(self.org, name='Restore Rem0te')
        self.pairing = Connection.objects.create(
            direction=Connection.OUTBOUND, state=Connection.ACTIVE, remote_app_type='rem0te',
            remote_installation_id='inst-' + uuid.uuid4().hex[:8], remote_display_name='Restore Rem0te',
            base_url='https://rem0te.example.com')

    def _snapshot_test_db_to_live(self):
        dst = sqlite3.connect(str(self.live))
        try:
            connection.connection.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')
        finally:
            dst.close()

    def _load_live_into_test_db(self):
        src = sqlite3.connect(str(self.live))
        try:
            src.backup(connection.connection)
        finally:
            src.close()

    def _settings(self):
        o = override_settings(BASE_DIR=self.tmp / 'base', MEDIA_ROOT=str(self.tmp / 'media'),
                              UPGRADE_BACKUP_DIR=self.tmp / 'backups', AI_GATEWAY_KEY_DIR='')
        o.enable()
        self.addCleanup(o.disable)
        for target, kw in (
                (mock.patch.object(snapshot, '_db', return_value={'ENGINE': 'django.db.backends.sqlite3',
                                                                  'NAME': str(self.live)}), {}),
                (mock.patch.object(snapshot, 'current_revision', return_value=SHA), {})):
            target.start()
            self.addCleanup(target.stop)

    # -- the test -------------------------------------------------------
    def test_backup_with_peer_rows_restores_with_no_network(self):
        from connect.models import Connection
        from docs.models import Document
        from integrations.models import RMMConnection, RMMDevice
        from psa.models import Ticket
        from vault.models import Password

        if connection.vendor != 'sqlite':
            self.skipTest('the SQLite restore path is what runs in the test environment')
        self._make_data()
        self._snapshot_test_db_to_live()
        self._settings()
        counts = {m: m.objects.count() for m in (Ticket, Document, Password, RMMConnection, RMMDevice, Connection)}
        encrypted = Password.objects.get(pk=self.password.pk).encrypted_password

        with no_network() as net:
            snap = snapshot.create(reason='restore without peer')
            report = snapshot.verify(snap)
            self.assertTrue(report['ok'], report)

            # Damage the live database: peer rows and local data gone.
            raw = sqlite3.connect(str(self.live))
            raw.execute('PRAGMA foreign_keys=OFF')
            for table in ('psa_ticket', 'docs_document', 'passwords', 'connect_connection',
                          'integrations_rmmdevice', 'integrations_rmmconnection'):
                try:
                    raw.execute(f'DELETE FROM {table}')
                except sqlite3.OperationalError:
                    pass
            raw.commit()
            raw.close()

            with mock.patch('django.db.connections.close_all'):
                snapshot.restore(snap, code=False)
        self.assertEqual(net.attempts, [], 'backup / verify / restore called out')

        self._load_live_into_test_db()
        for model, n in counts.items():
            self.assertEqual(model.objects.count(), n, model.__name__)
        self.assertEqual(Password.objects.get(pk=self.password.pk).encrypted_password, encrypted)
        self.assertEqual(Ticket.objects.get(pk=self.ticket.pk).subject, 'Restore me please')
        restored = Password.objects.get(pk=self.password.pk)
        self.assertEqual((restored.title, restored.username), ('Restore router', 'admin'))
        self.assertEqual(restored.get_password(), 's3cret-value')
        # The peer rows came back as they were: no state was invented or reset.
        self.assertEqual(Connection.objects.get(pk=self.pairing.pk).state, Connection.ACTIVE)
        self.assertTrue(RMMConnection.objects.filter(pk=self.rem0te.pk).exists())

        # Sign-in and pages work from the restored data, with the peer silent.
        self.client.force_login(self.su)
        s = self.client.session
        s['2fa_prompted'] = True
        s['current_organization_id'] = self.org.pk
        s.save()
        pages = {
            'ticket': f'/psa/t/{self.ticket.ticket_number}/',
            'ticket list': reverse('psa:ticket_list'),
            'document': reverse('docs:document_detail', args=[self.doc.slug]),
            'document list': reverse('docs:document_list'),
            'password list': reverse('vault:password_list'),
            'asset': f'/assets/{self.asset.pk}/',
            'customer': reverse('accounts:organization_detail', args=[self.org.pk]),
            'dashboard': reverse('core:dashboard'),
            'rmm devices': reverse('integrations:rmm_devices'),
            'connected applications': reverse('connect:index'),
        }
        with peer_unreachable('timeout') as peer:
            for label, path in pages.items():
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200, f'{label} {path}')
            self.assertIn('Restore me please', self.client.get(pages['ticket list']).content.decode())
        self.assertEqual(peer.attempts, [], 'a page called the peer after the restore')

        # First scheduler pass after the restore: at most one check per Rem0te connection.
        from integrations.rem0te import reconcile
        with peer_unreachable('timeout') as peer:
            reconcile.reconcile_all()
        per_conn = [a for a in peer.attempts if a[0] == 'rem0te.client.request']
        self.assertLessEqual(len(per_conn), 1 * RMMConnection.objects.filter(provider_type='rem0te').count(),
                             per_conn)
