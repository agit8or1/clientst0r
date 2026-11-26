"""scripts/ux/seed_scale.py: the guards and a tiny generation run (113.7)."""
import importlib.util
import pathlib
import tempfile

from django.test import TestCase

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'scripts' / 'ux' / 'seed_scale.py'


def load():
    spec = importlib.util.spec_from_file_location('seed_scale_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SeedScaleGuardTests(TestCase):

    def test_guards(self):
        m = load()
        with self.assertRaises(SystemExit):
            m.check_target('/home/administrator/db.sqlite3')
        with self.assertRaises(SystemExit):
            m.check_target('/home/administrator/elsewhere.sqlite3')   # not under an allowed root
        with self.assertRaises(SystemExit):
            m.check_target('/etc/scale.sqlite3')
        with tempfile.TemporaryDirectory(dir='/var/tmp') as d:
            target = pathlib.Path(d) / 'new.sqlite3'
            self.assertEqual(m.check_target(target), target.resolve())      # absent: allowed
            target.touch()
            self.assertEqual(m.check_target(target), target.resolve())      # empty: allowed
            target.write_bytes(b'SQLite format 3\x00')
            with self.assertRaises(SystemExit):
                m.check_target(target)                                      # non-empty: refused

    def test_plan(self):
        m = load()
        self.assertEqual((m.plan('medium')['customers'], m.plan('medium')['endpoints']), (60, 1200))
        self.assertEqual(m.plan('xl', customers=7, endpoints=30)['tickets'], 360)


class SeedScaleGenerateTests(TestCase):

    def test_tiny_run(self):
        from django.core.management import call_command
        from assets.models import Asset
        from core.models import Organization
        from psa.models import Charge, Ticket, TicketComment, TicketTimeEntry
        from vault.models import Password
        call_command('psa_seed_defaults', verbosity=0)
        m = load()
        counts = dict(customers=2, endpoints=5, tickets=12, documents=8, credentials=4, contacts=4, invoices=4)
        out = m.generate(counts, with_rmm=True, log=lambda *_: None)
        self.assertEqual(out['customers'], 2)
        self.assertEqual(Asset.objects.count(), 5)
        self.assertEqual(Ticket.objects.count(), 12)
        self.assertEqual(Organization.objects.count(), 3)       # two customers + the MSP
        self.assertEqual(TicketComment.objects.count(), out['comments'])
        self.assertEqual(TicketTimeEntry.objects.count(), out['time_entries'])
        self.assertEqual(Password.objects.count(), 4)
        self.assertEqual(Charge.objects.count(), 24)
        # an encrypted value round-trips through the model API
        self.assertTrue(Password.objects.first().get_password().startswith('Placeholder-'))
