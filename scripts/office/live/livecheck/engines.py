"""One adapter per managed engine. The engine is a run parameter
(``--engine collabora | onlyoffice``); everything engine-specific lives
here, so adding an engine (or following changes on dev/office-engines) is
one class.

What an adapter provides (the harness never calls Docker itself; every
lifecycle step goes through clientst0r's own code paths):

    available()            (bool, detail): this clientst0r has the engine
    status()               the Office service helper's status (office.managed.ipc)
    instance()             the managed EditorInstance
    service()              the ManagedOfficeService row
    queue(action, user, release='')   ``manage.py office_managed --queue``
    run_pending()          ``manage.py office_managed --run-pending`` (what the
                           scheduler runs every minute)
    operation(pk)          the ManagedOfficeOperation
    releases()             the helper's release list for this engine
    release_file / release_list_name   where mark-tested edits the list
    browser                selectors, click positions and keys for the worker
    url_mode(instance)     'hostname' (own HTTPS host name) or 'path' (same
                           host, editor under /browser, /cool, ...)
    editor_paths           the URL path prefixes the editor uses in path mode
    nginx_candidates       where the office server block may live (read only)

ONLYOFFICE matches the code on v3.17.670 exactly. Collabora follows the
same managed design and is detected at run time: the helper status must
name the engine (``config.engine == 'collabora'``) and the managed instance
must use the ``collabora`` provider. ASSUMPTIONS to confirm against
dev/office-engines are marked ``ENGINES-HOOK`` below.
"""
from __future__ import annotations

import io
import os
from urllib.parse import urlsplit

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
HELPER_FILE = os.path.join(REPO, 'deploy', 'office-helper', 'clientst0r-office-helper')


class EngineUnavailable(Exception):
    pass


ONLYOFFICE_BROWSER = {
    'frame': 'iframe[name="frameEditor"]',
    'ready_page': [],
    'ready_frame': ['#editor_sdk'],
    'settle_ms': 3000,
    'save_button': '#onlyoffice-save-now',
    # Fractions of the editor frame: the document body, a cell, the title
    # placeholder of the first slide (the slide list is on the left).
    'click': {'docx': (0.5, 0.45), 'xlsx': (0.3, 0.35), 'pptx': (0.58, 0.4)},
    'clicks': {'docx': 1, 'xlsx': 1, 'pptx': 1},
    'keys_before': {'docx': ['Control+End'], 'xlsx': ['Control+Home'], 'pptx': []},
    'keys_after': {'docx': [], 'xlsx': ['Enter'], 'pptx': ['Escape']},
    'type_delay_ms': 40,
}

COLLABORA_BROWSER = {
    'frame': '#collabora-frame',
    # office-collabora.js enables "Save now" on Document_Loaded.
    'ready_page': [],
    'ready_frame': ['#document-container'],
    'settle_ms': 3000,
    'save_button': '#collabora-save-now',
    'click': {'docx': (0.5, 0.5), 'xlsx': (0.3, 0.4), 'pptx': (0.6, 0.45)},
    'clicks': {'docx': 1, 'xlsx': 1, 'pptx': 2},
    'keys_before': {'docx': ['Control+End'], 'xlsx': ['Control+Home'], 'pptx': []},
    'keys_after': {'docx': [], 'xlsx': ['Enter'], 'pptx': ['Escape']},
    'type_delay_ms': 40,
}


class ManagedEngine:
    name = ''
    provider = ''
    browser = {}
    editor_paths = ()
    release_file = HELPER_FILE
    release_list_name = 'RELEASES'
    nginx_candidates = ()

    # -- Django-side helpers (imported lazily) -------------------------
    def _ipc(self):
        from office.managed import ipc
        return ipc

    def status(self):
        return self._ipc().call('status')

    def service(self):
        from office.models import ManagedOfficeService
        return ManagedOfficeService.get()

    def instance(self):
        from office.managed.provision import managed_instance
        inst = managed_instance()
        if inst is not None and inst.provider != self.provider:
            return None
        return inst

    def _command_options(self):
        """Options of ``office_managed`` (an engine switch, if the engines
        branch adds one)."""
        from office.management.commands.office_managed import Command
        parser = Command().create_parser('manage.py', 'office_managed')
        return {a.dest for a in parser._actions}

    def _engine_kwargs(self):
        # ENGINES-HOOK: if office_managed grows --engine, pass ours.
        return {'engine': self.name} if 'engine' in self._command_options() else {}

    def queue(self, action, user, release=''):
        from django.core.management import call_command
        from office.managed import jobs
        out = io.StringIO()
        call_command('office_managed', queue=action, release=release, user=user.username,
                     stdout=out, **self._engine_kwargs())
        op = jobs.active()
        if op is None or op.action != action:
            raise RuntimeError(f'queued {action} but no matching active operation: {out.getvalue()[:300]}')
        return op

    def run_pending(self):
        from django.core.management import call_command
        out = io.StringIO()
        call_command('office_managed', run_pending=True, stdout=out, **self._engine_kwargs())
        return out.getvalue().strip()

    def operation(self, pk):
        from office.models import ManagedOfficeOperation
        return ManagedOfficeOperation.objects.get(pk=pk)

    def active_operation(self):
        from office.managed import jobs
        return jobs.active()

    def releases(self):
        rel = self._ipc().call('releases')
        return [r for r in rel.get('releases') or [] if self.release_matches(r)]

    def release_matches(self, r):
        return True

    def status_engine(self, status):
        conf = (status or {}).get('config') or {}
        return conf.get('engine') or (status or {}).get('engine') or 'onlyoffice'

    def available(self):
        try:
            status = self.status()
        except Exception as e:   # noqa: BLE001 - reported, never raised
            return False, f'helper: {type(e).__name__}: {e}'
        eng = self.status_engine(status)
        if eng != self.name:
            return False, (f'the managed service on this host runs {eng}, not {self.name}')
        return True, ''

    # -- URLs ---------------------------------------------------------------
    def url_mode(self, instance, base_url):
        """'path' when the editor is served on clientst0r's own origin."""
        b = urlsplit(getattr(instance, 'browser_url', '') or '')
        c = urlsplit(base_url or '')
        if b.hostname and c.hostname and b.hostname.lower() == c.hostname.lower() \
                and (b.port or 443) == (c.port or 443):
            return 'path'
        return 'hostname'


class OnlyofficeEngine(ManagedEngine):
    name = 'onlyoffice'
    provider = 'onlyoffice'
    browser = ONLYOFFICE_BROWSER
    editor_paths = ()      # path mode is not supported for ONLYOFFICE (MANAGED_LOCAL.md)
    release_list_name = 'RELEASES'
    nginx_candidates = ('/etc/nginx/sites-available/clientst0r-office-managed',)

    def release_matches(self, r):
        return 'onlyoffice' in (r.get('image') or '')


class CollaboraEngine(ManagedEngine):
    name = 'collabora'
    provider = 'collabora'
    browser = COLLABORA_BROWSER
    # Collabora Online's browser-facing paths (same-host path mode).
    editor_paths = ('/browser/', '/cool/', '/hosting/discovery', '/hosting/capabilities',
                    '/loleaflet/', '/lool/')
    # ENGINES-HOOK: the Collabora release list. Assumed to be a second
    # Python list literal in the same helper; override with --release-file
    # / --release-list on mark-tested if dev/office-engines puts it elsewhere.
    release_list_name = 'COLLABORA_RELEASES'
    # ENGINES-HOOK: the nginx block the root-helper operation installs.
    nginx_candidates = ('/etc/nginx/snippets/clientst0r-office-collabora.conf',
                        '/etc/nginx/sites-available/clientst0r-office-collabora',
                        '/etc/nginx/sites-available/clientst0r-office-managed',
                        '/etc/nginx/sites-enabled/itdocs.conf')

    def release_matches(self, r):
        return 'collabora' in (r.get('image') or '') or r.get('engine') == 'collabora'


ENGINES = {'collabora': CollaboraEngine, 'onlyoffice': OnlyofficeEngine}


def get(name):
    try:
        return ENGINES[name]()
    except KeyError:
        raise EngineUnavailable(f'unknown engine {name!r}; one of {", ".join(ENGINES)}')
