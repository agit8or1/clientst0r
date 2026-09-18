"""A sync that drops records must not report success.

Both sync classes catch per-record failures, count them and carry on — right,
since one malformed record should not abandon the run. But they then wrote
`last_sync_status = 'success'` unconditionally, so a sync in which *every*
record failed reported success with an empty `last_error` and a green tick in
the UI.

The incremental cursor compounded it. `updated_since` is taken from
`last_sync_at` only when the last status was 'success', so a run that silently
"succeeded" while dropping every record moved the cursor past them — and the
next run asked only for things changed since. Those records were never offered
again unless they changed upstream. Permanent data loss, reported as success.
"""
from unittest import mock

from django.test import TestCase

from core.models import Organization
from integrations.models import PSAConnection, RMMConnection
from integrations.status import connection_status
from integrations.sync import PSASync, RMMSync, summarise_errors


def psa_connection(org):
    conn = PSAConnection(
        organization=org, provider_type='connectwise_manage', name='cw',
        base_url='https://psa.example.com',
        sync_companies=True, sync_contacts=False, sync_tickets=False)
    conn.set_credentials({'company_id': 'x', 'public_key': 'p', 'private_key': 'q'})
    conn.save()
    return conn


def run_psa_sync(conn, companies, upsert_side_effect=None):
    s = PSASync(conn)
    with mock.patch.object(type(s.provider), 'test_connection', return_value=True), \
         mock.patch.object(type(s.provider), 'list_companies', return_value=companies), \
         mock.patch.object(PSASync, '_upsert_company',
                           side_effect=upsert_side_effect or (lambda d: None)):
        return s.sync_all()


class PartialSyncIsReportedTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Client', slug='sync-client')
        self.conn = psa_connection(self.org)
        self.records = [{'external_id': f'c{i}', 'name': f'Co{i}'} for i in range(5)]

    def test_a_sync_that_drops_every_record_is_not_success(self):
        run_psa_sync(self.conn, self.records, upsert_side_effect=ValueError('boom'))
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'partial')

    def test_the_connection_says_what_was_dropped(self):
        run_psa_sync(self.conn, self.records, upsert_side_effect=ValueError('boom'))
        self.conn.refresh_from_db()
        self.assertIn('5 companies', self.conn.last_error)
        self.assertIn('failed to sync', self.conn.last_error)

    def test_the_next_run_retries_the_dropped_records(self):
        """
        The cursor is only honoured after a 'success', so recording the truth
        is also what makes the failures retryable — the next run asks for
        everything rather than only what changed since.
        """
        run_psa_sync(self.conn, self.records, upsert_side_effect=ValueError('boom'))
        self.conn.refresh_from_db()

        seen = {}
        s = PSASync(self.conn)

        def _capture(updated_since=None):
            seen['updated_since'] = updated_since
            return []

        with mock.patch.object(type(s.provider), 'test_connection', return_value=True), \
             mock.patch.object(type(s.provider), 'list_companies', side_effect=_capture):
            s.sync_all()

        self.assertIsNone(seen['updated_since'],
                          'the next sync skipped the records that failed')

    def test_a_clean_sync_still_reports_success_and_stays_incremental(self):
        run_psa_sync(self.conn, self.records)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'success')
        self.assertEqual(self.conn.last_error, '')

        seen = {}
        s = PSASync(self.conn)

        def _capture(updated_since=None):
            seen['updated_since'] = updated_since
            return []

        with mock.patch.object(type(s.provider), 'test_connection', return_value=True), \
             mock.patch.object(type(s.provider), 'list_companies', side_effect=_capture):
            s.sync_all()

        self.assertIsNotNone(seen['updated_since'],
                             'a clean sync should stay incremental')

    def test_one_bad_record_among_many_is_still_partial(self):
        calls = {'n': 0}

        def _sometimes(data):
            calls['n'] += 1
            if calls['n'] == 3:
                raise ValueError('one bad row')

        stats = run_psa_sync(self.conn, self.records, upsert_side_effect=_sometimes)
        self.conn.refresh_from_db()
        self.assertEqual(stats['companies']['errors'], 1)
        self.assertEqual(self.conn.last_sync_status, 'partial')

    def test_a_transport_failure_is_still_an_error_not_a_partial(self):
        s = PSASync(self.conn)
        with mock.patch.object(type(s.provider), 'test_connection', return_value=True), \
             mock.patch.object(type(s.provider), 'list_companies',
                               side_effect=RuntimeError('API down')):
            with self.assertRaises(RuntimeError):
                s.sync_all()
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.last_sync_status, 'error')


class SummariseErrorsTests(TestCase):

    def test_no_errors_is_empty(self):
        self.assertEqual(summarise_errors(
            {'companies': {'created': 3, 'updated': 0, 'errors': 0}}), '')

    def test_it_names_each_entity_type(self):
        text = summarise_errors({
            'companies': {'errors': 2}, 'contacts': {'errors': 0},
            'tickets': {'errors': 7},
        })
        self.assertIn('2 companies', text)
        self.assertIn('7 tickets', text)
        self.assertNotIn('contacts', text)


class PartialShowsOnTheDashboardTests(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name='Client', slug='sync-dash')
        self.conn = psa_connection(self.org)

    def test_partial_is_its_own_state_not_broken(self):
        """
        A partial sync writes its summary into `last_error`, and the broken
        branch keys on that field being non-empty — so read in the wrong order
        every partial sync would report as broken.
        """
        self.conn.last_sync_status = 'partial'
        self.conn.last_error = '5 companies failed to sync'
        self.conn.save()
        status = connection_status(self.conn)
        self.assertEqual(status['state'], 'partial')
        self.assertIn('retry', status['tooltip'])

    def test_a_real_error_is_still_broken(self):
        self.conn.last_sync_status = 'error'
        self.conn.last_error = 'API down'
        self.conn.save()
        self.assertEqual(connection_status(self.conn)['state'], 'broken')

    def test_a_clean_sync_is_still_working(self):
        from django.utils import timezone
        self.conn.last_sync_status = 'success'
        self.conn.last_error = ''
        self.conn.last_sync_at = timezone.now()
        self.conn.save()
        self.assertEqual(connection_status(self.conn)['state'], 'working')
