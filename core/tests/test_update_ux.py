"""Settings -> Updates wording: one name per build, one status while an
upgrade runs, and no stale "Update available" after installing it.

Covers: a commit that is a signed release tag is named as that release on
either channel (status line, Install button, running card, flash message),
also when its GitHub release page is not published yet; a commit that is not
a release is a testing build with its distance from the latest release; a
running upgrade shows its current stage and a checklist, never "Stopped",
and hides every "Update available" banner (navbar pill, dashboard status,
system warnings, Check now); a completed upgrade drops the cached update
check; interrupted and failed upgrades keep their recovery wording; the
channel explanation.

GitHub, origin and git are the stand-ins from test_update_versions.
"""
from __future__ import annotations

import os
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core.upgrade import apply as upgrade_apply
from core.upgrade import catalog, journal
from core.tests.test_update_versions import (
    DEFAULT_RELEASES, MAIN_SHA, TEST_MIDDLEWARE, FakeGitHub, _Base, _Resp, commit_of, obj_of,
    origin_tags, rel,
)


class MainAt(FakeGitHub):
    """FakeGitHub whose main head is `sha`."""

    def __init__(self, *a, main_sha=MAIN_SHA, **k):
        super().__init__(*a, **k)
        self.main_sha = main_sha

    def __call__(self, url, headers=None, timeout=None):
        if url.endswith('/commits/main'):
            self.calls.append((url, dict(headers or {})))
            return _Resp(200, {'sha': self.main_sha, 'commit': {
                'message': 'release: v3.17.694', 'committer': {'date': '2026-11-16T16:55:44Z'}}})
        return super().__call__(url, headers=headers, timeout=timeout)


RELEASE_694 = rel('v3.17.694', '2026-11-16T17:00:00Z', body='### Added\n- 694')


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class _PageBase(_Base):
    installed_version = '3.17.687'
    installed_sha = commit_of('v3.17.687')
    channel = 'preview'

    def setUp(self):
        super().setUp()
        self.su = get_user_model().objects.create_user('ux_su', 'ux@x.invalid', 'pw',
                                                       is_superuser=True, is_staff=True)
        self.client.force_login(self.su)
        for p in (mock.patch('core.update_progress.UpdateProgress'),
                  mock.patch.object(catalog, 'downgrade_compatibility',
                                    return_value=('safe', 'no schema change', ()))):
            p.start()
            self.addCleanup(p.stop)
        self.extra_tags = {}

    def patches(self):
        ps = super().patches()
        extra = self.extra_tags

        def tags():
            out = origin_tags(self.gh.releases, self.lightweight)
            out.update(extra)
            return out
        return [p for p in ps if getattr(p, 'attribute', None) != 'remote_tags'] + [
            mock.patch('core.upgrade.discovery.remote_tags', side_effect=tags)]

    def page(self):
        return self.run_patched(lambda: self.client.get(reverse('core:system_updates')).content.decode())

    def strip(self, html):
        return html.split('id="updSummary"', 1)[1].split('id="updVersions"', 1)[0]

    def journal_running(self, stage='preflight_ok', sha=None):
        journal.write({'status': 'running', 'stage': stage, 'pid': os.getpid(),
                       'prev_version': self.installed_version, 'prev_sha': self.installed_sha,
                       'target': {'kind': 'preview', 'ref': 'main', 'sha': sha or getattr(self.gh, 'main_sha', MAIN_SHA),
                                  'version': '3.17.694'},
                       'history': []})


class ReleaseLabellingTests(_PageBase):
    def test_main_head_that_is_a_published_release_is_named_as_the_release(self):
        self.gh = MainAt(DEFAULT_RELEASES + [RELEASE_694], main_sha=commit_of('v3.17.694'))
        state = self.resolve()
        t = state['target']
        # What gets installed is unchanged: main, pinned to the commit.
        self.assertEqual((t['kind'], t['ref'], t['sha']), ('preview', 'main', commit_of('v3.17.694')))
        d = catalog.describe_build(state, t['kind'], t['ref'], t['sha'], t['version'])
        self.assertEqual(d['label'], 'v3.17.694 · Official release')
        self.assertTrue(d['is_release'])
        from core.views import _update_status_line
        _tone, line = _update_status_line(state, [], {})
        self.assertIn('v3.17.694 · Official release', line)
        self.assertNotIn('testing build', line)
        html = self.page()
        strip = self.strip(html)
        self.assertIn('Install v3.17.694', strip)
        self.assertNotIn('(not a release)', strip)
        self.assertIn('Main is at <strong>v3.17.694</strong> (no unreleased changes)', strip)
        self.assertNotIn('Latest testing build <strong>', strip)
        rows = catalog.build(state, check_compat=False)
        main_row = next(r for r in rows if r['type'] == 'development')
        self.assertIn('Same commit as v3.17.694', main_row['labels'])

    def test_release_tag_without_a_published_github_release(self):
        # The tag is on origin (signed-tag object) but the GitHub release
        # page is not out yet: still named as the release; Official release
        # keeps recommending published releases only.
        self.gh = MainAt(main_sha=commit_of('v3.17.694'))
        self.extra_tags = {'v3.17.694': {'object': obj_of('v3.17.694'),
                                         'commit': commit_of('v3.17.694'), 'annotated': True}}
        state = self.resolve()
        self.assertEqual(state['preview']['release_tag'], 'v3.17.694')
        self.assertFalse(state['preview']['release_published'])
        d = catalog.describe_build(state, 'preview', 'main', commit_of('v3.17.694'))
        self.assertEqual(d['label'], 'v3.17.694 · Official release')
        self.assertIn('not published yet', d['detail'])
        self.assertEqual(state['discovery']['unpublished_tag']['tag'], 'v3.17.694')
        self.assertEqual(state['stable']['tag'], 'v3.17.687')
        html = self.page()
        self.assertIn('v3.17.694 is tagged and signed; its GitHub release is not published yet',
                      self.strip(html))
        self.set_channel('stable')
        stable_state = self.resolve()
        self.assertIsNone(stable_state['target'], 'stable recommends published releases only')

    def test_a_lightweight_or_untrusted_tag_is_not_called_a_release(self):
        self.gh = MainAt(main_sha=commit_of('v3.17.694'))
        self.extra_tags = {'v3.17.694': {'object': commit_of('v3.17.694'),
                                         'commit': commit_of('v3.17.694'), 'annotated': False}}
        state = self.resolve()
        self.assertNotIn('release_tag', state['preview'])
        d = catalog.describe_build(state, 'preview', 'main', commit_of('v3.17.694'))
        self.assertFalse(d['is_release'])
        self.extra_tags['v3.17.694'] = {'object': obj_of('v3.17.694'),
                                        'commit': commit_of('v3.17.694'), 'annotated': True}
        self.local_sigs = {'v3.17.694': (False, 'no trusted key')}
        state = self.resolve()
        self.assertFalse(catalog.describe_build(state, 'preview', 'main', commit_of('v3.17.694'))['is_release'])

    def test_unreleased_main_is_a_testing_build_with_its_distance(self):
        state = self.resolve()
        d = catalog.describe_build(state, 'preview', 'main', MAIN_SHA)
        self.assertEqual(d['label'],
                         f'Testing build main @ {MAIN_SHA[:7]} (unreleased, 63 commits after v3.17.687)')
        from core.views import _update_status_line
        _tone, line = _update_status_line(state, [], {})
        self.assertEqual(line, 'Update available on your Preview / testing channel: '
                               f'Testing build main @ {MAIN_SHA[:7]} (unreleased, 63 commits after v3.17.687)')
        html = self.page()
        self.assertIn(f'Install main @ {MAIN_SHA[:7]} (not a release)', self.strip(html))

    def test_installed_release_commit_is_an_official_release_not_ahead(self):
        self.gh = MainAt(main_sha=commit_of('v3.17.694'))
        self.extra_tags = {'v3.17.694': {'object': obj_of('v3.17.694'),
                                         'commit': commit_of('v3.17.694'), 'annotated': True}}
        self.installed_version, self.installed_sha = '3.17.694', commit_of('v3.17.694')
        state = self.resolve()
        self.assertIsNone(state['target'])
        rows = catalog.build(state, check_compat=False)
        summary = catalog.installed_summary(state, rows)
        self.assertEqual(summary['type_label'], 'Official release')
        self.assertFalse(summary['ahead_of_stable'])
        from core.views import _update_status_line
        tone, line = _update_status_line(state, rows, summary)
        self.assertEqual(tone, 'ok')
        self.assertTrue(line.startswith('Up to date — v3.17.694.'), line)

    def test_opening_the_check_address_goes_to_the_updates_page(self):
        """Signing in after the session ran out sends the browser back to the
        check address with a GET; that shows the Updates page, not a 405."""
        with mock.patch('core.views.UpdateService') as service:
            r = self.client.get(reverse('core:check_updates_now'))
        self.assertRedirects(r, reverse('core:system_updates'), fetch_redirect_response=False)
        service.assert_not_called()

    def test_check_now_flash_names_the_release(self):
        self.gh = MainAt(DEFAULT_RELEASES + [RELEASE_694], main_sha=commit_of('v3.17.694'))
        r = self.run_patched(lambda: self.client.post(reverse('core:check_updates_now'), follow=True))
        msgs = [str(m) for m in r.context['messages']]
        self.assertIn('Update available: v3.17.694 · Official release', msgs)
        self.assertFalse(any('Preview build available' in m for m in msgs))


class RunningUpgradeTests(_PageBase):
    def test_one_status_with_the_current_stage_and_no_update_banners(self):
        from core.models import SystemSetting
        self.gh = MainAt(DEFAULT_RELEASES + [RELEASE_694], main_sha=commit_of('v3.17.694'))
        self.resolve()
        SystemSetting.objects.filter(pk=1).update(latest_release_version='99.0.0')
        self.journal_running('preflight_ok')
        html = self.page()
        self.assertIn('id="upgrade-running"', html)
        self.assertIn('Updating to v3.17.694', html)
        self.assertIn('Current stage (3 of 11):', html)
        self.assertIn('Preflight checks passed', html)
        self.assertIn('next: taking and verifying the pre-upgrade backup', html)
        self.assertIn('v3.17.694 · Official release', html)
        self.assertIn('upd-stage--done', html)
        self.assertIn('upd-stage--current', html)
        self.assertNotIn('Stopped', html)
        self.assertNotIn('id="upgrade-recovery"', html)
        strip = self.strip(html)
        self.assertNotIn('Update available', strip)
        self.assertNotIn('Install v3.17.694', strip)
        self.assertIn('Updating to v3.17.694 · Official release — stage 3 of 11: '
                      'Preflight checks passed.', strip)
        self.assertIn('const UPGRADE_RUNNING = true;', html)
        # The navbar pill is gone while it runs.
        self.assertNotIn('id="navUpdateBadge"', html)

    def test_badge_dashboard_and_warnings_are_hidden_while_running(self):
        from core.context_processors import _update_badge
        from core.models import SystemSetting
        SystemSetting.objects.filter(pk=1).update(latest_release_version='99.0.0')
        s = SystemSetting.objects.get(pk=1)
        req = RequestFactory().get('/')
        req.user = self.su
        self.assertIsNotNone(_update_badge(req, s))
        self.journal_running('migrating')
        self.assertIsNone(_update_badge(req, s))
        from core import dashboard_widgets
        with mock.patch.object(SystemSetting, 'get_settings_for_request', return_value=s):
            status = dashboard_widgets.build_system_status(req, None)
        self.assertEqual(status['update'], '')
        from core import system_warnings
        with mock.patch('core.updater.UpdateService') as svc:
            svc.return_value.check_for_updates.return_value = {
                'update_available': True, 'current_version': '1', 'latest_version': '2'}
            self.assertEqual(system_warnings._warnings_from_app_version(), [])

    def test_check_now_while_running_says_an_upgrade_is_in_progress(self):
        self.journal_running('backup_verified')
        r = self.run_patched(lambda: self.client.post(reverse('core:check_updates_now'), follow=True))
        msgs = [str(m) for m in r.context['messages']]
        self.assertTrue(any(m.startswith('An upgrade is in progress') for m in msgs), msgs)

    def test_status_api_reports_running(self):
        self.journal_running()
        r = self.run_patched(lambda: self.client.get(reverse('core:update_status_api')))
        self.assertTrue(r.json()['upgrade_running'])

    def test_assess_message_never_says_stopped_while_running(self):
        self.journal_running('preflight_ok')
        a = journal.assess()
        self.assertEqual(a['state'], 'running')
        self.assertEqual(a['message'], 'An upgrade is in progress (current stage: Preflight checks passed).')
        p = journal.progress(a['journal'])
        self.assertEqual((p['number'], p['total']), (3, 11))
        self.assertEqual([s['state'] for s in p['steps']][:4], ['done', 'done', 'current', 'pending'])


class FinishedUpgradeTests(_PageBase):
    def test_completed_upgrade_drops_the_cached_check(self):
        from core.models import SystemSetting
        self.gh = MainAt(DEFAULT_RELEASES + [RELEASE_694], main_sha=commit_of('v3.17.694'))
        before = self.resolve()
        self.assertIsNotNone(before['target'])
        # Cached answer is reused...
        self.assertTrue(self.resolve(force=False)['from_cache'])
        # ...until an upgrade completes after it was fetched.
        self.installed_version, self.installed_sha = '3.17.694', commit_of('v3.17.694')
        journal.write({'status': 'complete', 'stage': 'complete', 'history': []})
        after = self.resolve(force=False)
        self.assertFalse(after['from_cache'])
        self.assertIsNone(after['target'])
        # Nothing recorded as "available" for the badge.
        self.assertEqual(SystemSetting.objects.get(pk=1).latest_release_version, '')
        from core.views import _update_status_line
        tone, line = _update_status_line(after, [], {})
        self.assertEqual(tone, 'ok')
        self.assertTrue(line.startswith('Up to date — v3.17.694.'), line)
        self.assertIn('No newer updates on your selected channel', line)

    def test_no_badge_when_installed_equals_latest(self):
        from config.version import get_version
        from core.context_processors import _update_badge
        from core.models import SystemSetting
        SystemSetting.objects.filter(pk=1).update(latest_release_version=get_version())
        req = RequestFactory().get('/')
        req.user = self.su
        self.assertIsNone(_update_badge(req, SystemSetting.objects.get(pk=1)))

    def test_pipeline_tail_clears_the_cache(self):
        import inspect
        src = inspect.getsource(upgrade_apply._run)
        tail = src.split("result['success'] = True", 1)[1]
        self.assertIn('channels.clear_cache()', tail)

    def test_interrupted_and_failed_keep_the_recovery_wording(self):
        journal.write({'status': 'failed', 'stage': 'migrating', 'prev_version': '3.17.687',
                       'prev_sha': self.installed_sha, 'error': 'database migration failed',
                       'target': {'kind': 'preview', 'ref': 'main', 'sha': MAIN_SHA, 'version': ''}})
        html = self.page()
        self.assertIn('The last upgrade did not finish', html)
        self.assertIn('Stopped at stage', html)
        self.assertIn('The last upgrade stopped during or after the database migration', html)
        self.assertNotIn('id="upgrade-running"', html)
        # interrupted: a dead pid
        journal.write({'status': 'running', 'stage': 'code_checked_out', 'pid': 999999999,
                       'prev_version': '3.17.687', 'prev_sha': self.installed_sha,
                       'target': {'kind': 'preview', 'ref': 'main', 'sha': MAIN_SHA, 'version': ''}})
        a = journal.assess()
        self.assertEqual(a['state'], 'interrupted')
        self.assertIn('before the database was migrated', a['message'])
        html = self.page()
        self.assertIn('The last upgrade did not finish', html)
        self.assertNotIn('id="upgrade-running"', html)


class ChannelTextTests(_PageBase):
    def test_preview_explains_and_recommends_official(self):
        html = self.page()
        help_ = html.split('id="updChannelHelp"', 1)[1].split('</div>', 1)[0]
        self.assertIn('Your channel: Preview / testing.', help_)
        self.assertIn('installs the newest commit on main, including unreleased changes', help_)
        self.assertIn('For production, <strong>Official release</strong> is recommended.', help_)

    def test_official_explains(self):
        self.set_channel('stable')
        html = self.page()
        help_ = html.split('id="updChannelHelp"', 1)[1].split('</div>', 1)[0]
        self.assertIn('Your channel: Official release', help_)
        self.assertIn('installs signed, published releases only', help_)

    def test_viewing_the_page_never_changes_the_channel(self):
        from core.models import SystemSetting
        self.page()
        self.assertEqual(SystemSetting.objects.get(pk=1).update_channel, 'preview')


class SignedOutPollingTests(_PageBase):
    """The status endpoints an open Updates tab polls answer JSON 401 once
    its session has ended, never a redirect to the login page (fetch()
    follows it silently and gets HTML); no status reaches anyone who is not
    a signed-in superuser."""

    APIS = ('core:update_status_api', 'core:update_progress_api')

    def test_anonymous_gets_json_401_and_no_status(self):
        self.client.logout()
        for name in self.APIS:
            r = self.run_patched(lambda: self.client.get(reverse(name)))
            self.assertEqual(r.status_code, 401, name)
            self.assertNotIn('Location', r)
            self.assertEqual(r.json(), {'error': 'signed_out'})

    def test_non_superuser_gets_json_403_and_no_status(self):
        u = get_user_model().objects.create_user('ux_staff', 's@x.invalid', 'pw', is_staff=True)
        self.client.force_login(u)
        for name in self.APIS:
            r = self.run_patched(lambda: self.client.get(reverse(name)))
            self.assertEqual(r.status_code, 403, name)
            self.assertEqual(r.json(), {'error': 'forbidden'})

    def test_expired_session_gets_json_401_not_a_login_redirect(self):
        for name in self.APIS:
            self.client.force_login(self.su)
            s = self.client.session
            s['_last_activity'] = time.time() - 10 * 24 * 3600
            s.save()
            r = self.run_patched(lambda: self.client.get(reverse(name)))
            self.assertEqual(r.status_code, 401, name)
            self.assertEqual(r.json(), {'error': 'signed_out'})
            # ...and the session really was ended.
            r = self.run_patched(lambda: self.client.get(reverse(name)))
            self.assertEqual(r.status_code, 401)

    def test_signed_in_superuser_still_gets_the_status(self):
        r = self.run_patched(lambda: self.client.get(reverse('core:update_status_api')))
        self.assertEqual(r.status_code, 200)
        self.assertIn('update_available', r.json())

    def test_pages_still_redirect_to_sign_in(self):
        self.client.logout()
        r = self.client.get(reverse('core:system_updates'))
        self.assertEqual(r.status_code, 302)

    def test_page_script_handles_signed_out_and_unreachable(self):
        html = self.page()
        self.assertIn("You've been signed out", html)
        self.assertIn('to see update status.', html)
        self.assertIn('data-signin-link', html)
        self.assertIn(reverse('two_factor:login') + '?next=', html)
        self.assertIn('clearInterval(statusPoll)', html)
        self.assertIn('Could not reach the server to refresh the update status', html)
        self.assertIn('id="updPollNotice"', html)
        self.assertIn('id="updateSignedOut"', html)
