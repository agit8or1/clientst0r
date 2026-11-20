"""SR-07: tamper-evident audit chain, archived retention, no admin delete."""
import gzip
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from audit import chain
from audit.models import AuditChainState, AuditLog


def _log(n=1, **kw):
    return [AuditLog.objects.create(action='update', username='u', description=f'entry {i}', **kw)
            for i in range(n)]


class ChainTests(TestCase):
    def test_seal_then_verify(self):
        _log(5)
        self.assertEqual(chain.seal(), 5)
        self.assertEqual(chain.seal(), 0)
        ok, problems = chain.verify()
        self.assertTrue(ok, problems)
        state = AuditChainState.get()
        self.assertEqual(state.head_seq, 5)
        self.assertTrue(state.verify_ok)
        self.assertEqual(list(AuditLog.objects.order_by('pk').values_list('chain_seq', flat=True)), [1, 2, 3, 4, 5])

    def test_changed_row_is_detected(self):
        rows = _log(4)
        chain.seal()
        AuditLog.objects.filter(pk=rows[1].pk).update(description='nothing to see')
        ok, problems = chain.verify()
        self.assertFalse(ok)
        self.assertIn('#2', problems[0])
        self.assertFalse(AuditChainState.get().verify_ok)

    def test_removed_row_is_detected(self):
        rows = _log(4)
        chain.seal()
        AuditLog.objects.filter(pk=rows[1].pk).delete()
        ok, problems = chain.verify()
        self.assertFalse(ok)
        self.assertTrue(any('missing' in p for p in problems), problems)

    def test_removed_newest_rows_are_detected(self):
        rows = _log(4)
        chain.seal()
        AuditLog.objects.filter(pk__in=[rows[2].pk, rows[3].pk]).delete()
        ok, problems = chain.verify()
        self.assertFalse(ok)
        self.assertTrue(any('recorded head' in p for p in problems), problems)

    def test_row_slipped_into_history_is_detected(self):
        rows = _log(3)
        gap = rows[1].pk
        AuditLog.objects.filter(pk=gap).delete()
        chain.seal()
        self.assertTrue(chain.verify()[0])
        AuditLog.objects.create(pk=gap, action='login', username='ghost')
        ok, problems = chain.verify()
        self.assertFalse(ok)
        self.assertTrue(any('among sealed history' in p for p in problems), problems)

    def test_recomputed_plain_hash_does_not_verify(self):
        """Someone with only the database cannot re-seal a changed row."""
        rows = _log(2)
        chain.seal()
        row = AuditLog.objects.get(pk=rows[1].pk)
        row.description = 'forged'
        import hashlib
        prev = AuditLog.objects.get(pk=rows[0].pk).chain_mac
        forged = hashlib.sha256(prev.encode() + b'\n' + chain.canonical(row)).hexdigest()
        AuditLog.objects.filter(pk=row.pk).update(description='forged', chain_mac=forged)
        self.assertFalse(chain.verify()[0])

    def test_key_rotation_keeps_old_entries_verifiable(self):
        with override_settings(APP_MASTER_KEY='old-master-key-for-tests'):
            _log(2)
            chain.seal()
        with override_settings(APP_MASTER_KEY='new-master-key-for-tests',
                               APP_MASTER_KEY_PREVIOUS='old-master-key-for-tests'):
            _log(2)
            chain.seal()
            ok, problems = chain.verify()
            self.assertTrue(ok, problems)
        with override_settings(APP_MASTER_KEY='new-master-key-for-tests', APP_MASTER_KEY_PREVIOUS='',
                               SECRET_KEY='unrelated-secret-key-for-tests'):
            ok, problems = chain.verify()
            self.assertFalse(ok)
            self.assertIn('unknown key', problems[0])

    def test_tick_verifies_once_a_day(self):
        _log(1)
        sealed, verified = chain.tick()
        self.assertEqual((sealed, verified), (1, True))
        self.assertEqual(chain.tick(), (0, None))


class RetentionTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch('audit.chain.archive_dir', return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def _aged(self, n, days):
        rows = _log(n)
        AuditLog.objects.filter(pk__in=[r.pk for r in rows]).update(
            timestamp=timezone.now() - timedelta(days=days))
        return rows

    def test_prune_archives_first_and_chain_still_verifies(self):
        old = self._aged(3, 400)
        _log(2)
        deleted, path = chain.prune_before(timezone.now() - timedelta(days=365))
        self.assertEqual(deleted, 3)
        self.assertFalse(AuditLog.objects.filter(pk__in=[r.pk for r in old]).exists())
        with gzip.open(path, 'rt') as fh:
            archived = [json.loads(line) for line in fh]
        self.assertEqual([a['id'] for a in archived], [r.pk for r in old])
        self.assertTrue(all(a['chain_mac'] for a in archived))
        self.assertEqual(oct(Path(path).stat().st_mode & 0o777), '0o600')
        state = AuditChainState.get()
        self.assertEqual(state.base_seq, 3)
        ok, problems = chain.verify()
        self.assertTrue(ok, problems)
        _log(1)
        chain.seal()
        self.assertTrue(chain.verify()[0])

    def test_prune_refused_when_chain_is_broken(self):
        rows = self._aged(3, 400)
        chain.seal()
        AuditLog.objects.filter(pk=rows[0].pk).update(description='edited')
        with self.assertRaises(chain.PruneRefused):
            chain.prune_before(timezone.now() - timedelta(days=365))
        self.assertEqual(AuditLog.objects.count(), 3)

    def test_failed_archive_deletes_nothing(self):
        self._aged(3, 400)
        with mock.patch('audit.chain.export', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                chain.prune_before(timezone.now() - timedelta(days=365))
        self.assertEqual(AuditLog.objects.count(), 3)

    def test_command_refuses_short_retention(self):
        with self.assertRaises(CommandError):
            call_command('audit_chain', 'prune', '--days', '5')


class AdminAndWiringTests(TestCase):
    def test_admin_cannot_delete(self):
        admin = site._registry[AuditLog]
        su = User.objects.create_superuser('root', 'r@example.com', 'x-Long-passphrase-1')
        self.assertFalse(admin.has_delete_permission(SimpleNamespace(user=su)))

    def test_scheduler_runs_the_chain(self):
        from core.management.commands.run_scheduler import COMMAND_TASKS
        from core.models import ScheduledTask
        self.assertEqual(COMMAND_TASKS['audit_chain'], ('audit_chain', ['tick']))
        ScheduledTask.get_or_create_defaults()
        self.assertTrue(ScheduledTask.objects.filter(task_type='audit_chain', enabled=True).exists())

    def test_broken_chain_is_a_critical_system_warning(self):
        from core.system_warnings import _warnings_from_audit_chain
        self.assertEqual(_warnings_from_audit_chain(), [])
        rows = _log(2)
        chain.seal()
        AuditLog.objects.filter(pk=rows[0].pk).update(username='someone-else')
        chain.verify()
        w = _warnings_from_audit_chain()
        self.assertEqual(w[0]['severity'], 'critical')
