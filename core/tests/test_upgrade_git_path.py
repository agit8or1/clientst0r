"""Signature checks work when the service's PATH holds only the virtualenv.

The web service unit sets PATH=/…/venv/bin. git then could not run ssh-keygen,
`git verify-tag` failed, and every older release showed as Unavailable on
Settings -> Updates.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.test import SimpleTestCase, override_settings

from core.upgrade import revision


class GitEnvTests(SimpleTestCase):
    def test_system_dirs_appended_when_path_is_venv_only(self):
        env = revision.git_env({'PATH': '/opt/app/venv/bin'})
        parts = env['PATH'].split(os.pathsep)
        self.assertEqual(parts[0], '/opt/app/venv/bin')
        for d in ('/usr/bin', '/bin', '/usr/local/bin'):
            self.assertIn(d, parts)
        self.assertEqual(env['GIT_TERMINAL_PROMPT'], '0')

    def test_existing_order_kept_and_no_duplicates(self):
        env = revision.git_env({'PATH': '/custom/bin:/usr/bin'})
        parts = env['PATH'].split(os.pathsep)
        self.assertEqual(parts[:2], ['/custom/bin', '/usr/bin'])
        self.assertEqual(parts.count('/usr/bin'), 1)

    def test_missing_path(self):
        env = revision.git_env({})
        self.assertIn('/usr/bin', env['PATH'].split(os.pathsep))

    def test_git_helper_passes_the_extended_path(self):
        with mock.patch.dict(os.environ, {'PATH': '/opt/app/venv/bin'}, clear=False), \
                mock.patch('core.upgrade.revision.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            revision.git('status')
        env = run.call_args.kwargs['env']
        self.assertIn('/usr/bin', env['PATH'].split(os.pathsep))


GIT = shutil.which('git')
SSH_KEYGEN = shutil.which('ssh-keygen')


@skipUnless(GIT and SSH_KEYGEN, 'git and ssh-keygen are needed')
class VerifyTagWithVenvOnlyPathTests(SimpleTestCase):
    """End to end: a real SSH-signed tag verifies with PATH set to a
    directory that holds neither git nor ssh-keygen."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        key = self.tmp / 'key'
        subprocess.run([SSH_KEYGEN, '-q', '-t', 'ed25519', '-N', '', '-C', 'test', '-f', str(key)], check=True)
        pub = (self.tmp / 'key.pub').read_text().split()
        self.signers = self.tmp / 'allowed_signers'
        self.signers.write_text(f'release@test.example {pub[0]} {pub[1]}\n')
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()
        base = ['-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=release@test.example']
        run = lambda *a: subprocess.run([GIT, *base, *a], check=True, capture_output=True)  # noqa: E731
        run('init', '-q')
        run('commit', '-q', '--allow-empty', '-m', 'x')
        run('-c', 'gpg.format=ssh', '-c', f'user.signingkey={key}', 'tag', '-s', '-m', 'v9.9.9', 'v9.9.9')
        self.venv_bin = self.tmp / 'venv' / 'bin'
        self.venv_bin.mkdir(parents=True)

    def test_signed_tag_verifies(self):
        with mock.patch.dict(os.environ, {'PATH': str(self.venv_bin)}), \
                override_settings(BASE_DIR=self.repo):
            ok, msg = revision.check_tag_signature('v9.9.9', str(self.signers))
        self.assertTrue(ok, msg)
        self.assertNotIn('cannot run', msg)


class ToolErrorNotCachedTests(SimpleTestCase):
    """A "cannot run ssh-keygen" failure is about this machine, not the tag:
    it is never cached, and one cached by an older version is checked again."""

    def _entry(self):
        return {'tag': 'v1.0.0', 'sha': 'a' * 40, 'annotated': True, 'tag_object': 'b' * 40}

    def test_tool_error_not_cached_and_old_one_rechecked(self):
        from core.upgrade import discovery
        digest = 'd1'
        key = f"{'b' * 40}:{digest}"
        cache = {'signatures': {key: [False, 'error: cannot run ssh-keygen: No such file or directory']}}
        with mock.patch.object(discovery, '_signers_digest', return_value=digest), \
                mock.patch('core.upgrade.revision.local_tag_signatures',
                           return_value={'v1.0.0': (True, 'Good "git" signature')}) as check:
            entries = [self._entry()]
            discovery.signature_states(entries, cache)
        check.assert_called_once()
        self.assertEqual(entries[0]['signature'], discovery.SIG_VERIFIED)
        self.assertEqual(cache['signatures'][key], [True, 'Good "git" signature'])

        cache = {'signatures': {}}
        with mock.patch.object(discovery, '_signers_digest', return_value=digest), \
                mock.patch('core.upgrade.revision.local_tag_signatures',
                           return_value={'v1.0.0': (False, 'error: cannot run ssh-keygen')}):
            discovery.signature_states([self._entry()], cache)
        self.assertNotIn(key, cache['signatures'])

    def test_real_failure_still_cached(self):
        from core.upgrade import discovery
        cache = {'signatures': {}}
        with mock.patch.object(discovery, '_signers_digest', return_value='d1'), \
                mock.patch('core.upgrade.revision.local_tag_signatures',
                           return_value={'v1.0.0': (False, 'No principal matched.')}):
            discovery.signature_states([self._entry()], cache)
        self.assertEqual(cache['signatures'][f"{'b' * 40}:d1"], [False, 'No principal matched.'])
