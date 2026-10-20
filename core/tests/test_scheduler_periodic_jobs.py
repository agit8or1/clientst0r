"""Every periodic management command is owned by the in-app scheduler (v3.17.599).

Before this release the periodic PSA/docs/field-ops/etc. commands ran from a
crontab that deploy/update_instructions.sh appended to (install.sh and Docker
installed none), or from nothing at all: psa_generate_recurring_invoices,
psa_sla_workflow_tick, kb_review_reminders and others were written "for cron"
and never scheduled anywhere.

Because psa_generate_recurring_invoices had never run, switching it on must not
back-bill the periods it missed: the scheduler runs it with --no-catch-up.
"""
import io
import subprocess
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings as django_settings
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.management.commands.run_scheduler import COMMAND_TASKS
from core.models import Organization, ScheduledTask
from psa.models import Contract, Invoice


# Every command found to be meant for periodic running, by the command name.
PERIODIC_COMMANDS = {
    # never scheduled anywhere
    'psa_generate_recurring_invoices',
    'psa_sla_workflow_tick',
    'kb_review_reminders',
    'psa_escalate_idle_approvals',
    'psa_run_recurring_purchases',
    'psa_generate_workflow_suggestions',
    'auto_document_field_visits',
    'psa_advance_subscription_lifecycle',
    'psa_apply_late_fees',
    'prune_technician_locations',
    'check_incident_sla_breaches',
    'recompute_exposure_scores',
    'assets_warranty_alerts',
    'assets_capture_baselines',
    'assets_generate_remediation_suggestions',
    'send_compliance_recertifications',
    'sync_network_assets',
    'update_geoip_db',
    'check_wans',
    # previously only in the crontab update_instructions.sh installed
    'psa_run_recurring_tickets',
    'psa_poll_email',
    'psa_send_outbound',
    'psa_auto_renew_contracts',
    'psa_auto_replenish_suggestions',
    'sync_distributors',
    'run_scheduled_reports',
    'poll_security_alerts',
}

# The crontab cadences these had, kept by the scheduler defaults.
CRONTAB_CADENCES = {
    'psa_run_recurring_tickets': 15,
    'psa_poll_email': 5,
    'psa_send_outbound': 5,
    'psa_auto_renew_contracts': 1440,
    'psa_auto_replenish_suggestions': 1440,
    'sync_distributors': 60,
    'run_scheduled_reports': 15,
    'poll_security_alerts': 5,
}


def _defaults_by_type():
    return {d['task_type']: d for d in ScheduledTask.PERIODIC_COMMAND_DEFAULTS}


def _make_due(task_type):
    ScheduledTask.get_or_create_defaults()
    ScheduledTask.objects.update(enabled=False)
    task = ScheduledTask.objects.get(task_type=task_type)
    task.enabled = True
    task.last_status = 'pending'
    task.next_run_at = timezone.now() - timedelta(minutes=5)
    task.save()
    return task


def _run_scheduler_with(side_effect=None):
    """Run the real scheduler with every other call_command mocked."""
    real = call_command

    def _dispatch(name, *a, **kw):
        if name == 'run_scheduler':
            return real(name, *a, **kw)
        if side_effect is not None:
            return side_effect(name, *a, **kw)
        return None

    with mock.patch('django.core.management.call_command',
                    side_effect=_dispatch) as cc:
        real('run_scheduler', verbosity=0, stdout=io.StringIO())
    return cc


class RegistryTests(TestCase):

    def test_every_periodic_command_is_a_scheduler_task(self):
        registered = {cmd for cmd, _args in COMMAND_TASKS.values()}
        self.assertEqual(PERIODIC_COMMANDS - registered, set())

    def test_every_registered_task_is_a_valid_choice_with_a_default(self):
        choices = {k for k, _ in ScheduledTask.TASK_TYPES}
        defaults = _defaults_by_type()
        for task_type in COMMAND_TASKS:
            with self.subTest(task_type=task_type):
                self.assertIn(task_type, choices)
                if task_type != 'rmm_sync':  # seeded by the base defaults
                    self.assertIn(task_type, defaults)

    def test_every_registered_command_exists(self):
        commands = get_commands()
        for task_type, (command, _args) in COMMAND_TASKS.items():
            with self.subTest(task_type=task_type):
                self.assertIn(command, commands)

    def test_crontab_cadences_are_kept(self):
        defaults = _defaults_by_type()
        for task_type, minutes in CRONTAB_CADENCES.items():
            with self.subTest(task_type=task_type):
                self.assertEqual(defaults[task_type]['interval_minutes'], minutes)

    def test_sla_tick_runs_every_five_minutes(self):
        self.assertEqual(_defaults_by_type()['psa_sla_workflow_tick']['interval_minutes'], 5)

    def test_late_fees_are_opt_in(self):
        self.assertFalse(_defaults_by_type()['psa_apply_late_fees']['enabled'])

    def test_the_scheduler_bills_without_catch_up(self):
        command, args = COMMAND_TASKS['psa_generate_recurring_invoices']
        self.assertEqual(command, 'psa_generate_recurring_invoices')
        self.assertIn('--no-catch-up', args)


class SeedingTests(TestCase):

    def test_seeding_is_idempotent(self):
        ScheduledTask.get_or_create_defaults()
        first = ScheduledTask.objects.count()
        ScheduledTask.get_or_create_defaults()
        self.assertEqual(ScheduledTask.objects.count(), first)
        for task_type in COMMAND_TASKS:
            self.assertEqual(
                ScheduledTask.objects.filter(task_type=task_type).count(), 1)

    def test_seeding_leaves_operator_changes_alone(self):
        ScheduledTask.get_or_create_defaults()
        ScheduledTask.objects.filter(task_type='psa_poll_email').update(
            enabled=False, interval_minutes=30)
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='psa_poll_email')
        self.assertFalse(task.enabled)
        self.assertEqual(task.interval_minutes, 30)

    def test_a_newly_seeded_task_is_not_due_until_one_interval_out(self):
        ScheduledTask.objects.filter(task_type='psa_poll_email').delete()
        ScheduledTask.get_or_create_defaults()
        task = ScheduledTask.objects.get(task_type='psa_poll_email')
        self.assertIsNotNone(task.next_run_at)
        self.assertFalse(task.should_run())
        task.next_run_at = timezone.now() - timedelta(seconds=1)
        self.assertTrue(task.should_run())

    def test_the_scheduler_seeds_missing_rows_without_running_them(self):
        ScheduledTask.objects.filter(task_type__in=list(COMMAND_TASKS)).delete()
        ScheduledTask.objects.update(enabled=False)
        cc = _run_scheduler_with()
        for task_type in COMMAND_TASKS:
            self.assertTrue(ScheduledTask.objects.filter(task_type=task_type).exists())
        called = {c.args[0] for c in cc.call_args_list} - {'run_scheduler'}
        self.assertEqual(called, set())


class DispatchTests(TestCase):

    def test_each_task_type_calls_its_command(self):
        for task_type, (command, args) in COMMAND_TASKS.items():
            with self.subTest(task_type=task_type):
                task = _make_due(task_type)
                cc = _run_scheduler_with()
                calls = [c for c in cc.call_args_list if c.args[0] != 'run_scheduler']
                self.assertEqual(len(calls), 1, calls)
                self.assertEqual(calls[0].args, (command, *args))
                task.refresh_from_db()
                self.assertEqual(task.last_status, 'success')

    def test_a_failing_command_is_recorded_as_failed(self):
        task = _make_due('psa_poll_email')

        def _boom(name, *a, **kw):
            raise CommandError('IMAP login failed')

        _run_scheduler_with(_boom)
        task.refresh_from_db()
        self.assertEqual(task.last_status, 'failed')
        self.assertIn('IMAP login failed', task.last_error)
        self.assertIsNotNone(task.next_run_at)


def _contract(org, **kw):
    today = date.today()
    defaults = dict(
        organization=org, client_org=org, name='Retainer', status='active',
        billing_frequency='monthly', recurring_amount=Decimal('500.00'),
        start_date=today - relativedelta(years=2), next_billing_date=today,
        auto_renew=False)
    defaults.update(kw)
    return Contract.objects.create(**defaults)


class RecurringInvoiceCatchUpGuardTests(TestCase):
    """The scheduled path bills the current period only, never back-bills."""

    def setUp(self):
        self.org = Organization.objects.create(name='Client', slug='sched-billing')
        self.today = date.today()
        self.current = _contract(self.org, name='Up to date')
        self.behind = _contract(
            self.org, name='Three behind',
            next_billing_date=self.today - relativedelta(months=3))

    def _invoices(self, c):
        return Invoice.objects.filter(source_contract=c).count()

    def _scheduled_run(self):
        """Run the real command through the real scheduler path."""
        task = _make_due('psa_generate_recurring_invoices')
        real = call_command
        with mock.patch('django.core.management.call_command', side_effect=real):
            real('run_scheduler', verbosity=0, stdout=io.StringIO())
        task.refresh_from_db()
        return task

    def test_up_to_date_contract_is_invoiced_once(self):
        self._scheduled_run()
        self.assertEqual(self._invoices(self.current), 1)
        self.current.refresh_from_db()
        self.assertEqual(self.current.next_billing_date,
                         self.today + relativedelta(months=1))

    def test_three_periods_behind_is_not_invoiced_and_is_reported(self):
        task = self._scheduled_run()
        self.assertEqual(self._invoices(self.behind), 0)
        self.behind.refresh_from_db()
        self.assertEqual(self.behind.next_billing_date,
                         self.today - relativedelta(months=3))
        # Visible on Settings > Scheduler.
        self.assertEqual(task.last_status, 'failed')
        self.assertIn('Three behind', task.last_error)
        self.assertIn('not back-billed', task.last_error)
        # ...and the current-period invoice still went out in the same run.
        self.assertEqual(self._invoices(self.current), 1)

    def test_second_run_is_idempotent(self):
        self._scheduled_run()
        task = self._scheduled_run()
        self.assertEqual(self._invoices(self.current), 1)
        self.assertEqual(self._invoices(self.behind), 0)
        self.assertIn('Three behind', task.last_error)

    def test_all_current_run_records_success(self):
        self.behind.delete()
        task = self._scheduled_run()
        self.assertEqual(task.last_status, 'success')
        self.assertEqual(task.last_error, '')

    def test_a_few_days_late_is_still_the_current_period(self):
        late = _contract(self.org, name='Late',
                         next_billing_date=self.today - timedelta(days=3))
        with self.assertRaises(CommandError):  # raised for self.behind
            call_command('psa_generate_recurring_invoices', '--no-catch-up', stdout=io.StringIO())
        self.assertEqual(self._invoices(late), 1)

    def test_cancel_at_period_end_is_not_billed_on_the_scheduled_path(self):
        self.behind.delete()
        self.current.cancel_at_period_end = True
        self.current.save()
        call_command('psa_generate_recurring_invoices', '--no-catch-up', stdout=io.StringIO())
        self.assertEqual(self._invoices(self.current), 0)

    def test_dry_run_reports_without_raising(self):
        call_command('psa_generate_recurring_invoices', '--no-catch-up', '--dry-run', stdout=io.StringIO())
        self.assertEqual(Invoice.objects.count(), 0)

    def test_manual_run_without_the_flag_keeps_catching_up(self):
        call_command('psa_generate_recurring_invoices', stdout=io.StringIO())
        # Three missed periods plus the current one.
        self.assertEqual(self._invoices(self.behind), 4)
        self.assertEqual(self._invoices(self.current), 1)


_BEGIN = '# BEGIN legacy-cron-cleanup'
_END = '# END legacy-cron-cleanup'


class LegacyCrontabCleanupTests(SimpleTestCase):
    """update_instructions.sh removes the cron lines it used to add."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = (Path(django_settings.BASE_DIR) / 'deploy'
                      / 'update_instructions.sh').read_text(encoding='utf-8')
        cls.block = cls.script[cls.script.index(_BEGIN):cls.script.index(_END)]

    def run_block(self, crontab_text):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cronfile, writes = tmp / 'crontab', tmp / 'writes'
            if crontab_text is not None:
                cronfile.write_text(crontab_text)
            harness = f'''
set -euo pipefail
log() {{ echo "$1"; }}
crontab() {{
    if [ "$1" = "-l" ]; then
        [ -f {cronfile} ] || return 1
        cat {cronfile}
    else
        cat > {cronfile}.new && mv {cronfile}.new {cronfile}
        echo write >> {writes}
    fi
}}
{self.block}
'''
            r = subprocess.run(['bash', '-c', harness], capture_output=True,
                               text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return (cronfile.read_text() if cronfile.exists() else None,
                    writes.read_text().count('write') if writes.exists() else 0)

    LEGACY = (
        '*/15 * * * * /v/bin/python /app/manage.py psa_run_recurring_tickets >/dev/null 2>&1\n'
        '*/5 * * * * /v/bin/python /app/manage.py psa_poll_email >/dev/null 2>&1\n'
        '*/5 * * * * /v/bin/python /app/manage.py psa_send_outbound >/dev/null 2>&1\n'
        '30 2 * * * /v/bin/python /app/manage.py psa_auto_renew_contracts >/dev/null 2>&1\n'
        '0 * * * * /v/bin/python /app/manage.py sync_distributors >/dev/null 2>&1\n'
        '*/15 * * * * /v/bin/python /app/manage.py run_scheduled_reports >/dev/null 2>&1\n'
        '0 6 * * * /v/bin/python /app/manage.py psa_auto_replenish_suggestions >/dev/null 2>&1\n'
        '*/5 * * * * /v/bin/python /app/manage.py poll_security_alerts >/dev/null 2>&1\n'
    )
    KEEP = ('* * * * * /app/scripts/check_update_trigger.sh\n'
            '0 3 * * * /usr/local/bin/my-own-backup.sh\n')

    def test_legacy_lines_are_removed_and_others_kept(self):
        after, writes = self.run_block(self.KEEP + self.LEGACY)
        self.assertEqual(writes, 1)
        self.assertNotIn('manage.py psa_', after)
        self.assertNotIn('sync_distributors', after)
        self.assertNotIn('run_scheduled_reports', after)
        self.assertNotIn('poll_security_alerts', after)
        self.assertIn('check_update_trigger.sh', after)
        self.assertIn('my-own-backup.sh', after)

    def test_second_run_does_not_rewrite_the_crontab(self):
        after, _ = self.run_block(self.KEEP + self.LEGACY)
        again, writes = self.run_block(after)
        self.assertEqual(writes, 0)
        self.assertEqual(again, after)

    def test_only_legacy_lines_leaves_an_empty_crontab(self):
        after, writes = self.run_block(self.LEGACY)
        self.assertEqual(writes, 1)
        self.assertEqual(after.strip(), '')

    def test_no_crontab_at_all_is_left_alone(self):
        after, writes = self.run_block(None)
        self.assertEqual(writes, 0)
        self.assertIsNone(after)

    def test_the_script_no_longer_adds_periodic_cron_lines(self):
        for command in CRONTAB_CADENCES:
            with self.subTest(command=command):
                self.assertNotRegex(
                    self.script, rf'echo[^\n]*manage\.py {command}')
                self.assertNotRegex(
                    self.script, rf'=".*manage\.py {command}')


class DockerRunsTheSchedulerTests(SimpleTestCase):

    def test_compose_has_a_scheduler_service(self):
        base = Path(django_settings.BASE_DIR)
        compose = (base / 'docker-compose.yml').read_text(encoding='utf-8')
        self.assertIn('\n  scheduler:\n', compose)
        self.assertIn('manage.py run_scheduler', compose)
        self.assertIn('CLIENTST0R_SKIP_SETUP', compose)
        entry = (base / 'docker-entrypoint.sh').read_text(encoding='utf-8')
        self.assertIn('CLIENTST0R_SKIP_SETUP', entry)
