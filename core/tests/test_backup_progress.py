"""What the Apply progress view shows during the backup step (v3.17.667).

A large install spends minutes taking and test-restoring the pre-upgrade
backup; the view now names the part being done, the elapsed time and the
expected duration (from the previous backup's recorded timings).

The progress file used here is a temporary one: the real one in /tmp is
what a running install's Updates page reads.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.update_progress import BACKUP_PHASES, UpdateProgress
from core.upgrade import apply as upgrade_apply
from core.upgrade import preflight, snapshot
from core.upgrade.revision import Target

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]
SHA1 = '1' * 40
SHA2 = '2' * 40


def _tmp(test):
    tmp = Path(tempfile.mkdtemp(prefix='cs0r-progress-test-'))
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _progress(tmp):
    p = UpdateProgress(update_id='test')
    p.progress_file = tmp / 'progress.json'
    return p


def _fake_snapshot(root, name, *, db_bytes, media_bytes, db_s, media_s, verify_s, version='3.17.660'):
    d = Path(root) / name
    d.mkdir(parents=True)
    (d / 'manifest.json').write_text(json.dumps({
        'app_version': version, 'files': {},
        'sizes': {'database_bytes': db_bytes, 'media_bytes': media_bytes},
        'timings': {'database_seconds': db_s, 'media_seconds': media_s,
                    'create_seconds': db_s + media_s}}))
    (d / 'verification.json').write_text(json.dumps({'ok': True, 'duration_seconds': verify_s}))
    return d


class EstimateTests(SimpleTestCase):
    def setUp(self):
        self.root = _tmp(self) / 'backups'
        o = override_settings(UPGRADE_BACKUP_DIR=self.root)
        o.enable()
        self.addCleanup(o.disable)

    def test_without_history_uses_default_rates(self):
        est = snapshot.estimate(147 * 10**6, 349 * 10**6)
        self.assertIn('sizes', est['basis'])
        self.assertEqual(est['total'], est['database'] + est['media'] + est['verify'])
        self.assertGreater(est['total'], 60, 'a 500 MB backup is not instant')

    def test_scaled_from_the_previous_backup(self):
        # 100 MB DB in 10 s, 200 MB media in 40 s, verify of 300 MB in 60 s
        _fake_snapshot(self.root, 'snapshot-20261101-000000-v3.17.650', db_bytes=1, media_bytes=1,
                       db_s=99, media_s=99, verify_s=99)
        _fake_snapshot(self.root, 'snapshot-20261110-000000-v3.17.660', db_bytes=100e6,
                       media_bytes=200e6, db_s=10, media_s=40, verify_s=60)
        est = snapshot.estimate(200e6, 400e6)   # twice as big
        self.assertEqual((est['database'], est['media'], est['verify']), (20, 80, 120))
        self.assertIn('previous backup (v3.17.660, took 1 min 50 s)', est['basis'])

    def test_previous_without_timings_is_skipped(self):
        d = self.root / 'snapshot-20261111-000000-v3.17.600'
        d.mkdir(parents=True)
        (d / 'manifest.json').write_text(json.dumps({'files': {}}))
        self.assertIn('sizes', snapshot.estimate(1e6, 1e6)['basis'])

    def test_format_duration(self):
        self.assertEqual(snapshot.format_duration(42), '42 s')
        self.assertEqual(snapshot.format_duration(185), '3 min 05 s')
        self.assertEqual(snapshot.format_duration(1800), '30 min')


class ProgressFileTests(SimpleTestCase):
    def test_backup_phases_are_recorded_with_durations(self):
        p = _progress(_tmp(self))
        p.start(total_steps=8)
        p.step_start('Verified Backup')
        p.backup_begin({'database': 15, 'media': 35, 'verify': 62, 'total': 112,
                        'basis': 'estimated from the database and upload sizes'})
        b = p.get_progress()['backup']
        self.assertEqual(b['estimate_seconds'], 112)
        self.assertEqual([x['key'] for x in b['phases']], ['database', 'media', 'verify'])
        for i, (key, label) in enumerate(BACKUP_PHASES, start=1):
            p.backup_phase(key)
            b = p.get_progress()['backup']
            self.assertEqual((b['phase'], b['phase_label'], b['phase_index']), (key, label, i))
        p.backup_phase('nonsense')
        self.assertEqual(p.get_progress()['backup']['phase'], 'verify')
        p.backup_end()
        b = p.get_progress()['backup']
        self.assertEqual(b['phase'], '')
        self.assertEqual(set(b['done']), {'database', 'media', 'verify'})
        self.assertIn('finished_at', b)

    def test_labels(self):
        self.assertEqual(dict(BACKUP_PHASES), {
            'database': 'Copying the database',
            'media': 'Archiving uploaded files',
            'verify': 'Verifying (test restore)'})

    def test_phase_before_begin_is_ignored(self):
        p = _progress(_tmp(self))
        p.start()
        p.backup_phase('database')
        self.assertNotIn('backup', p.get_progress())


class ApplyReportsBackupProgressTests(TestCase):
    def setUp(self):
        self.tmp = _tmp(self)
        self.root = self.tmp / 'backups'
        o = override_settings(UPGRADE_BACKUP_DIR=self.root)
        o.enable()
        self.addCleanup(o.disable)
        self.progress = _progress(self.tmp)
        self.progress.start(total_steps=upgrade_apply.TOTAL_STEPS)
        self.seen = []

        def create(**kw):
            for part in ('database', 'media'):
                kw['phase'](part)
                self.seen.append(self.progress.get_progress()['backup']['phase_label'])
            d = self.root / 'snapshot-20261112-000000-v99.0.0'
            d.mkdir(parents=True)
            (d / 'manifest.json').write_text(json.dumps({'timings': {'create_seconds': 70}}))
            (d / 'verification.json').write_text(json.dumps({'duration_seconds': 50}))
            return d

        def verify(snap, out=None):
            self.seen.append(self.progress.get_progress()['backup']['phase_label'])
            return {'ok': True, 'level': 'restore-test', 'checks': []}

        patches = [
            mock.patch.object(upgrade_apply, 'is_git_install', return_value=True),
            mock.patch.object(upgrade_apply, 'head_sha', return_value=SHA1),
            mock.patch.object(upgrade_apply, 'check_remote_unchanged'),
            mock.patch.object(upgrade_apply, 'fetch'),
            mock.patch.object(upgrade_apply, 'verify_release_tag', return_value='Good signature'),
            mock.patch.object(upgrade_apply, 'version_at', return_value='99.0.0'),
            mock.patch.object(upgrade_apply.preflight, 'run',
                              return_value=[preflight.Check('disk space', 'ok', 'plenty')]),
            mock.patch.object(upgrade_apply.preflight, 'measure_sizes',
                              return_value=(147 * 2**20, 349 * 2**20)),
            mock.patch.object(upgrade_apply.snapshot, 'create', side_effect=create),
            mock.patch.object(upgrade_apply.snapshot, 'verify', side_effect=verify),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_backup_step_names_each_part_with_an_estimate(self):
        script = self.tmp / 'update.sh'
        script.write_text('#!/bin/bash\necho "Update complete!"\n')
        os.chmod(script, 0o700)
        with mock.patch.object(upgrade_apply, 'extract_to_private_file', return_value=script):
            r = upgrade_apply.run(Target('release', 'v99.0.0', SHA2), progress=self.progress)
        self.assertTrue(r['success'], r)
        self.assertEqual(self.seen, ['Copying the database', 'Archiving uploaded files',
                                     'Verifying (test restore)'])
        out = '\n'.join(r['output'])
        self.assertIn('database 147 MB, uploads 349 MB; expected to take about', out)
        self.assertIn('Backup: Copying the database (about', out)
        self.assertIn('Backup: Verifying (test restore) (about', out)
        self.assertIn('Backup took 2 min 00 s.', out)
        b = self.progress.get_progress()['backup']
        self.assertGreater(b['estimate_seconds'], 0)
        self.assertEqual(set(b['done']), {'database', 'media', 'verify'})

    def test_a_broken_estimate_does_not_stop_the_backup(self):
        script = self.tmp / 'update.sh'
        script.write_text('#!/bin/bash\necho "Update complete!"\n')
        os.chmod(script, 0o700)
        with mock.patch.object(upgrade_apply.preflight, 'measure_sizes', side_effect=OSError('x')), \
                mock.patch.object(upgrade_apply, 'extract_to_private_file', return_value=script):
            r = upgrade_apply.run(Target('release', 'v99.0.0', SHA2), progress=self.progress)
        self.assertTrue(r['success'], r)
        self.assertEqual(self.seen, ['Copying the database', 'Archiving uploaded files',
                                     'Verifying (test restore)'])
        self.assertIsNone(self.progress.get_progress()['backup']['estimate_seconds'])


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class ProgressViewTests(TestCase):
    def setUp(self):
        su = get_user_model().objects.create_user('prog_su', 'p@x.invalid', 'pw',
                                                  is_superuser=True, is_staff=True)
        self.client.force_login(su)
        self.tmp = _tmp(self)

    def test_progress_api_carries_the_server_clock(self):
        fake = _progress(self.tmp)
        fake.start()
        with mock.patch('core.update_progress.UpdateProgress', return_value=fake):
            data = self.client.get(reverse('core:update_progress_api')).json()
        self.assertIn('now', data)
        self.assertIsInstance(data['now'], float)

    def test_updates_page_has_the_backup_detail_without_inline_handlers(self):
        with mock.patch('core.updater.UpdateService.check_for_updates', return_value={
                'update_available': False, 'target': None, 'current_version': '1',
                'latest_version': '1', 'channels': {}}), \
                override_settings(UPGRADE_BACKUP_DIR=self.tmp / 'b'):
            html = self.client.get(reverse('core:system_updates')).content.decode()
        self.assertIn('id="backupDetail"', html)
        self.assertIn('function updateBackupDetail', html)
        self.assertIn('elapsed', html)
        step = html.split('data-step="backup"', 1)[1].split('data-step="git_pull"', 1)[0]
        self.assertNotIn('onclick', step)
