"""P0-4 (docs/ux/STANDALONE_REQUIREMENTS.md, rule F1): every outbound request
has an explicit timeout.

An AST scan of the project's Python (not venv, migrations, tests, node
folders or .wt-* worktrees) for

* ``requests.get/post/put/patch/delete/head/options/request(...)``,
* ``.get/.post/... / .request(...)`` on a name bound to ``requests.Session()``
  (or any ``*Session(...)`` call, or ``requests.session()``),
* ``urllib.request.urlopen(...)`` / ``urlopen(...)``,
* ``httpx.get/post/.../request(...)`` and ``httpx.Client(...)`` /
  ``httpx.AsyncClient(...)`` without a default timeout,
* ``socket.create_connection(...)``

that has no ``timeout=`` keyword (a ``**kwargs`` splat is accepted: the
caller supplies it; a positional timeout for ``urlopen`` /
``create_connection`` counts too). A new unbounded call fails here with
``file:line``.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

EXCLUDE_DIRS = {'venv', '.venv', 'node_modules', 'migrations', 'tests', 'static', 'staticfiles', 'media',
                '__pycache__', '.git', 'site-packages', 'mobile', 'mobile-app', 'local_apps'}
VERBS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'request'}


def _excluded(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    if any(p in EXCLUDE_DIRS or p.startswith('.wt-') or p.startswith('.dev-worktree') for p in parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith(('test_', 'tests_')) or name in ('tests.py', 'testing.py', 'conftest.py')


def _dotted(node):
    out = []
    while isinstance(node, ast.Attribute):
        out.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        out.append(node.id)
        return '.'.join(reversed(out))
    return ''


def _has_timeout(call: ast.Call, positional_at=None) -> bool:
    for kw in call.keywords:
        if kw.arg == 'timeout' or kw.arg is None:
            return True
    return positional_at is not None and len(call.args) > positional_at


class _Scanner(ast.NodeVisitor):
    def __init__(self):
        self.sessions = set()
        self.hits = []

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call):
            fn = _dotted(node.value.func)
            last = fn.rsplit('.', 1)[-1]
            if last.endswith('Session') or last in ('session', 'get_session', 'build_session', 'make_session',
                                                    'new_session', 'guarded_session'):
                for t in node.targets:
                    name = _dotted(t)
                    if name:
                        self.sessions.add(name)
        self.generic_visit(node)

    def visit_Call(self, node):
        fn = _dotted(node.func)
        if fn:
            head, _, last = fn.rpartition('.')
            line = node.lineno
            if head in ('requests', 'httpx') and last in VERBS:
                if not _has_timeout(node):
                    self.hits.append((line, fn))
            elif head in self.sessions and last in VERBS:
                if not _has_timeout(node):
                    self.hits.append((line, fn))
            elif fn in ('urllib.request.urlopen', 'urlopen', 'request.urlopen'):
                if not _has_timeout(node, positional_at=2):
                    self.hits.append((line, fn))
            elif fn == 'socket.create_connection':
                if not _has_timeout(node, positional_at=1):
                    self.hits.append((line, fn))
            elif fn in ('httpx.Client', 'httpx.AsyncClient'):
                if not _has_timeout(node):
                    self.hits.append((line, fn))
        self.generic_visit(node)


def scan(root: Path):
    hits = []
    for path in sorted(root.rglob('*.py')):
        if _excluded(path, root):
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanner = _Scanner()
        scanner.visit(tree)
        hits += [f'{path.relative_to(root)}:{line}: {fn}(...) has no timeout=' for line, fn in scanner.hits]
    return hits


class OutboundTimeoutLintTests(SimpleTestCase):

    def test_every_outbound_call_has_a_timeout(self):
        hits = scan(Path(settings.BASE_DIR))
        self.assertEqual(hits, [], 'Outbound calls without an explicit timeout (rule F1):\n' + '\n'.join(hits))

    def test_scanner_finds_unbounded_calls(self):
        src = ('import requests, socket\nfrom urllib.request import urlopen\n'
               's = requests.Session()\n'
               'requests.get("u")\nrequests.post("u", timeout=3)\ns.get("u")\ns.get("u", timeout=(3, 5))\n'
               'urlopen("u")\nurlopen("u", timeout=3)\nsocket.create_connection(("h", 1))\n'
               'requests.get("u", **kw)\nd = {}\nd.get("k")\n')
        sc = _Scanner()
        sc.visit(ast.parse(src))
        self.assertEqual(sorted(line for line, _ in sc.hits), [4, 6, 8, 10])


class InteractiveBudgetTests(SimpleTestCase):
    """"Test connection" and console-link calls are short: connect <= 5 s,
    read <= 10 s, one retry, 15 s in total; a sync keeps its own budget."""

    def _provider(self):
        import requests
        from integrations.providers.base import BaseProvider

        class Dummy(BaseProvider):
            provider_name = 'Dummy'

            def __init__(self):
                self.base_url = 'https://dummy.example.com'
                self.session = requests.Session()
                self.seen = []

            def _get_auth_headers(self):
                return {}

            def test_connection(self):
                self.seen.append((self._interactive_deadline is not None,
                                  self.session.get_adapter(self.base_url).max_retries.total))
                self._make_request('GET', '/ping')
                return True

            def list_things(self):
                return self._make_request('GET', '/things')
        return Dummy()

    def test_test_connection_uses_the_short_budget_and_restores_it(self):
        from unittest import mock
        p = self._provider()
        calls = []
        p.session.request = lambda method, url, **kw: calls.append(kw) or mock.Mock(status_code=200)
        before = p.session.get_adapter(p.base_url).max_retries.total
        self.assertTrue(p.test_connection())
        self.assertEqual(p.seen, [(True, 1)])
        connect, read = calls[0]['timeout']
        self.assertLessEqual(connect, 5)
        self.assertLessEqual(read, 10)
        self.assertEqual(p.session.get_adapter(p.base_url).max_retries.total, before)
        self.assertIsNone(p._interactive_deadline)
        calls.clear()
        p.list_things()                       # a sync call keeps the long budget
        self.assertEqual(calls[0]['timeout'], 30)

    def test_total_deadline_stops_further_calls(self):
        from integrations.providers.base import ProviderError
        p = self._provider()
        with p.interactive(total=0):
            with self.assertRaises(ProviderError):
                p._make_request('GET', '/x')
