"""Setup checks for the managed local editor (ONLYOFFICE or Collabora CODE).

    run(service) -> list[DiagnosticCheck]

1. The helper is installed and reachable (the socket), and its preflight
   for the chosen engine: OS, CPU architecture, Docker + Compose, nftables,
   capacity (memory limit vs. what is available now, the clientst0r
   reserve, CPU left for clientst0r, swap), disk, port conflicts, the local
   reverse proxy, the callback route, subnet conflicts, DNS, an installable
   release, the license file.
2. The editor host name (``reverse_proxy_checks``):
   * DNS resolves the editor host name to this server (or to the same
     address as clientst0r's host name, i.e. the TLS device in front);
   * certificate present and valid for the name (the helper reads it when
     this server holds it; with TLS terminated in front, the verified HTTPS
     request below proves it);
   * the helper's Nginx files are installed and current; for the same-host
     layout, clientst0r's site includes the snippet (read-only check);
3. The three paths:
   * clientst0r -> editor over loopback (internal URL);
   * the browser URL over verified HTTPS through the reverse proxy (DNS,
     certificate and proxy as users' browsers meet them, from this server);
   * editor -> clientst0r from inside the container (helper
     ``callback-check``: TCP + verified TLS to clientst0r's host name);
   * browser -> editor: the last browser probe recorded from an
     administrator's browser on the Managed page;
4. Once the provider is configured, the provider's own diagnostics.

Nothing here changes the server.
"""
from __future__ import annotations

from types import SimpleNamespace

from office import net
from office.providers import FAIL, NOT_RUN, PASS, WARN, DiagnosticCheck, get_provider

from . import ipc
from .provision import ProvisionError, managed_instance, status_engine, urls_from_status

PREFLIGHT_LABELS = {
    'os': 'Supported operating system', 'arch': 'CPU architecture',
    'docker': 'Docker and Docker Compose', 'nftables': 'Container firewall (nftables)',
    'openssl': 'OpenSSL (WOPI proof key)',
    'memory': 'Memory (editor limit + clientst0r reserve)',
    'memory_available': 'Memory available now (would the editor starve clientst0r?)',
    'memory_limit': 'Editor memory limit', 'capacity': 'Capacity verdict',
    'swap': 'Swap', 'cpu': 'CPU left for clientst0r', 'disk': 'Disk space', 'port': 'Loopback port',
    'proxy': 'Reverse proxy on this server', 'callback': 'Callback route (editor -> clientst0r)',
    'nginx': 'Nginx', 'subnet': 'Container network',
    'dns': 'DNS', 'release': 'Pinned release', 'license': 'Enterprise license',
}
STATUS = {'pass': PASS, 'fail': FAIL, 'warn': WARN}
ENGINE_LABELS = {'onlyoffice': 'ONLYOFFICE', 'collabora': 'Collabora'}
HEALTH_PATHS = {'onlyoffice': '/healthcheck', 'collabora': '/hosting/discovery'}


def _probe_instance(status):
    """An unsaved stand-in with the managed URLs, so net.fetch applies the
    managed-mode rules before any EditorInstance exists."""
    urls = urls_from_status(status)
    return SimpleNamespace(mode='managed_local', browser_url=urls['browser_url'],
                           internal_url=urls['internal_url'], ca_bundle='', verify_tls=True,
                           connect_timeout_s=5, request_timeout_s=15, public_only=False)


def _healthcheck(url, inst, key, label, remedy, engine='onlyoffice'):
    path = HEALTH_PATHS[engine]
    try:
        r = net.fetch(url.rstrip('/') + path, inst, 256 * 1024)
    except net.OfficeFetchError as e:
        return DiagnosticCheck(key, label, FAIL, str(e)[:300], remedy)
    if engine == 'collabora':
        good = r.status_code == 200 and b'wopi-discovery' in r.content
        what = 'a WOPI discovery document'
    else:
        good = r.status_code == 200 and r.content.strip().lower() == b'true'
        what = '"true"'
    return DiagnosticCheck(key, label, PASS if good else FAIL,
                           f'HTTP {r.status_code} from {url.rstrip("/")}{path}'
                           + ('' if good else f' without {what}'), '' if good else remedy)


def capacity_checks(status, engine):
    """The helper's capacity verdict for `engine` as checks (also shown on the
    Managed page)."""
    cap = ((status or {}).get('capacity') or {}).get(engine)
    if not cap:
        return []
    return [DiagnosticCheck(f'capacity.{engine}', f'Capacity for {ENGINE_LABELS[engine]} on this server',
                            STATUS.get(cap.get('verdict'), NOT_RUN), str(cap.get('recommendation', ''))[:500])]


def reverse_proxy_checks(status):
    """DNS, certificate, Nginx files and (same-host) the include line, from
    the helper's read-only proxy-status."""
    out = []
    try:
        ps = ipc.call('proxy-status', timeout=30)
    except ipc.HelperError as e:
        return [DiagnosticCheck('proxy', 'Reverse proxy for the editor', FAIL, str(e)[:300])]
    host, layout = ps.get('hostname') or '', ps.get('layout') or 'dedicated'
    dns = ps.get('dns') or {}
    if not dns.get('editor'):
        out.append(DiagnosticCheck('proxy.dns', f'DNS for {host}', FAIL, f'{host} does not resolve.',
                                   'Create the DNS record for the editor host name.'))
    else:
        here = dns.get('points_here')
        out.append(DiagnosticCheck(
            'proxy.dns', f'DNS for {host}', PASS if here else WARN,
            f'{host} resolves to {", ".join(dns["editor"][:4])}'
            + ('' if here else f'; clientst0r\'s host name resolves to '
                                f'{", ".join(dns.get("clientstor", [])[:4]) or "nothing"}'),
            '' if here else 'Point the editor host name at this server (or at the TLS device in '
                            'front of it, like clientst0r\'s own name).'))
    cert = ps.get('certificate') or {}
    if cert.get('checked_here'):
        out.append(DiagnosticCheck('proxy.cert', 'Certificate for the editor host name',
                                   PASS if cert.get('ok') else FAIL,
                                   f'{cert.get("path", "")}: {cert.get("detail", "")}'
                                   + (f' (until {cert["not_after"]})' if cert.get('not_after') else ''),
                                   '' if cert.get('ok') else 'Install a certificate for the editor '
                                   'host name (PROXY_CERT_FILE/PROXY_KEY_FILE, or Let\'s Encrypt).'))
    else:
        out.append(DiagnosticCheck('proxy.cert', 'Certificate for the editor host name', NOT_RUN,
                                   (cert.get('detail') or '') + ' Proven by the verified HTTPS check '
                                   'below.'))
    if ps.get('problem'):
        out.append(DiagnosticCheck('proxy.files', 'Nginx configuration for the editor', FAIL,
                                   ps['problem'][:300]))
    elif ps.get('installed'):
        out.append(DiagnosticCheck('proxy.files', 'Nginx configuration for the editor', PASS,
                                   f'Installed and current for {host} ({layout}).'))
    else:
        out.append(DiagnosticCheck('proxy.files', 'Nginx configuration for the editor', FAIL,
                                   f'Not installed (or not current) for {host} ({layout}).',
                                   'Use "Install proxy configuration" below.'))
    site = ps.get('clientstor_site') or {}
    if layout == 'same-host':
        site_name = site.get('file') or "clientst0r's site"
        site_path = site.get('path') or "clientst0r's Nginx site"
        out.append(DiagnosticCheck(
            'proxy.include', 'clientst0r\'s site includes the editor locations',
            PASS if ps.get('include_present') else FAIL,
            f'{site_name}: ' + ('include present.' if ps.get('include_present') else 'include missing.'),
            '' if ps.get('include_present') else
            f'Add "{ps.get("include_line")}" once inside the server block of {site_path}, then '
            'nginx -t and reload Nginx.'))
    elif site:
        out.append(DiagnosticCheck('proxy.site', 'clientst0r\'s existing site', PASS,
                                   f'{site.get("file")} (server_name {" ".join(site.get("server_names") or [])};'
                                   f' listen {", ".join(site.get("listen") or [])}) - read, never modified.'))
    return out


def browser_probe_check(service):
    from .probe import last_probe
    probe = last_probe()
    if probe is None:
        return DiagnosticCheck('browser', 'Browser reaches the editor', NOT_RUN,
                               'No browser probe recorded yet.',
                               'Use "Run browser probe" on the Managed page.')
    outcome = (probe.extra_data or {}).get('outcome', '')
    return DiagnosticCheck('browser', 'Browser reaches the editor', PASS if outcome == 'reached' else FAIL,
                           f'{probe.timestamp:%Y-%m-%d %H:%M} UTC by {probe.username}: '
                           f'{(probe.extra_data or {}).get("url", "")} {outcome}.')


def callback_check():
    try:
        r = ipc.call('callback-check', timeout=60)
    except ipc.HelperError as e:
        return DiagnosticCheck('editor_to_cs', 'Editor reaches clientst0r (callbacks)', NOT_RUN, str(e)[:300])
    return DiagnosticCheck(
        'editor_to_cs', 'Editor reaches clientst0r (callbacks)', PASS if r.get('ok') else FAIL,
        f'From inside the container to {r.get("target")} ({r.get("route")}): '
        + ('verified TLS connection.' if r.get('ok') else (r.get('detail') or 'failed')[:300]),
        '' if r.get('ok') else 'Check CALLBACK_ROUTE / CALLBACK_UPSTREAM_IP in the root config, the '
                               'TLS device in front of this server, and clientst0r\'s certificate.')


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
        engine = status_engine(status)
    except ProvisionError as e:
        add(DiagnosticCheck('engine', 'Editor engine', FAIL, str(e)))
        return checks
    installed = status.get('installed') or {}
    present = installed.get('release') and installed.get('state') != 'uninstalled'
    wanted = engine if present or service is None else (service.engine or engine)
    try:
        pre = ipc.call('preflight', {'engine': wanted}, timeout=60)
    except (ipc.HelperError, ValueError) as e:
        add(DiagnosticCheck('preflight', 'Server preflight', FAIL, str(e)))
        pre = {'checks': []}
    for c in pre.get('checks') or []:
        add(DiagnosticCheck(f'pre.{c.get("key")}', PREFLIGHT_LABELS.get(c.get('key'), c.get('key', '')),
                            STATUS.get(c.get('status'), NOT_RUN), str(c.get('detail', ''))[:500]))
    checks.extend(capacity_checks(status, wanted))
    checks.extend(reverse_proxy_checks(status))

    try:
        probe = _probe_instance(status)
    except ProvisionError as e:
        add(DiagnosticCheck('urls', 'Editor addresses', FAIL, str(e)))
        return checks
    running = ((status.get('container') or {}).get('running'))
    label = ENGINE_LABELS[engine]
    if running:
        add(_healthcheck(probe.internal_url, probe, 'cs_to_oo', f'clientst0r reaches {label} (loopback)',
                         'Check the container state and its logs (Diagnostics).', engine))
        add(_healthcheck(probe.browser_url, probe, 'https', 'Editor host name over verified HTTPS '
                         '(DNS, certificate, reverse proxy)',
                         'Point the editor host name at this server, make sure its certificate is '
                         'valid, and install the proxy configuration. If this server cannot reach its '
                         'own public address, add the host name to /etc/hosts as 127.0.0.1.', engine))
        add(callback_check())
    else:
        add(DiagnosticCheck('cs_to_oo', f'clientst0r reaches {label} (loopback)', NOT_RUN,
                            'The editor container is not running.', 'Install or start it first.'))
    add(browser_probe_check(service))

    inst = managed_instance(engine)
    if inst is None or not running:
        add(DiagnosticCheck('oo', f'{label} provider checks', NOT_RUN,
                            'Available once the editor is installed and configured.'))
        return checks
    try:
        checks.extend(get_provider(inst.provider).diagnostics(inst))
    except Exception as e:      # a connector failure is a failed check, not a crash
        add(DiagnosticCheck('oo', f'{label} provider checks', FAIL, type(e).__name__))
    return checks
