"""
Phase 34.2 (v3.17.545) — per-vendor config collection over SSH.

An adapter's whole job is to know which command prints the running config on a
given platform and how to tidy what comes back. The transport is shared: it is
the same SSH session either way, and duplicating it per vendor would mean fixing
a timeout bug in six places.

`paramiko` is imported lazily. It is in `requirements.txt`, but an install that
has not re-run pip since upgrading should keep working everywhere except this
one feature, which reports the missing dependency instead of failing at import
time and taking the whole app with it.
"""
from __future__ import annotations

import re


class CollectionError(Exception):
    """Anything that stopped a collection. The message reaches the operator."""


class BaseAdapter:
    """A platform. Subclasses supply the command and any output tidying."""

    key = 'generic'
    label = 'Generic (single command)'
    # Command that prints the running configuration.
    config_command = ''
    # Optional second command whose output carries a version string.
    version_command = ''
    version_pattern = ''

    #: Devices that page their output need this sent first, or the config
    #: arrives with "--More--" every 24 lines.
    setup_commands: list[str] = []

    def clean(self, raw: str) -> str:
        """Trim the shell noise around the config itself.

        The default strips the echoed command and any trailing prompt, which is
        what every platform tested so far needed.
        """
        lines = (raw or '').splitlines()
        if lines and self.config_command and self.config_command in lines[0]:
            lines = lines[1:]
        # A trailing prompt line has no whitespace and ends in # or >.
        while lines and re.match(r'^\S*[#>]\s*$', lines[-1]):
            lines.pop()
        return '\n'.join(line.rstrip() for line in lines).strip('\n')

    def extract_version(self, raw: str) -> str:
        if not (self.version_pattern and raw):
            return ''
        match = re.search(self.version_pattern, raw, re.IGNORECASE | re.MULTILINE)
        return (match.group(1).strip() if match else '')[:120]


class CiscoIOSAdapter(BaseAdapter):
    key = 'cisco_ios'
    label = 'Cisco IOS / IOS-XE'
    config_command = 'show running-config'
    version_command = 'show version'
    version_pattern = r'Version\s+([^\s,]+)'
    setup_commands = ['terminal length 0']


class CiscoASAAdapter(BaseAdapter):
    key = 'cisco_asa'
    label = 'Cisco ASA'
    config_command = 'show running-config'
    version_command = 'show version'
    version_pattern = r'Version\s+([^\s,]+)'
    setup_commands = ['terminal pager 0']


class AristaEOSAdapter(BaseAdapter):
    key = 'arista_eos'
    label = 'Arista EOS'
    config_command = 'show running-config'
    version_command = 'show version'
    version_pattern = r'Software image version:\s+(\S+)'
    setup_commands = ['terminal length 0']


class JuniperJunosAdapter(BaseAdapter):
    key = 'juniper_junos'
    label = 'Juniper Junos'
    config_command = 'show configuration | display set | no-more'
    version_command = 'show version'
    version_pattern = r'Junos:\s+(\S+)'


class MikroTikAdapter(BaseAdapter):
    key = 'mikrotik'
    label = 'MikroTik RouterOS'
    config_command = '/export'
    version_command = '/system resource print'
    version_pattern = r'version:\s+(\S+)'


class FortiOSAdapter(BaseAdapter):
    key = 'fortios'
    label = 'Fortinet FortiOS'
    config_command = 'show full-configuration'
    version_command = 'get system status'
    version_pattern = r'Version:\s+(.+?)(?:,|$)'


class HPProCurveAdapter(BaseAdapter):
    key = 'hp_procurve'
    label = 'HP / Aruba ProCurve'
    config_command = 'show running-config'
    version_command = 'show version'
    version_pattern = r'Revision\s+(\S+)'
    setup_commands = ['no page']


ADAPTERS = {
    a.key: a for a in [
        BaseAdapter, CiscoIOSAdapter, CiscoASAAdapter, AristaEOSAdapter,
        JuniperJunosAdapter, MikroTikAdapter, FortiOSAdapter, HPProCurveAdapter,
    ]
}

ADAPTER_CHOICES = [(key, cls.label) for key, cls in ADAPTERS.items()]


def get_adapter(key: str) -> BaseAdapter:
    cls = ADAPTERS.get(key or 'generic', BaseAdapter)
    return cls()


def collect_over_ssh(target, password, *, timeout=30):
    """Run the adapter's commands on `target` and return `(config, version)`.

    `password` is the plaintext, already decrypted by the caller — this
    function never touches the vault, so the decision about whether a
    credential may be used unattended stays in one place.
    """
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise CollectionError(
            'SSH collection needs the paramiko package, which is not installed. '
            'Run pip install -r requirements.txt and retry.'
        ) from exc

    adapter = get_adapter(target.adapter)
    if not adapter.config_command and not target.config_command:
        raise CollectionError(
            'No command configured to print the running config for this device.')
    config_command = target.config_command or adapter.config_command

    client = paramiko.SSHClient()
    # Devices are identified by the address the operator configured, on a
    # network they administer. Refusing an unknown host key here would mean
    # every new switch fails its first backup until somebody SSHes in by hand,
    # so unknown keys are accepted — and this is exactly why the transport does
    # not accept credentials that require per-use approval.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=target.host,
            port=target.port or 22,
            username=target.username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
    except Exception as exc:
        raise CollectionError(f'Could not connect: {exc}') from exc

    try:
        for command in adapter.setup_commands:
            _run(client, command, timeout)

        raw_config = _run(client, config_command, timeout)
        config = adapter.clean(raw_config)
        if not config.strip():
            raise CollectionError(
                f'"{config_command}" returned nothing. Check the command and '
                'that the account has permission to run it.')

        version = ''
        version_command = target.version_command or adapter.version_command
        if version_command:
            try:
                version = adapter.extract_version(_run(client, version_command, timeout))
            except Exception:
                # A missing version string is not a reason to throw away a
                # config that came back fine.
                version = ''
        return config, version
    finally:
        client.close()


def _run(client, command, timeout):
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    if not out.strip():
        err = stderr.read().decode('utf-8', errors='replace').strip()
        if err:
            raise CollectionError(f'"{command}" failed: {err[:300]}')
    return out
