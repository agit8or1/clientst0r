"""
Glue between the Office branches: the drain hook on ONLYOFFICE, and
Collabora instances that share no secret with clientst0r.
"""
from office import diagnostics, sessions, targets
from office.forms import EditorInstanceForm
from office.models import EditSession
from office.tests_onlyoffice import OnlyOfficeTestBase
from office import tests as core


class OnlyOfficeForceSaveTests(OnlyOfficeTestBase):

    def test_drain_force_save_uses_the_command_service(self):
        _t, s, _page = self.setup_doc()
        self.assertTrue(self.provider.force_save(s))
        cmd = self.ds.commands[-1]
        self.assertEqual((cmd['c'], cmd['key']), ('forcesave', self.key(s)))

    def test_no_changes_counts_as_saved(self):
        _t, s, _page = self.setup_doc()
        self.ds.no_changes = True
        self.assertTrue(self.provider.force_save(s))

    def test_refusal_is_reported(self):
        _t, s, _page = self.setup_doc()
        self.ds.open_keys.clear()  # Docs no longer knows the key
        self.assertFalse(self.provider.force_save(s))

    def test_session_never_opened_has_nothing_to_save(self):
        inst = self.make_instance()
        t = targets.target_for(self.make_doc())
        s = sessions.open_session(t, self.editor, mode='edit', instance=inst)
        n = len(self.ds.commands)
        self.assertTrue(self.provider.force_save(EditSession.objects.get(pk=s.pk)))
        self.assertEqual(len(self.ds.commands), n)


class SecretPerProviderTests(core.OfficeTestBase):

    def _form(self, provider, secret=''):
        return EditorInstanceForm(data={
            'provider': provider, 'name': f'{provider} 1', 'mode': 'separate_server',
            'browser_url': 'https://docs.example.com/', 'callback_base_url': 'https://app.example.com/',
            'shared_secret': secret, 'shared': 'on', 'max_file_mb': 50,
            'connect_timeout_s': 5, 'request_timeout_s': 30, 'conversion_timeout_s': 60, 'enabled': 'on'})

    def test_onlyoffice_needs_a_secret(self):
        f = self._form('onlyoffice')
        f.is_valid()
        self.assertIn('shared_secret', f.errors)

    def test_collabora_needs_none(self):
        f = self._form('collabora')
        f.is_valid()
        self.assertNotIn('shared_secret', f.errors)

    def test_default_secret_still_refused(self):
        f = self._form('collabora', 'verysecretstring')
        f.is_valid()
        self.assertIn('shared_secret', f.errors)

    def test_collabora_without_secret_passes_the_secret_check(self):
        inst = self.make_instance(provider='collabora', shared_secret='')
        check = {c.key: c for c in diagnostics.config_checks(inst)}['config.secret']
        self.assertEqual(check.status, 'pass')
        self.assertIn('Not used', check.detail)
