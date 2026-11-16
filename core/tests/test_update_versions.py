"""Settings -> Updates: version discovery, channels and manual selection.

Covers: GitHub release pagination (Link: next) and the ETag / 304 cache;
release classification (stable, pre-release by flag or tag suffix, drafts
and odd tags left out); newest-first ordering by real timestamps; the
channel policy (Official release / Preview / testing recommend, never hide,
never downgrade; a stored 'prerelease' setting reads as Preview / testing);
signature states and the signed-tag rule for pre-releases, which are testing
builds; the two-tab grouping (Official, Preview / testing); installs ahead of
the official release; failures (API down, rate limited, a page missing); the
version table on the page whatever the channel; Apply with an explicitly
selected out-of-channel or older version (confirmed, verified on the
server, channel unchanged); the review endpoint; database compatibility of
older versions; and restore points for rollback.

GitHub, origin and git are stand-ins: nothing here reaches the network or
touches the real install.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.upgrade import apply as upgrade_apply
from core.upgrade import catalog, channels, discovery
from core.upgrade.revision import Target

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def _h(prefix, tag):
    return hashlib.sha1(f'{prefix}:{tag}'.encode()).hexdigest()


def commit_of(tag):
    return _h('commit', tag)


def obj_of(tag):
    return _h('tagobj', tag)


MAIN_SHA = _h('main', 'head')


class _Resp:
    def __init__(self, status, data=None, text='', headers=None):
        self.status_code, self._data, self.text, self.headers = status, data, text, headers or {}

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def rel(tag, published, *, prerelease=False, draft=False, body='', name=None):
    return {'tag_name': tag, 'name': name or tag, 'draft': draft, 'prerelease': prerelease,
            'published_at': published, 'created_at': published, 'body': body,
            'html_url': f'https://example.invalid/releases/{tag}', 'assets': []}


DEFAULT_RELEASES = [
    rel('v3.17.687', '2026-11-15T20:33:14Z', body='### Added\n- stable 687'),
    rel('v3.17.686', '2026-11-15T18:47:22Z'),
    rel('v3.17.681', '2026-11-14T21:48:24Z', prerelease=True, body='pulled'),
    rel('v3.17.680', '2026-11-14T20:11:21Z'),
]


class FakeGitHub:
    """Routes GitHub URLs; records requests; pages releases per_page at a
    time (Link: next), sends ETags and answers 304 to a matching
    If-None-Match."""

    def __init__(self, releases=None, *, per_page=100, main_version='3.17.694', ahead=63,
                 fail_page=None, etags=True):
        self.releases = list(DEFAULT_RELEASES if releases is None else releases)
        self.per_page, self.main_version, self.ahead = per_page, main_version, ahead
        self.fail_page, self.etags = fail_page, etags
        self.calls = []

    def _etag(self, payload):
        return 'W/"' + hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest() + '"'

    def _json(self, payload, headers, req_headers, extra=None):
        h = dict(extra or {})
        if self.etags:
            tag = self._etag(payload)
            h['ETag'] = tag
            if (req_headers or {}).get('If-None-Match') == tag:
                return _Resp(304, None, headers=h)
        return _Resp(200, payload, headers=h)

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        if '/releases?' in url:
            page = int(url.rsplit('page=', 1)[1])
            if self.fail_page == page:
                return _Resp(502, {})
            start = (page - 1) * self.per_page
            chunk = self.releases[start:start + self.per_page]
            extra = {}
            if start + self.per_page < len(self.releases):
                extra['Link'] = (f'<https://api.github.com/repositories/1/releases?per_page='
                                 f'{self.per_page}&page={page + 1}>; rel="next"')
            return self._json(chunk, headers, headers, extra)
        if '/git/ref/tags/' in url:
            tag = url.rsplit('/', 1)[1]
            return self._json({'object': {'type': 'tag', 'sha': obj_of(tag)}}, headers, headers)
        if '/git/tags/' in url:
            obj = url.rsplit('/', 1)[1]
            tag = next((r['tag_name'] for r in self.releases if obj_of(r['tag_name']) == obj), '')
            return _Resp(200, {'object': {'sha': commit_of(tag)}, 'verification': {'signature': 'sig'}})
        if url.endswith('/commits/main'):
            return self._json({'sha': MAIN_SHA, 'commit': {'message': 'release: newest on main\n\nbody',
                                                           'committer': {'date': '2026-11-16T16:55:44Z'}}},
                              headers, headers)
        if url.endswith('/config/version.py'):
            return _Resp(200, text=f"VERSION = '{self.main_version}'\n")
        if '/compare/' in url:
            return self._json({'ahead_by': self.ahead, 'behind_by': 0,
                               'commits': [{'sha': MAIN_SHA, 'commit': {'message': 'release: newest on main'}}]},
                              headers, headers)
        return _Resp(404)


def origin_tags(releases, lightweight=()):
    out = {}
    for r in releases:
        t = r['tag_name']
        if t in lightweight:
            out[t] = {'object': commit_of(t), 'commit': commit_of(t), 'annotated': False}
        else:
            out[t] = {'object': obj_of(t), 'commit': commit_of(t), 'annotated': True}
    return out


class _Base(TestCase):
    installed_version = '3.17.694'
    installed_sha = MAIN_SHA
    channel = 'stable'

    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix='cs0r-versions-test-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        o = override_settings(UPGRADE_BACKUP_DIR=tmp / 'backups')
        o.enable()
        self.addCleanup(o.disable)
        self.gh = FakeGitHub()
        self.lightweight = ()
        self.local_sigs = {}          # tag -> (ok, msg) for tags "present locally"
        self.tags_error = None
        self.set_channel(self.channel)

    def set_channel(self, channel):
        from core.models import SystemSetting
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(update_channel=channel)

    def inst(self):
        return {'version': self.installed_version, 'sha': self.installed_sha, 'branch': 'main',
                'clean': True, 'is_git': True}

    def patches(self):
        def tags():
            if self.tags_error:
                raise self.tags_error
            return origin_tags(self.gh.releases, self.lightweight)

        def local(todo):
            return {t: self.local_sigs[t] for t in todo if t in self.local_sigs}
        return [mock.patch.object(channels, 'installed', side_effect=self.inst),
                mock.patch.object(discovery, 'remote_tags', side_effect=tags),
                mock.patch.object(discovery, '_signers_digest', return_value='digest'),
                mock.patch('core.upgrade.revision.local_tag_signatures', side_effect=local),
                mock.patch.object(channels.requests, 'get', side_effect=self.gh)]

    def run_patched(self, fn, *a, **k):
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            return fn(*a, **k)
        finally:
            for p in reversed(ps):
                p.stop()

    def resolve(self, force=True):
        return self.run_patched(channels.resolve, force_refresh=force)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

class DiscoveryTests(_Base):
    def test_every_page_is_read(self):
        self.gh = FakeGitHub([rel(f'v3.17.{600 + i}', f'2026-10-{1 + i % 28:02d}T00:00:00Z')
                              for i in range(7)], per_page=3)
        state = self.resolve()
        self.assertEqual(state['discovery']['pages'], 3)
        self.assertEqual(len(state['releases']), 7)
        pages = [u for u, _ in self.gh.calls if '/releases?' in u]
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(u.startswith('https://api.github.com/') for u in pages))

    def test_a_missing_page_fails_the_whole_list(self):
        self.gh = FakeGitHub(DEFAULT_RELEASES * 1, per_page=2, fail_page=2)
        state = self.resolve()
        self.assertIn('incomplete', state['error'])
        self.assertIsNone(state['releases'], 'never a partial list')
        self.assertIsNone(state['target'])

    def test_next_link_off_the_api_host_is_not_followed(self):
        class Evil(FakeGitHub):
            def __call__(self, url, headers=None, timeout=None):
                r = super().__call__(url, headers, timeout)
                if '/releases?' in url:
                    r.headers['Link'] = '<https://evil.invalid/steal?page=2>; rel="next"'
                return r
        self.gh = Evil()
        self.resolve()
        self.assertFalse([u for u, _ in self.gh.calls if 'evil.invalid' in u])

    def test_classification(self):
        self.gh = FakeGitHub([
            rel('v3.18.0-rc.1', '2026-11-16T10:00:00Z'),                 # suffix: pre-release
            rel('v3.17.700', '2026-11-16T09:00:00Z', draft=True),        # draft: never listed
            rel('nightly-9', '2026-11-16T08:00:00Z'),                    # not a version tag
            rel('v3.17.681', '2026-11-14T21:48:24Z', prerelease=True),   # flagged pre-release
            rel('v3.17.687', '2026-11-15T20:33:14Z'),
        ])
        state = self.resolve()
        types = {e['tag']: e['type'] for e in state['releases']}
        self.assertEqual(types, {'v3.18.0-rc.1': 'prerelease', 'v3.17.681': 'prerelease',
                                 'v3.17.687': 'stable'})
        self.assertEqual(state['discovery']['drafts'], 1)
        self.assertEqual(state['discovery']['ignored'], ['nightly-9'])
        self.assertEqual(state['stable']['tag'], 'v3.17.687')
        self.assertEqual(state['prerelease']['tag'], 'v3.18.0-rc.1')
        self.assertEqual(state['releases'][0]['kind'], 'prerelease')

    def test_newest_first_by_publish_date_not_by_version(self):
        self.gh = FakeGitHub([
            rel('v3.17.690', '2026-11-01T00:00:00Z'),
            rel('v3.17.650', '2026-11-10T00:00:00Z'),   # published later (a backport)
            rel('v3.17.689', '2026-10-01T00:00:00Z'),
        ])
        state = self.resolve()
        self.assertEqual([e['tag'] for e in state['releases']], ['v3.17.650', 'v3.17.690', 'v3.17.689'])
        rows = catalog.build(state, check_compat=False)
        self.assertEqual(rows[0]['type'], 'development')     # main's commit date is the newest
        self.assertEqual([r['ref'] for r in rows[1:]], ['v3.17.650', 'v3.17.690', 'v3.17.689'])
        self.assertEqual(rows[0]['date_kind'], 'Committed')
        self.assertEqual(rows[1]['date_kind'], 'Released')

    def test_tags_resolve_to_commits_through_origin(self):
        state = self.resolve()
        by = {e['tag']: e for e in state['releases']}
        self.assertEqual(by['v3.17.686']['sha'], commit_of('v3.17.686'))
        self.assertEqual(by['v3.17.686']['tag_object'], obj_of('v3.17.686'))

    def test_etag_is_sent_back_and_304_reuses_the_stored_answer(self):
        first = self.resolve()
        self.gh.calls.clear()
        second = self.resolve()
        release_calls = [h for u, h in self.gh.calls if '/releases?' in u]
        self.assertTrue(release_calls and release_calls[0].get('If-None-Match', '').startswith('W/"'))
        self.assertEqual([e['tag'] for e in first['releases']], [e['tag'] for e in second['releases']])
        self.assertIsNone(second['error'])

    def test_rate_limit_is_explained(self):
        def limited(*a, **k):
            return _Resp(403, {}, headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1763300000'})
        self.gh = limited
        state = self.resolve()
        self.assertIn('rate limit', state['error'])
        self.assertIn('UTC', state['error'])
        self.gh = lambda *a, **k: _Resp(429, {})
        self.assertIn('rate limit', self.resolve()['error'])

    def test_api_down_never_claims_up_to_date(self):
        import requests

        def down(*a, **k):
            raise requests.ConnectionError('no route')
        self.gh = down
        state = self.resolve()
        self.assertIn('Cannot connect', state['error'])
        self.assertIsNone(state['releases'])
        from core.views import _update_status_line
        tone, line = _update_status_line(state, [], {'ahead_of_stable': False})
        self.assertEqual(tone, 'error')
        self.assertNotIn('No newer', line)

    def test_failed_check_falls_back_to_the_last_complete_list_marked_stale(self):
        self.resolve()
        self.gh = lambda *a, **k: _Resp(500, {})
        state = self.resolve()
        self.assertTrue(state['stale'])
        self.assertEqual(len(state['releases']), 4)
        from core.views import _update_status_line
        tone, line = _update_status_line(state, [], {'ahead_of_stable': False})
        self.assertEqual(tone, 'stale')
        self.assertIn('latest check failed', line)

    def test_origin_unreachable_falls_back_to_the_api_for_the_newest(self):
        self.tags_error = OSError('no git')
        state = self.resolve()
        by = {e['tag']: e for e in state['releases']}
        self.assertEqual(by['v3.17.687']['sha'], commit_of('v3.17.687'))   # from the API
        self.assertEqual(by['v3.17.686']['sha'], '')                       # unknown, not invented
        self.assertEqual(by['v3.17.686']['signature'], discovery.SIG_UNKNOWN)
        self.assertIn('origin could not be asked', state['discovery']['tags_error'])


# ---------------------------------------------------------------------------
# signatures and the pre-release trust policy
# ---------------------------------------------------------------------------

class SignatureTests(_Base):
    installed_version = '3.17.600'
    installed_sha = 'f' * 40

    def test_states(self):
        self.gh = FakeGitHub(DEFAULT_RELEASES + [rel('v3.17.679', '2026-11-13T00:00:00Z'),
                                                 rel('v3.17.678', '2026-11-12T00:00:00Z')])
        self.lightweight = ('v3.17.678',)
        self.local_sigs = {'v3.17.687': (True, 'Good "git" signature'),
                           'v3.17.679': (False, 'error: no signature found')}
        by = {e['tag']: e['signature'] for e in self.resolve()['releases']}
        self.assertEqual(by['v3.17.687'], discovery.SIG_VERIFIED)
        self.assertEqual(by['v3.17.686'], discovery.SIG_PENDING)      # not local: checked at install
        self.assertEqual(by['v3.17.679'], discovery.SIG_INVALID)
        self.assertEqual(by['v3.17.678'], discovery.SIG_UNSIGNED)

    def test_untrusted_prerelease_is_listed_but_not_installable_or_recommended(self):
        self.set_channel('stable')
        self.gh = FakeGitHub(DEFAULT_RELEASES + [rel('v3.18.0-rc.1', '2026-11-16T10:00:00Z',
                                                     prerelease=True)])
        self.local_sigs = {'v3.18.0-rc.1': (False, 'error: no signature found')}
        state = self.resolve()
        self.assertEqual(state['target']['ref'], 'v3.17.687', 'falls back to the trusted stable')
        row = catalog.find(catalog.build(state, check_compat=False), 'prerelease', 'v3.18.0-rc.1',
                           commit_of('v3.18.0-rc.1'))
        self.assertFalse(row['installable'])
        self.assertIn('not signed by a trusted release key', row['reason'])

    def test_signed_prerelease_is_a_testing_build_never_official(self):
        self.gh = FakeGitHub(DEFAULT_RELEASES + [rel('v3.18.0-rc.1', '2026-11-16T10:00:00Z',
                                                     prerelease=True)])
        self.local_sigs = {'v3.18.0-rc.1': (True, 'Good signature')}
        # Official release never recommends it, however new and well signed.
        self.set_channel('stable')
        state = self.resolve()
        self.assertEqual(state['target']['ref'], 'v3.17.687')
        row = catalog.find(catalog.build(state, check_compat=False), 'prerelease', 'v3.18.0-rc.1',
                           commit_of('v3.18.0-rc.1'))
        self.assertEqual(row['group'], 'testing')
        self.assertNotIn('Official', row['type_label'])
        self.assertTrue(row['installable'])          # signed tag: eligible, as before
        self.assertFalse(row['in_channel'])
        # On Preview / testing it belongs to the channel; main is what is recommended.
        self.set_channel('preview')
        state = self.resolve()
        row = catalog.find(catalog.build(state, check_compat=False), 'prerelease', 'v3.18.0-rc.1',
                           commit_of('v3.18.0-rc.1'))
        self.assertTrue(row['in_channel'])
        self.assertEqual(state['target']['kind'], 'preview')

    def test_apply_verifies_a_prerelease_tag_like_a_release(self):
        from core.upgrade.revision import RevisionError
        with mock.patch.object(upgrade_apply, 'is_git_install', return_value=True), \
                mock.patch.object(upgrade_apply, 'check_remote_unchanged'), \
                mock.patch.object(upgrade_apply, 'fetch'), \
                mock.patch('core.upgrade.revision.git', return_value=mock.Mock(returncode=1, stdout='')), \
                mock.patch.object(upgrade_apply, 'verify_release_tag', side_effect=RevisionError(
                    'v3.18.0-rc.1 is not signed by a trusted release key')) as verify, \
                mock.patch.object(upgrade_apply, '_groom'), \
                mock.patch.object(upgrade_apply, '_audit'):
            r = upgrade_apply.run(Target('prerelease', 'v3.18.0-rc.1', 'a' * 40), allow_prerelease=True)
        self.assertTrue(r['refused'])
        self.assertIn('not signed', r['error'])
        self.assertEqual(verify.call_args[0][0].kind, 'prerelease')

    def test_prerelease_needs_confirmation_on_stable(self):
        with mock.patch.object(upgrade_apply, 'is_git_install', return_value=True), \
                mock.patch.object(upgrade_apply, 'fetch') as fetch, \
                mock.patch.object(upgrade_apply, '_audit'):
            r = upgrade_apply.run(Target('prerelease', 'v3.18.0-rc.1', 'a' * 40))
        self.assertTrue(r['refused'])
        self.assertIn('Official release channel', r['error'])
        fetch.assert_not_called()

    def test_prerelease_installs_without_flag_on_preview_testing(self):
        self.set_channel('preview')
        with mock.patch.object(upgrade_apply, 'is_git_install', return_value=True), \
                mock.patch.object(upgrade_apply, 'check_remote_unchanged'), \
                mock.patch.object(upgrade_apply, 'fetch'), \
                mock.patch('core.upgrade.revision.git', return_value=mock.Mock(returncode=1, stdout='')), \
                mock.patch.object(upgrade_apply, 'verify_release_tag', side_effect=__import__(
                    'core.upgrade.revision', fromlist=['RevisionError']).RevisionError('not signed')) as verify, \
                mock.patch.object(upgrade_apply, '_groom'), \
                mock.patch.object(upgrade_apply, '_audit'):
            r = upgrade_apply.run(Target('prerelease', 'v3.18.0-rc.1', 'a' * 40))
        # Not refused for the channel; still refused by the signature check.
        self.assertIn('not signed', r['error'])
        verify.assert_called_once()


# ---------------------------------------------------------------------------
# channel policy and where the installed build stands
# ---------------------------------------------------------------------------

class ChannelPolicyTests(_Base):
    def test_development_build_ahead_of_stable_on_stable(self):
        # Production today: v3.17.694 from main, Stable selected.
        state = self.resolve()
        self.assertIsNone(state['target'], 'never offers the older stable release as an update')
        self.assertEqual(state['relation_to_stable'], 'ahead')
        rows = catalog.build(state, check_compat=False)
        summary = catalog.installed_summary(state, rows)
        self.assertEqual(summary['type'], 'development')
        self.assertTrue(summary['ahead_of_stable'])
        by = {r['ref']: r for r in rows}
        self.assertEqual(by['main']['relation'], 'installed')
        self.assertIn('Installed', by['main']['labels'])
        self.assertIn('Latest testing build', by['main']['labels'])
        self.assertEqual(by['v3.17.687']['relation'], 'older')
        self.assertIn('Latest official', by['v3.17.687']['labels'])
        self.assertIn('Latest testing tag', by['v3.17.681']['labels'])
        self.assertEqual(by['v3.17.681']['group'], 'testing')
        self.assertEqual(by['v3.17.687']['group'], 'official')
        self.assertEqual(by['v3.17.687']['status'], 'Older version')
        self.assertNotIn('Recommended', by['v3.17.687']['labels'])
        from core.views import _update_status_line
        tone, line = _update_status_line(state, rows, summary)
        self.assertEqual(tone, 'ok')
        self.assertIn('No newer updates on your selected channel', line)
        # The ahead-of-stable sentence is shown once, by the page, from this flag.
        self.assertTrue(summary['ahead_of_stable'])
        self.assertNotIn('Update available', line)

    def test_behind_on_stable_recommends_the_newest_stable_only(self):
        self.installed_version, self.installed_sha = '3.17.680', commit_of('v3.17.680')
        state = self.resolve()
        self.assertEqual(state['target']['ref'], 'v3.17.687')
        rows = catalog.build(state, check_compat=False)
        by = {r['ref']: r for r in rows}
        self.assertTrue(by['v3.17.687']['recommended'])
        self.assertEqual(by['v3.17.680']['relation'], 'installed')
        self.assertFalse(by['v3.17.681']['in_channel'])
        self.assertTrue(by['main']['installable'])
        self.assertFalse(by['main']['in_channel'])

    def test_preview_recommends_main(self):
        self.set_channel('preview')
        self.installed_version, self.installed_sha = '3.17.687', commit_of('v3.17.687')
        t = self.resolve()['target']
        self.assertEqual((t['kind'], t['ref'], t['sha']), ('preview', 'main', MAIN_SHA))

    def test_badge_follows_the_channel(self):
        from core.models import SystemSetting
        self.installed_version, self.installed_sha = '3.17.687', commit_of('v3.17.687')
        self.set_channel('preview')
        self.resolve()
        self.assertEqual(SystemSetting.objects.get(pk=1).latest_release_version, '3.17.694')
        self.set_channel('stable')
        self.resolve()
        self.assertEqual(SystemSetting.objects.get(pk=1).latest_release_version, '3.17.687')


# ---------------------------------------------------------------------------
# installing something older: database compatibility
# ---------------------------------------------------------------------------

class DowngradeCompatibilityTests(TestCase):
    def setUp(self):
        catalog._compat.cache_clear()

    def _check(self, files, script='x\nreset --hard "$TARGET_SHA"\n', applied=(('core', '0001_initial'),)):
        with mock.patch('core.upgrade.revision.commit_available', return_value=True), \
                mock.patch('core.upgrade.revision.migration_files_at', return_value=files), \
                mock.patch('core.upgrade.revision.show_file', return_value=script), \
                mock.patch.object(catalog, 'applied_local_migrations', return_value=list(applied)), \
                mock.patch.object(catalog, '_local_apps', return_value={'core': 'core'}):
            return catalog.downgrade_compatibility('b' * 40)

    def test_safe_when_the_target_has_every_applied_migration(self):
        state, detail, missing = self._check(['core/migrations/0001_initial.py'])
        self.assertEqual(state, 'safe')
        self.assertEqual(missing, ())

    def test_unsafe_when_it_would_need_a_reverse_migration(self):
        state, detail, missing = self._check(['core/migrations/0001_initial.py'],
                                             applied=(('core', '0001_initial'), ('core', '0108_new')))
        self.assertEqual(state, 'unsafe')
        self.assertEqual(missing, ('core.0108_new',))
        self.assertIn('reverse migrations', detail)

    def test_unsafe_when_its_update_script_predates_pinned_installs(self):
        state, detail, _ = self._check(['core/migrations/0001_initial.py'], script='git reset --hard origin/main')
        self.assertEqual(state, 'unsafe')
        self.assertIn('install main instead', detail)

    def test_unchecked_without_the_commit(self):
        with mock.patch('core.upgrade.revision.commit_available', return_value=False), \
                mock.patch.object(catalog, 'applied_local_migrations', return_value=[]):
            self.assertEqual(catalog.downgrade_compatibility('c' * 40)[0], 'unchecked')

    def test_pipeline_refuses_an_incompatible_older_version_even_when_confirmed(self):
        with mock.patch.object(upgrade_apply, 'is_git_install', return_value=True), \
                mock.patch.object(upgrade_apply, 'check_remote_unchanged'), \
                mock.patch.object(upgrade_apply, 'fetch'), \
                mock.patch.object(upgrade_apply, 'verify_release_tag', return_value='ok'), \
                mock.patch.object(upgrade_apply, 'version_at', return_value='0.0.1'), \
                mock.patch('core.upgrade.revision.git', return_value=mock.Mock(returncode=1)), \
                mock.patch.object(catalog, 'downgrade_compatibility',
                                  return_value=('unsafe', 'needs reverse migrations', ('core.0108',))), \
                mock.patch.object(upgrade_apply.snapshot, 'create') as create, \
                mock.patch.object(upgrade_apply, '_groom'), \
                mock.patch.object(upgrade_apply, '_audit'), \
                override_settings(UPGRADE_BACKUP_DIR=Path(tempfile.mkdtemp(prefix='cs0r-dg-'))):
            r = upgrade_apply.run(Target('release', 'v0.0.1', 'a' * 40), allow_downgrade=True)
        self.assertTrue(r['refused'])
        self.assertIn('needs reverse migrations', r['error'])
        create.assert_not_called()


# ---------------------------------------------------------------------------
# the page and Apply
# ---------------------------------------------------------------------------

@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class UpdatesPageTests(_Base):
    def setUp(self):
        super().setUp()
        self.su = get_user_model().objects.create_user('vers_su', 'v@x.invalid', 'pw',
                                                       is_superuser=True, is_staff=True)
        self.client.force_login(self.su)
        p = mock.patch('core.update_progress.UpdateProgress')
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(catalog, 'downgrade_compatibility',
                              return_value=('safe', 'no schema change', ()))
        p.start()
        self.addCleanup(p.stop)
        self.gh = FakeGitHub(DEFAULT_RELEASES + [rel('v3.18.0-beta.2', '2026-11-16T09:00:00Z',
                                                     prerelease=True)])

    def page(self):
        return self.run_patched(lambda: self.client.get(reverse('core:system_updates')).content.decode())

    def apply(self, body):
        with mock.patch('core.updater.UpdateService.perform_update') as perform, \
                mock.patch('threading.Thread') as thread:
            r = self.run_patched(lambda: self.client.post(reverse('core:apply_update'), data=json.dumps(body),
                                                          content_type='application/json'))
            if thread.called:
                thread.call_args.kwargs['target']()
        return r, perform

    def test_on_stable_every_prerelease_and_the_development_build_are_listed(self):
        html = self.page()
        self.assertIn('Available Versions', html)
        for tag in ('v3.17.681', 'v3.18.0-beta.2', 'v3.17.687', 'v3.17.686'):
            self.assertIn(f'data-search="{tag}', html)
        self.assertIn('data-type="development"', html)
        self.assertIn(MAIN_SHA[:12], html)
        self.assertIn('unofficial, may be unstable', html)
        self.assertIn('Latest testing build', html)
        self.assertIn('No newer updates on your selected channel', html)
        self.assertIn('You are running a testing build newer than the latest official release', html)
        self.assertNotIn('onclick=', html.split('id="updSummary"', 1)[1])

    def test_on_preview_every_stable_release_is_listed(self):
        self.set_channel('preview')
        html = self.page()
        for tag in ('v3.17.687', 'v3.17.686', 'v3.17.680'):
            self.assertIn(f'data-search="{tag}', html)
        self.assertIn('data-type="stable"', html)
        self.assertIn('Latest official', html)

    def test_the_list_is_collapsed_to_what_is_newer(self):
        import re
        html = self.page()
        rows = re.findall(r'<tr class="upd-row[^>]*>', html)
        self.assertTrue(rows)
        # Every row is in the page (Show all reveals them) but starts hidden;
        # only newer rows (and the installed one beside them) are marked to
        # show by default.
        self.assertTrue(all(' hidden' in r for r in rows))
        relevant = [r for r in rows if 'data-relevant="1"' in r]
        self.assertTrue(all('data-search="v3.17.6' not in r for r in relevant))
        self.assertIn(f'Show all versions ({len(rows)})', html)
        # The channel is a small select in the status strip; saving installs nothing.
        strip = html.split('id="updSummary"', 1)[1].split('id="updVersions"', 1)[0]
        self.assertIn('name="channel"', strip)
        # Backups and rollback start collapsed.
        self.assertRegex(html, r'<details class="upd-more" id="preUpgradeBackups">')

    def test_two_tabs_official_and_testing(self):
        import re
        html = self.page()
        tabs = re.findall(r'data-action="filterVersions" data-arg="(\w+)"', html)
        self.assertEqual(tabs, ['official', 'testing'])
        self.assertIn('>Official <span', html)
        self.assertIn('>Preview / testing <span', html)
        for word in ('Prerelease', 'Latest prerelease', 'data-arg="stable"', 'data-arg="development"'):
            self.assertNotIn(word, html)
        # Pre-releases and main are testing builds; stable releases are official.
        rows = re.findall(r'<tr class="upd-row[^>]*>', html)
        group = {re.search(r'data-search="(\S+)', r).group(1): re.search(r'data-group="(\w+)"', r).group(1)
                 for r in rows}
        self.assertEqual(group['v3.17.687'], 'official')
        self.assertEqual(group['v3.17.681'], 'testing')
        self.assertEqual(group['v3.18.0-beta.2'], 'testing')
        self.assertEqual(group['main'], 'testing')
        # The channel select has exactly two options.
        strip = html.split('id="updChannelSelect"', 1)[1].split('</select>', 1)[0]
        self.assertEqual(re.findall(r'<option value="(\w+)"', strip), ['stable', 'preview'])

    def test_a_stored_prerelease_channel_reads_as_preview_testing(self):
        self.set_channel('prerelease')
        self.assertEqual(channels.current_channel(), 'preview')
        html = self.page()
        strip = html.split('id="updChannelSelect"', 1)[1].split('</select>', 1)[0]
        self.assertIn('<option value="preview" selected>', strip)

    def test_saving_the_old_prerelease_channel_is_refused(self):
        self.client.post(reverse('core:set_update_channel'), {'channel': 'prerelease'})
        from core.models import SystemSetting
        self.assertNotEqual(SystemSetting.objects.get(pk=1).update_channel, 'prerelease')

    def test_page_without_github_says_so_instead_of_showing_empty_categories(self):
        import requests

        def down(*a, **k):
            raise requests.ConnectionError('no route')
        self.gh = down
        html = self.page()
        self.assertIn('The version list could not be read from GitHub', html)
        self.assertNotIn('None published', html)
        self.assertNotIn('No newer updates', html)

    def test_out_of_channel_install_needs_confirmation_and_keeps_the_channel(self):
        from core.models import SystemSetting
        self.local_sigs = {'v3.18.0-beta.2': (True, 'Good signature')}
        body = {'kind': 'prerelease', 'ref': 'v3.18.0-beta.2', 'sha': commit_of('v3.18.0-beta.2')}
        r, perform = self.apply(body)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['reason'], 'confirm_required')
        perform.assert_not_called()

        r, perform = self.apply({**body, 'confirm_out_of_channel': True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['status'], 'started')
        kwargs = perform.call_args.kwargs
        self.assertEqual((kwargs['target'].kind, kwargs['target'].ref), ('prerelease', 'v3.18.0-beta.2'))
        self.assertTrue(kwargs['allow_prerelease'])
        self.assertFalse(kwargs['allow_downgrade'])
        self.assertEqual(SystemSetting.objects.get(pk=1).update_channel, 'stable')

    def test_development_build_on_stable_is_allowed_explicitly(self):
        self.installed_version, self.installed_sha = '3.17.687', commit_of('v3.17.687')
        r, perform = self.apply({'kind': 'preview', 'ref': 'main', 'sha': MAIN_SHA,
                                 'confirm_out_of_channel': True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(perform.call_args.kwargs['allow_preview'])

    def test_older_version_needs_its_own_confirmation(self):
        body = {'kind': 'release', 'ref': 'v3.17.686', 'sha': commit_of('v3.17.686')}
        r, perform = self.apply(body)
        self.assertEqual(r.status_code, 400)
        perform.assert_not_called()
        r, perform = self.apply({**body, 'confirm_downgrade': True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(perform.call_args.kwargs['allow_downgrade'])

    def test_untrusted_version_is_refused_on_the_server(self):
        self.local_sigs = {'v3.18.0-beta.2': (False, 'error: no signature found')}
        r, perform = self.apply({'kind': 'prerelease', 'ref': 'v3.18.0-beta.2',
                                 'sha': commit_of('v3.18.0-beta.2'), 'confirm_out_of_channel': True})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['reason'], 'not_installable')
        perform.assert_not_called()

    def test_a_sha_that_discovery_does_not_offer_is_refused(self):
        r, perform = self.apply({'kind': 'release', 'ref': 'v3.17.686', 'sha': 'e' * 40,
                                 'confirm_downgrade': True})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['reason'], 'not_offered')
        perform.assert_not_called()

    def test_moved_main_offers_the_new_build_for_review(self):
        r, perform = self.apply({'kind': 'preview', 'ref': 'main', 'sha': 'd' * 40,
                                 'confirm_out_of_channel': True})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['reason'], 'target_changed')
        self.assertEqual(r.json()['target']['sha'], MAIN_SHA)
        perform.assert_not_called()

    def test_review_runs_the_checks_without_installing(self):
        from core.upgrade import preflight
        self.local_sigs = {'v3.18.0-beta.2': (True, 'Good signature')}
        body = {'kind': 'prerelease', 'ref': 'v3.18.0-beta.2', 'sha': commit_of('v3.18.0-beta.2')}
        with mock.patch('core.upgrade.revision.fetch') as fetch, \
                mock.patch('core.upgrade.revision.verify_release_tag', return_value='Good signature'), \
                mock.patch('core.upgrade.revision.version_at', return_value='3.18.0b2'), \
                mock.patch('core.upgrade.revision.head_sha', return_value=MAIN_SHA), \
                mock.patch.object(preflight, 'run', return_value=[preflight.Check('disk space', 'ok', 'fine')]), \
                mock.patch('core.updater.UpdateService.perform_update') as perform:
            r = self.run_patched(lambda: self.client.post(reverse('core:upgrade_review_api'),
                                                          data=json.dumps(body), content_type='application/json'))
        d = r.json()
        self.assertTrue(d['ok'], d)
        self.assertFalse(d['in_channel'])
        self.assertEqual(d['relation'], 'newer')
        self.assertEqual([c['name'] for c in d['checks']], ['revision', 'signature', 'disk space'])
        fetch.assert_called_once()
        perform.assert_not_called()

    def test_review_of_an_unknown_version(self):
        r = self.run_patched(lambda: self.client.post(
            reverse('core:upgrade_review_api'),
            data=json.dumps({'kind': 'release', 'ref': 'v9.9.9', 'sha': 'e' * 40}),
            content_type='application/json'))
        self.assertEqual(r.status_code, 404)

    def test_superusers_only(self):
        plain = get_user_model().objects.create_user('vers_plain', 'p@x.invalid', 'pw')
        self.client.force_login(plain)
        r = self.client.post(reverse('core:upgrade_review_api'), data='{}', content_type='application/json')
        self.assertEqual(r.status_code, 302)

    def test_saving_a_channel_installs_nothing(self):
        with mock.patch('core.updater.UpdateService.perform_update') as perform, \
                mock.patch('core.upgrade.apply.run') as run:
            self.client.post(reverse('core:set_update_channel'), {'channel': 'preview'})
        from core.models import SystemSetting
        self.assertEqual(SystemSetting.objects.get(pk=1).update_channel, 'preview')
        perform.assert_not_called()
        run.assert_not_called()


# ---------------------------------------------------------------------------
# rollback restore points
# ---------------------------------------------------------------------------

class RestorePointTests(TestCase):
    def _summary(self, rows):
        return {'backups': rows, 'policy': object()}

    def _row(self, name, **kw):
        return {'name': name, 'path': f'/b/{name}', 'app_version': '3.17.690', 'git_sha': 'a' * 40,
                'created_dt': None, 'size_human': '1 MB', 'reason': '', 'verified': True,
                'in_progress': False, **kw}

    def _points(self, rows, keep=None, commit=True):
        keep = [r['path'] for r in rows] if keep is None else keep
        plan = {'keep': [({'path': p}, 'kept') for p in keep], 'delete': []}
        with mock.patch('core.upgrade.retention.plan', return_value=plan), \
                mock.patch('core.upgrade.revision.commit_available', return_value=commit), \
                mock.patch('core.upgrade.snapshot.load_manifest', return_value={'db': {'engine': 'sqlite'}}), \
                mock.patch('core.upgrade.snapshot.db_engine', return_value='sqlite'), \
                mock.patch('core.upgrade.snapshot.parse_env_file', return_value={}), \
                mock.patch('core.upgrade.snapshot.key_fingerprint', return_value='k'):
            return catalog.restore_points(self._summary(rows))

    def test_only_verified_kept_snapshots_with_their_code_are_offered(self):
        rows = [self._row('snapshot-a'), self._row('snapshot-b', verified=False),
                self._row('snapshot-c', git_sha=''), self._row('snapshot-d')]
        pts = {p['name']: p for p in self._points(rows, keep=['/b/snapshot-a', '/b/snapshot-b', '/b/snapshot-c'])}
        self.assertTrue(pts['snapshot-a']['eligible'])
        self.assertIn('upgrade_restore /b/snapshot-a', pts['snapshot-a']['command'])
        self.assertFalse(pts['snapshot-b']['eligible'])
        self.assertFalse(pts['snapshot-c']['eligible'])
        self.assertIn('retention removes it', pts['snapshot-d']['why_not'])

    def test_missing_commit_is_not_offered(self):
        p = self._points([self._row('snapshot-a')], commit=False)[0]
        self.assertFalse(p['eligible'])
        self.assertIn('not in this checkout', p['why_not'])


class ModalStackingTests(SimpleTestCase):
    """v3.17.694's Apply did nothing for users with a background set: the
    confirm modal had no backdrop and sat inside <main>, which
    `body.has-background .container` makes a z-index:1 stacking context, so
    the body-level PWA install banner (z-index 9999) covered its button."""

    def test_modals_are_moved_under_body_and_keep_a_backdrop(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'templates/core/system_updates.html').read_text()
        self.assertIn('document.body.appendChild(el)', src)
        self.assertNotIn('data-bs-backdrop="false"', src)
        self.assertNotIn('z-index: 99999', src)


class ChannelMigrationTests(TestCase):
    """core 0112: a saved 'prerelease' channel becomes Preview / testing."""

    def test_data_migration_maps_prerelease_to_preview(self):
        import importlib
        from django.apps import apps as global_apps
        from core.models import SystemSetting
        SystemSetting.get_settings()
        SystemSetting.objects.filter(pk=1).update(update_channel='prerelease')
        mod = importlib.import_module('core.migrations.0112_update_channel_two_channels')
        mod.prerelease_to_preview(global_apps, None)
        self.assertEqual(SystemSetting.objects.get(pk=1).update_channel, 'preview')
