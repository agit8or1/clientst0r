"""
Software inventory sync for every RMM provider.

The sync used to pass Tactical RMM's ``uuid=`` argument to every provider, so
NinjaOne, Datto RMM, Atera and ConnectWise Automate raised TypeError on every
device and their software never synced. A provider that could not read a
device's software also answered with an empty list, which the sync read as
"nothing installed" and deleted the stored inventory.
"""
from unittest import mock

from django.utils import timezone

from integrations.models import RMMDevice, RMMSoftware
from integrations.providers.rmm_base import ProviderError
from integrations.sync import RMMSync
from integrations.tests_rmm_association import PROVIDERS, _Base

OTHERS = ('ninjaone', 'datto_rmm', 'atera', 'connectwise_automate')
SW = [{'external_id': 'sw-1', 'name': 'Notepad++', 'version': '8.6', 'vendor': 'Don Ho'}]


class SoftwareSyncTests(_Base):

    def device(self, conn, ext='dev-1', raw=None):
        return RMMDevice.objects.create(
            organization=self.a, connection=conn, external_id=ext, device_name='PC-1',
            last_seen=timezone.now(), raw_data=raw or {})

    def test_every_provider_gets_the_arguments_its_client_takes(self):
        for provider in OTHERS:
            with self.subTest(provider=provider):
                conn = self.connection(provider)
                dev = self.device(conn)
                cls = PROVIDERS[provider][0]
                # autospec keeps the real signature, so a stray uuid= raises TypeError.
                with mock.patch.object(cls, 'list_software', autospec=True, return_value=SW) as ls:
                    syncer = RMMSync(conn)
                    syncer.sync_software()
                ls.assert_called_once_with(mock.ANY, 'dev-1')
                self.assertEqual(list(RMMSoftware.objects.filter(device=dev).values_list('name', flat=True)),
                                 ['Notepad++'])
                self.assertEqual(syncer.stats['software']['errors'], 0)

    def test_tactical_keeps_numeric_key_and_uuid(self):
        conn = self.connection('tactical_rmm')
        self.device(conn, ext='agent-uuid', raw={'id': 42})
        with mock.patch.object(PROVIDERS['tactical_rmm'][0], 'list_software', autospec=True,
                               return_value=SW) as ls:
            RMMSync(conn).sync_software()
        ls.assert_called_once_with(mock.ANY, '42', uuid='agent-uuid')

    def test_a_failed_read_keeps_stored_software(self):
        for provider in OTHERS + ('tactical_rmm',):
            with self.subTest(provider=provider):
                conn = self.connection(provider)
                dev = self.device(conn)
                RMMSoftware.objects.create(organization=self.a, connection=conn, device=dev,
                                           external_id='old', name='Kept App', version='1')
                cls = PROVIDERS[provider][0]
                with mock.patch.object(cls, '_make_request', side_effect=ConnectionError('timeout')):
                    syncer = RMMSync(conn)
                    syncer.sync_software()
                self.assertTrue(RMMSoftware.objects.filter(device=dev, name='Kept App').exists())
                self.assertEqual(syncer.stats['software']['errors'], 1)

    def test_providers_raise_instead_of_answering_empty(self):
        for provider in OTHERS + ('tactical_rmm',):
            with self.subTest(provider=provider):
                conn = self.connection(provider)
                p = RMMSync(conn).provider
                with mock.patch.object(type(p), '_make_request', side_effect=ConnectionError('down')):
                    with self.assertRaises(ProviderError):
                        p.list_software('dev-1')
