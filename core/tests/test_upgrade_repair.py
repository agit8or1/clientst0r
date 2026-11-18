"""v3.17.709: repair an unfinished upgrade from Settings -> Updates.

What went wrong: v3.17.706 stopped at "migrating" (a migration graph bug in
that revision). Resume re-ran the same broken revision, and Apply stayed
disabled, so the only way out was the command line. Repair finishes the
unfinished upgrade with a newer build that contains the stuck revision,
reusing the verified pre-upgrade backup."""
import json
import subprocess
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.upgrade import apply as upgrade_apply
from core.upgrade import channels, journal
from core.upgrade.revision import Target

from .test_upgrade_pipeline import SHA1, SHA2, TEST_MIDDLEWARE, ApplyPipelineTests, _TmpMixin

SHA3 = '3' * 40


def _git(ancestor=True):
    def run(*args, **kwargs):
        rc = 0
        if args[:2] == ('merge-base', '--is-ancestor'):
            rc = 0 if ancestor else 1
        return subprocess.CompletedProcess(list(args), rc, '', '')
    return run


class RepairPipelineTests(_TmpMixin, TestCase):
    # The same patched pipeline as ApplyPipelineTests (without re-running its tests).
    setUp = ApplyPipelineTests.setUp
    _script = ApplyPipelineTests._script

    def _stuck(self):
        journal.begin(target=Target('preview', 'main', SHA2).as_dict(), prev_sha=SHA1,
                      prev_version='3.17.702', backup=str(self.snap))
        journal.stage('migrating', backup=str(self.snap))
        journal.finish('failed', error='database migration failed')

    def test_repair_finishes_with_the_newer_build_and_keeps_the_backup(self):
        self._stuck()
        with mock.patch.object(upgrade_apply.snapshot, 'is_verified', return_value=(True, 'verified')), \
                mock.patch('core.upgrade.revision.git', side_effect=_git(True)), \
                self._script('echo "sha=$CLIENTST0R_TARGET_SHA"\n'):
            r = upgrade_apply.run(None, retarget=Target('preview', 'main', SHA3), allow_preview=True)
        self.assertTrue(r['success'], r)
        out = '\n'.join(r['output'])
        self.assertIn(f'sha={SHA3}', out)
        self.assertIn('Repairing the upgrade', out)
        self.assertIn('Reusing the pre-upgrade backup', out)
        self.m['create'].assert_not_called()
        j = journal.read()
        self.assertEqual(j['status'], 'complete')
        self.assertEqual(j['target']['sha'], SHA3)
        self.assertEqual(j['retargeted_from'][0]['sha'], SHA2)
        self.assertEqual(j['prev_version'], '3.17.702')

    def test_build_without_the_stuck_revision_is_refused_and_journal_untouched(self):
        self._stuck()
        before = journal.read()
        with mock.patch('core.upgrade.revision.git', side_effect=_git(False)), \
                self._script('touch "$0.ran"\n') as script:
            r = upgrade_apply.run(None, retarget=Target('preview', 'main', SHA3), allow_preview=True)
        self.assertTrue(r['refused'])
        self.assertIn('does not contain', r['error'])
        script.assert_not_called()
        after = journal.read()
        self.assertEqual(after['target'], before['target'])
        self.assertEqual(after['status'], 'failed')

    def test_repair_with_the_stuck_revision_is_refused(self):
        self._stuck()
        r = upgrade_apply.run(None, retarget=Target('preview', 'main', SHA2), allow_preview=True)
        self.assertTrue(r['refused'])
        self.assertIn('use Resume', r['error'])

    def test_repair_to_preview_follows_the_channel_rule(self):
        self._stuck()
        with mock.patch('core.upgrade.revision.git', side_effect=_git(True)):
            r = upgrade_apply.run(None, retarget=Target('preview', 'main', SHA3))
        self.assertTrue(r['refused'])
        self.assertIn('channel', r['error'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class RepairViewTests(_TmpMixin, TestCase):
    def setUp(self):
        self.tmp = self.make_tmp()
        o = override_settings(UPGRADE_BACKUP_DIR=self.tmp / 'backups')
        o.enable()
        self.addCleanup(o.disable)
        self.su = get_user_model().objects.create_user('rep_su', 'r@x.invalid', 'pw',
                                                       is_superuser=True, is_staff=True)
        self.client.force_login(self.su)
        channels.clear_cache()
        p = mock.patch('core.update_progress.UpdateProgress')
        p.start()
        self.addCleanup(p.stop)
        journal.begin(target=Target('preview', 'main', SHA2).as_dict(), prev_sha=SHA1,
                      prev_version='3.17.702')
        journal.stage('migrating')
        journal.finish('failed', error='database migration failed')
        self.offer = {'kind': 'preview', 'ref': 'main', 'sha': SHA3, 'version': '3.17.709'}

    def _info(self):
        return {'update_available': True, 'target': self.offer, 'current_version': '3.17.702',
                'channels': {'target': self.offer, 'preview': None}}

    def _post(self, body):
        return self.client.post(reverse('core:repair_update'), data=json.dumps(body),
                                content_type='application/json')

    def test_repair_starts_with_the_offered_build(self):
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info()), \
                mock.patch('core.upgrade.revision.git', side_effect=_git(True)), \
                mock.patch('core.updater.UpdateService.perform_update') as perform, \
                mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'repair', 'stuck_sha': SHA2, 'kind': 'preview', 'ref': 'main',
                            'sha': SHA3})
            self.assertEqual(r.status_code, 200, r.content)
            thread.call_args.kwargs['target']()
        kw = perform.call_args.kwargs
        self.assertTrue(kw['resume'])
        self.assertEqual(kw['retarget'].sha, SHA3)
        self.assertTrue(kw['allow_preview'])

    def test_resume_starts_without_a_target(self):
        with mock.patch('core.updater.UpdateService.perform_update') as perform, \
                mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'resume', 'stuck_sha': SHA2})
            self.assertEqual(r.status_code, 200, r.content)
            thread.call_args.kwargs['target']()
        self.assertTrue(perform.call_args.kwargs['resume'])
        self.assertIsNone(perform.call_args.kwargs['retarget'])

    def test_build_not_offered_is_refused(self):
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info()), \
                mock.patch('core.upgrade.revision.git', side_effect=_git(True)), \
                mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'repair', 'stuck_sha': SHA2, 'kind': 'preview', 'ref': 'main',
                            'sha': '4' * 40})
        self.assertEqual(r.status_code, 409)
        thread.assert_not_called()

    def test_stale_page_is_refused(self):
        with mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'resume', 'stuck_sha': SHA1})
        self.assertEqual(r.status_code, 409)
        thread.assert_not_called()

    def test_nothing_to_repair(self):
        journal.finish('complete')
        with mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'resume', 'stuck_sha': SHA2})
        self.assertEqual(r.status_code, 409)
        thread.assert_not_called()

    def test_superuser_only(self):
        u = get_user_model().objects.create_user('rep_staff', 's@x.invalid', 'pw', is_staff=True)
        self.client.force_login(u)
        with mock.patch('threading.Thread') as thread:
            r = self._post({'mode': 'resume', 'stuck_sha': SHA2})
        self.assertNotEqual(r.status_code, 200)
        thread.assert_not_called()

    def test_page_offers_repair_and_resume(self):
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value=self._info()), \
                mock.patch('core.upgrade.revision.git', side_effect=_git(True)):
            r = self.client.get(reverse('core:system_updates'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="repairBtn"', html)
        self.assertIn(f'data-sha="{SHA3}"', html)
        self.assertIn('id="resumeBtn"', html)
