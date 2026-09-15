"""Backup key handling and default encryption.

Two defects this pins:

1. `manage.py backup` advertised itself as producing encrypted backups but
   `--encrypt` was opt-in and off, and the default output directory was
   `/tmp/clientst0r-backups` created at 0755. A full database dump went to a
   world-readable path in the clear.

2. backup and restore built their Fernet from `APP_MASTER_KEY.encode()`
   directly, while the rest of the vault normalises the key first (whitespace,
   URL-safe alphabet, padding). An unpadded key therefore worked everywhere in
   the application and failed at restore — the worst place to find out.
"""
import base64
import os

from django.core.management import load_command_class
from django.test import SimpleTestCase, override_settings

RAW = os.urandom(32)
STANDARD = base64.b64encode(RAW).decode()
UNPADDED = STANDARD.rstrip('=')
URLSAFE = base64.urlsafe_b64encode(RAW).decode()


class BackupDefaultsTests(SimpleTestCase):

    def _parser(self):
        cmd = load_command_class('core', 'backup')
        return cmd.create_parser('manage.py', 'backup')

    def test_encryption_is_on_by_default(self):
        opts = vars(self._parser().parse_args([]))
        self.assertTrue(
            opts['encrypt'],
            'backup would write the database in the clear unless asked not to',
        )

    def test_no_encrypt_is_still_available(self):
        opts = vars(self._parser().parse_args(['--no-encrypt']))
        self.assertFalse(opts['encrypt'])

    def test_default_output_is_not_world_readable_tmp(self):
        opts = vars(self._parser().parse_args([]))
        self.assertFalse(
            opts['output_dir'].startswith('/tmp'),
            'database dumps default into /tmp, which is world-readable and '
            'subject to tmpfiles cleanup',
        )


class MasterKeyShapeTests(SimpleTestCase):
    """Every key shape the vault accepts must also survive backup + restore."""

    def _roundtrip(self, key):
        with override_settings(APP_MASTER_KEY=key):
            from vault.encryption import get_fernet
            f = get_fernet()
            return f.decrypt(f.encrypt(b'database-dump')) == b'database-dump'

    def test_standard_base64_key(self):
        self.assertTrue(self._roundtrip(STANDARD))

    def test_urlsafe_base64_key(self):
        self.assertTrue(self._roundtrip(URLSAFE))

    def test_key_with_trailing_newline(self):
        self.assertTrue(self._roundtrip(STANDARD + '\n'))

    def test_unpadded_key_no_longer_breaks_restore(self):
        """This is the one that used to raise ValueError inside restore."""
        self.assertTrue(self._roundtrip(UNPADDED))

    def test_existing_backups_still_decrypt(self):
        """Backward compatibility is the whole point of routing through
        get_master_key rather than changing the key material. A backup written
        by the old `Fernet(APP_MASTER_KEY.encode())` must still restore."""
        from cryptography.fernet import Fernet
        for key in (STANDARD, URLSAFE, STANDARD + '\n'):
            token = Fernet(key.encode()).encrypt(b'old-backup')
            with override_settings(APP_MASTER_KEY=key):
                from vault.encryption import get_fernet
                self.assertEqual(
                    get_fernet().decrypt(token), b'old-backup',
                    f'a backup written with the old key handling ({key[:6]}...) '
                    f'no longer restores',
                )

    def test_a_bad_key_is_still_rejected(self):
        from vault.encryption import EncryptionError
        with override_settings(APP_MASTER_KEY=base64.b64encode(os.urandom(16)).decode()):
            from vault.encryption import get_fernet
            with self.assertRaises(EncryptionError):
                get_fernet()
