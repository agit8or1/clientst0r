"""Operations tooling: office_setup --import-secret/--install, office_sessions,
the install guidance page, and upgrade safety (clientst0r's own update path
never upgrades or restarts an Office editor)."""
import io
import os
import re
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from audit.models import AuditLog

from . import install_guidance, sessions
from .models import EditorInstance, EditSession
from .providers import NotConfigured, NotSupported, register
from .tests import TEST_MIDDLEWARE, FakeProvider, OfficeTestBase

BASE = Path(django_settings.BASE_DIR)
SECRET = 'f3b1c2d4e5a6978812ab34cd56ef7890aabbccddeeff00112233445566778899'


def write_import(directory, *, secret=SECRET, provider='onlyoffice', mode=0o600, extra=''):
    path = Path(directory) / 'import.env'
    path.write_text(
        '# clientst0r Office editor import file. CONTAINS A SECRET.\n'
        f'PROVIDER={provider}\nEDITION=onlyoffice\nMODE=separate_server\nNAME=docs.example.com\n'
        'BROWSER_URL=https://docs.example.com/\nINTERNAL_URL=\n'
        f'CALLBACK_URL=https://app.example.com/\nSECRET={secret}\n{extra}')
    path.chmod(mode)
    return path


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


class OfficeSetupImportTests(OfficeTestBase):

    def setUp(self):
        super().setUp()
        self.dir = tempfile.mkdtemp(prefix='office-import-')

    def test_import_creates_disabled_instance_and_shreds_file(self):
        path = write_import(self.dir)
        out = run('office_setup', '--import-secret', str(path))
        self.assertFalse(path.exists())
        self.assertNotIn(SECRET, out)
        inst = EditorInstance.objects.get(name='docs.example.com')
        self.assertEqual(inst.shared_secret, SECRET)
        self.assertFalse(inst.enabled)
        self.assertEqual(inst.provider, 'onlyoffice')
        self.assertEqual(inst.browser_url, 'https://docs.example.com/')
        self.assertEqual(inst.callback_base_url, 'https://app.example.com/')
        entry = AuditLog.objects.filter(extra_data__office_event='settings_change').latest('pk')
        self.assertNotIn(SECRET, entry.description + str(entry.extra_data))

    def test_import_into_existing_instance(self):
        inst = self.make_instance(shared_secret='old-secret-value-1234567890')
        path = write_import(self.dir)
        run('office_setup', '--import-secret', str(path), '--instance', str(inst.pk))
        inst.refresh_from_db()
        self.assertEqual(inst.shared_secret, SECRET)
        self.assertEqual(inst.health_status, 'unknown')
        self.assertFalse(path.exists())

    def test_provider_mismatch_keeps_file_and_secret(self):
        inst = self.make_instance(provider='collabora')
        path = write_import(self.dir)
        with self.assertRaises(CommandError):
            run('office_setup', '--import-secret', str(path), '--instance', str(inst.pk))
        self.assertTrue(path.exists())
        inst.refresh_from_db()
        self.assertNotEqual(inst.shared_secret, SECRET)

    def test_group_readable_file_refused(self):
        path = write_import(self.dir, mode=0o640)
        with self.assertRaisesMessage(CommandError, 'chmod 600'):
            run('office_setup', '--import-secret', str(path))
        self.assertFalse(EditorInstance.objects.exists())

    def test_symlink_refused(self):
        path = write_import(self.dir)
        link = Path(self.dir) / 'link.env'
        link.symlink_to(path)
        with self.assertRaisesMessage(CommandError, 'regular file'):
            run('office_setup', '--import-secret', str(link))

    def test_vendor_default_secret_refused(self):
        path = write_import(self.dir, secret='developer-only-not-a-real-secret')
        with self.assertRaisesMessage(CommandError, 'published default'):
            run('office_setup', '--import-secret', str(path))

    def test_unknown_keys_refused(self):
        path = write_import(self.dir, extra='EVIL=1\n')
        with self.assertRaisesMessage(CommandError, 'not an install-editor.sh import file'):
            run('office_setup', '--import-secret', str(path))

    def test_install_is_guidance_only(self):
        out = run('office_setup', '--install', '--provider', 'onlyoffice', '--mode', 'same-server',
                  '--editor-host', 'docs.example.com', '--app-url', 'https://app.example.com/')
        self.assertIn('Nothing was installed by this command.', out)
        self.assertIn(install_guidance.INSTALLER_COPY, out)
        self.assertIn('--mode same-server', out)
        self.assertIn('--hostname docs.example.com', out)

    def test_plan_lists_installer_commands(self):
        out = run('office_setup', '--plan', '--provider', 'collabora', '--edition', 'collabora-code',
                  '--mode', 'separate-server', '--editor-host', 'docs.example.com',
                  '--app-url', 'https://app.example.com/')
        self.assertIn('--provider collabora-code', out)
        self.assertIn('sha256sum -c', out)
        self.assertIn('evaluation and testing only', out)


@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)
class InstallPageTests(OfficeTestBase):

    def get(self, **params):
        self.client.force_login(self.su)
        resp = self.client.get(reverse('office:install'), params)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_same_server_commands(self):
        inst = self.make_instance(mode='same_server', shared_secret=SECRET,
                                  callback_base_url='https://app.example.com/')
        page = self.get(provider='onlyoffice', mode='same_server', editor_host='docs.example.com',
                        instance=inst.pk)
        self.assertNotIn(SECRET, page)
        self.assertIn('--mode same-server', page)
        self.assertIn('--clientstor-url https://app.example.com/', page)
        self.assertIn('--accept-mscorefonts-eula', page)
        self.assertIn('--preflight-only', page)
        self.assertIn('--dry-run', page)
        self.assertIn(f'office_setup --import-secret /var/lib/clientst0r-office-import/import-docs.example.com.env --instance {inst.pk}', page)
        self.assertIn('verify-tag', page)

    def test_separate_server_commands(self):
        page = self.get(provider='collabora', mode='separate_server', edition='collabora-code',
                        editor_host='docs.example.com', tls='certbot', private_ca='1')
        self.assertIn('--provider collabora-code', page)
        self.assertIn('--mode separate-server', page)
        self.assertIn('--tls certbot', page)
        self.assertIn('--ca-file /root/clientst0r-ca.pem', page)
        self.assertIn(install_guidance.installer_sha256(), page)
        self.assertIn('scp root@docs.example.com:', page)
        self.assertNotIn('--accept-mscorefonts-eula', page)

    def test_parameters_are_sanitised(self):
        page = self.get(provider='onlyoffice', mode='separate_server',
                        editor_host='docs.example.com$(id)', tls='certbot;id', edition='x`id`')
        self.assertNotIn('$(id)', page)
        self.assertNotIn('`id`', page)
        self.assertNotIn('certbot;id', page)
        self.assertIn('--tls existing-cert', page)

    def test_existing_service_has_no_installer(self):
        page = self.get(provider='onlyoffice', mode='existing_service')
        self.assertNotIn('install-editor.sh --provider', page)
        self.assertIn('Nothing to install', page)


class DrainProvider(FakeProvider):
    def __init__(self, support=True):
        self.support = support
        self.calls = []

    def force_save(self, session):
        self.calls.append(session.pk)
        if not self.support:
            raise NotSupported('no server-side save')
        return True


class OfficeSessionsTests(OfficeTestBase):

    def setUp(self):
        super().setUp()
        self.provider = DrainProvider()
        register(self.provider, replace=True)
        self.inst = self.make_instance()
        self.target_a = self.target()
        self.s1 = sessions.open_session(self.target_a, self.editor, mode='edit', instance=self.inst)
        self.s2 = sessions.open_session(self.target_a, self.owner, mode='edit', instance=self.inst)

    def test_status_lists_sessions_without_keys(self):
        out = run('office_sessions', '--status')
        self.assertIn(self.inst.name, out)
        self.assertIn('2 open session(s)', out)
        self.assertIn(self.editor.username, out)
        self.assertNotIn(self.s1.document_key, out)

    def test_drain_blocks_new_sessions_and_force_saves_each_group_once(self):
        def close_all(_seconds):
            for s in EditSession.objects.filter(state='open'):
                sessions.close(s, reason='user closed')
        with mock.patch('office.management.commands.office_sessions.time.sleep', side_effect=close_all):
            out = run('office_sessions', '--drain', str(self.inst.pk), '--timeout', '60', '--poll', '1')
        self.assertIn('is drained', out)
        self.assertEqual(self.provider.calls, [self.s1.pk])   # one co-editing group, one request
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.enabled)
        with self.assertRaises(NotConfigured):
            sessions.open_session(self.target(), self.editor, mode='edit', instance=self.inst)

    def test_drain_timeout_exits_nonzero_and_keeps_sessions(self):
        with self.assertRaises(SystemExit) as cm:
            run('office_sessions', '--drain', str(self.inst.pk), '--timeout', '0')
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(sessions.live_sessions().count(), 2)

    def test_drain_revoke_remaining(self):
        out = run('office_sessions', '--drain', str(self.inst.pk), '--timeout', '0', '--revoke-remaining')
        self.assertIn('Revoked 2 session(s)', out)
        self.assertEqual(sessions.live_sessions().count(), 0)
        self.assertEqual(EditSession.objects.filter(state='revoked').count(), 2)

    def test_drain_when_provider_cannot_force_save(self):
        self.provider.support = False
        with self.assertRaises(SystemExit):
            out = io.StringIO()
            call_command('office_sessions', '--drain', str(self.inst.pk), '--timeout', '0',
                         stdout=out, stderr=io.StringIO())
        self.assertIn('not supported', out.getvalue())

    def test_resume(self):
        EditorInstance.objects.filter(pk=self.inst.pk).update(enabled=False)
        run('office_sessions', '--resume', str(self.inst.pk))
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.enabled)

    def test_base_provider_force_save_is_not_supported(self):
        from .providers import EditorProvider
        with self.assertRaises(NotSupported):
            EditorProvider().force_save(self.s1)


class UpgradeSafetyTests(SimpleTestCase):
    """clientst0r's update path must never upgrade, restart or reconfigure an
    Office editor installed by scripts/office/install-editor.sh."""

    EDITOR_WORDS = re.compile(r'onlyoffice|documentserver|coolwsd|collabora|\bds-[a-z*]', re.I)
    UPDATE_PATH = [
        'scripts/auto_update.sh', 'scripts/install_auto_update.sh', 'deploy/update_instructions.sh',
        'update.sh', 'core/updater.py', 'core/upgrade/apply.py', 'core/upgrade/preflight.py',
        'core/upgrade/snapshot.py', 'core/upgrade/doctor.py', 'core/upgrade/revision.py',
        'core/management/commands/upgrade_apply.py', 'core/management/commands/auto_update.py',
        'core/management/commands/auto_heal_version.py', 'deploy/clientst0r-auto-update.service',
    ]

    def test_update_path_never_names_editor_services_or_packages(self):
        for rel in self.UPDATE_PATH:
            path = BASE / rel
            if not path.exists():
                continue
            text = path.read_text(errors='replace')
            hit = self.EDITOR_WORDS.search(text)
            self.assertIsNone(hit, f'{rel} mentions an Office editor ({hit and hit.group(0)})')

    def test_root_helper_cannot_restart_or_upgrade_editor(self):
        from core.tests.test_root_helper import load_helper
        h = load_helper()
        for unit in ('coolwsd.service', 'ds-docservice.service', 'nginx.service'):
            self.assertIsNone(h.SERVICE_RE.match(unit), unit)
        for pkg in ('onlyoffice-documentserver', 'coolwsd', 'code-brand', 'collabora-online-brand',
                    'collaboraoffice-core', 'onlyoffice-documentserver-ee:amd64'):
            with self.assertRaisesRegex(h.HelperError, 'install-editor.sh --upgrade'):
                h.apt_argv(['upgrade-packages', 'openssl', pkg])
        self.assertEqual(h.apt_argv(['upgrade-packages', 'openssl'])[-1], 'openssl')

    def test_package_updater_skips_editor_packages(self):
        from core.management.commands.update_system_packages import without_editor_packages
        kept, skipped = without_editor_packages(['openssl', 'coolwsd', 'onlyoffice-documentserver',
                                                 'collaboraofficebasis-core', 'libc6:amd64'])
        self.assertEqual(kept, ['openssl', 'libc6:amd64'])
        self.assertEqual(skipped, ['coolwsd', 'onlyoffice-documentserver', 'collaboraofficebasis-core'])

    def test_installer_pins_and_holds(self):
        text = (BASE / 'scripts/office/install-editor.sh').read_text()
        self.assertIn('Pin-Priority: 1001', text)
        self.assertIn('apt-mark hold', text)
