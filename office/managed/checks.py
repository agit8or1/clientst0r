"""Setup checks for Managed Local ONLYOFFICE.

    run(service) -> list[DiagnosticCheck]

1. The helper is installed and reachable (the socket), and its preflight:
   OS, CPU architecture, Docker + Compose, nftables, CPU, RAM (with the
   clientst0r reserve), disk, port conflicts, the local reverse proxy,
   subnet conflicts, DNS, an installable release, the license file.
2. From clientst0r, through office.net (the same SSRF rules editing uses):
   * clientst0r -> ONLYOFFICE over loopback (internal URL /healthcheck);
   * the browser URL over verified HTTPS through the reverse proxy (the
     certificate users' browsers will see; proves DNS, TLS and the proxy);
3. Once the provider is configured, the ONLYOFFICE provider's own
   diagnostics: signed requests (JWT), the published default secret is
   refused, ONLYOFFICE -> clientst0r (the container downloads a document
   from the callback address and converts it), the last real save callback,
   WebSockets and the browser probe (browser -> ONLYOFFICE, recorded from an
   administrator's browser).

Nothing here changes the server.
"""
from __future__ import annotations

from types import SimpleNamespace

from office import net
from office.providers import FAIL, NOT_RUN, PASS, WARN, DiagnosticCheck, get_provider

from . import ipc
from .provision import ProvisionError, managed_instance, urls_from_status

PREFLIGHT_LABELS = {
    'os': 'Supported operating system', 'arch': 'CPU architecture',
    'docker': 'Docker and Docker Compose', 'nftables': 'Container firewall (nftables)',
    'memory': 'Memory (editor limit + clientst0r reserve)', 'memory_limit': 'Editor memory limit',
    'swap': 'Swap', 'cpu': 'CPU', 'disk': 'Disk space', 'port': 'Loopback port',
    'proxy': 'Reverse proxy on this server', 'subnet': 'Container network',
    'dns': 'DNS', 'release': 'Pinned release', 'license': 'Enterprise license',
}
STATUS = {'pass': PASS, 'fail': FAIL, 'warn': WARN}


def _probe_instance(status):
    """An unsaved stand-in with the managed URLs, so net.fetch applies the
    managed-mode rules before any EditorInstance exists."""
    urls = urls_from_status(status)
    return SimpleNamespace(mode='managed_local', browser_url=urls['browser_url'],
                           internal_url=urls['internal_url'], ca_bundle='', verify_tls=True,
                           connect_timeout_s=5, request_timeout_s=15, public_only=False)


def _healthcheck(url, inst, key, label, remedy):
    try:
        r = net.fetch(url.rstrip('/') + '/healthcheck', inst, 4096)
    except net.OfficeFetchError as e:
        return DiagnosticCheck(key, label, FAIL, str(e)[:300], remedy)
    good = r.status_code == 200 and r.content.strip().lower() == b'true'
    return DiagnosticCheck(key, label, PASS if good else FAIL,
                           f'HTTP {r.status_code} from {url.rstrip("/")}/healthcheck'
                           + ('' if good else ' without "true"'), '' if good else remedy)


def run(service=None):
    checks = []
    add = checks.append
    try:
        status = ipc.call('status', timeout=15)
    except ipc.HelperError as e:
        add(DiagnosticCheck('helper', 'Office service helper', FAIL, str(e),
                            'Run scripts/office/install-editor.sh --mode managed-local as root on '
                            'this server (docs/office/MANAGED_LOCAL.md, "Setup").'))
        return checks
    add(DiagnosticCheck('helper', 'Office service helper', PASS,
                        f'Helper version {status.get("helper_version")}, reachable over its socket.'))
    try:
        pre = ipc.call('preflight', timeout=60)
    except ipc.HelperError as e:
        add(DiagnosticCheck('preflight', 'Server preflight', FAIL, str(e)))
        pre = {'checks': []}
    for c in pre.get('checks') or []:
        add(DiagnosticCheck(f'pre.{c.get("key")}', PREFLIGHT_LABELS.get(c.get('key'), c.get('key', '')),
                            STATUS.get(c.get('status'), NOT_RUN), str(c.get('detail', ''))[:500]))

    try:
        probe = _probe_instance(status)
    except ProvisionError as e:
        add(DiagnosticCheck('urls', 'Editor addresses', FAIL, str(e)))
        return checks
    running = ((status.get('container') or {}).get('running'))
    if running:
        add(_healthcheck(probe.internal_url, probe, 'cs_to_oo', 'clientst0r reaches ONLYOFFICE (loopback)',
                         'Check the container state and its logs (Diagnostics).'))
        add(_healthcheck(probe.browser_url, probe, 'https', 'Office host name over verified HTTPS '
                         '(DNS, certificate, reverse proxy)',
                         'Point the office host name at this server, install its certificate and the '
                         'Nginx server block (install-editor.sh --mode managed-local writes it). If this '
                         'server cannot reach its own public address, add the office host name to '
                         '/etc/hosts as 127.0.0.1.'))
    else:
        add(DiagnosticCheck('cs_to_oo', 'clientst0r reaches ONLYOFFICE (loopback)', NOT_RUN,
                            'The editor container is not running.', 'Install or start it first.'))

    inst = managed_instance()
    if inst is None or not running:
        add(DiagnosticCheck('oo', 'ONLYOFFICE provider checks (JWT, ONLYOFFICE -> clientst0r, '
                            'callbacks, WebSockets, browser)', NOT_RUN,
                            'Available once the editor is installed and configured.'))
        return checks
    try:
        checks.extend(get_provider('onlyoffice').diagnostics(inst))
    except Exception as e:      # a connector failure is a failed check, not a crash
        add(DiagnosticCheck('oo', 'ONLYOFFICE provider checks', FAIL, type(e).__name__))
    return checks
