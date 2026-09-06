#!/usr/bin/env python3
"""
Client St0r site collector — reference implementation (Phase 33, v3.17.558).

Runs on a small box inside a client's network, asks the server what to scan,
sweeps, and posts the results back. It polls; nothing ever connects *into* the
client network.

What it does, with no dependencies beyond the standard library:
  * fetches its scan configuration
  * ping-sweeps the configured subnets (or the local ones)
  * reads this machine's own ARP table for MAC addresses
  * posts devices back

What it does NOT do:
  * no credentials for anything on the network
  * no vulnerability or exploit scanning
  * no writes or changes to any device
  * nothing persistent beyond this process and its systemd timer

SNMP (LLDP/CDP neighbours and bridge tables) is the one part left as an
extension point rather than shipped half-built: it needs `pysnmp` and real
switch hardware to validate against, and an untested SNMP walk that silently
returns nothing would be worse than an honest gap. The server accepts and
stores that data today — see `emit_neighbours()` below for the shape it wants.

Usage:
    collector.py --server https://clientst0r.example.com --key <site key>
    collector.py --server ... --key ... --once --dry-run
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

COLLECTOR_VERSION = '1.0'


def fetch_config(server, key, timeout=30):
    request = urllib.request.Request(
        f'{server.rstrip("/")}/network-discovery/collector/config/',
        headers={'X-Discovery-Key': key,
                 'X-Collector-Version': COLLECTOR_VERSION})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))['config']


def post_results(server, key, payload, timeout=120):
    body = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        f'{server.rstrip("/")}/network-discovery/collector/results/',
        data=body, method='POST',
        headers={'X-Discovery-Key': key,
                 'Content-Type': 'application/json',
                 'X-Collector-Version': COLLECTOR_VERSION})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def local_subnets():
    """Best-effort local IPv4 networks, without extra packages."""
    found = []
    try:
        out = subprocess.run(['ip', '-4', '-o', 'addr', 'show'],
                             capture_output=True, text=True, timeout=10).stdout
        for match in re.finditer(r'inet (\d+\.\d+\.\d+\.\d+/\d+)', out):
            cidr = match.group(1)
            if not cidr.startswith('127.'):
                found.append(str(ipaddress.ip_network(cidr, strict=False)))
    except Exception:
        pass

    if not found:
        # Fall back to whichever address this host uses to reach the outside,
        # assuming a /24. Crude, and better than scanning nothing.
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(('8.8.8.8', 80))
            ip = sock.getsockname()[0]
            sock.close()
            found.append(str(ipaddress.ip_network(ip + '/24', strict=False)))
        except Exception:
            pass
    return found


def ping(host, timeout_ms=300):
    flag = '-n' if platform.system() == 'Windows' else '-c'
    wait = ['-w', str(timeout_ms)] if platform.system() == 'Windows' else \
           ['-W', str(max(1, timeout_ms // 1000))]
    try:
        return subprocess.run(
            ['ping', flag, '1', *wait, host],
            capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def arp_table():
    table = {}
    try:
        out = subprocess.run(['ip', 'neigh'], capture_output=True,
                             text=True, timeout=10).stdout
        for line in out.splitlines():
            match = re.match(r'(\d+\.\d+\.\d+\.\d+).*lladdr ([0-9a-fA-F:]{17})', line)
            if match:
                table[match.group(1)] = match.group(2)
    except Exception:
        try:
            out = subprocess.run(['arp', '-a'], capture_output=True,
                                 text=True, timeout=10).stdout
            for line in out.splitlines():
                match = re.search(
                    r'(\d+\.\d+\.\d+\.\d+).*?([0-9a-fA-F]{2}[:-]'
                    r'(?:[0-9a-fA-F]{2}[:-]){4}[0-9a-fA-F]{2})', line)
                if match:
                    table[match.group(1)] = match.group(2)
        except Exception:
            pass
    return table


def sweep(subnets, max_hosts=1024, timeout_ms=300):
    alive = []
    for cidr in subnets:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        for count, host in enumerate(network.hosts()):
            if count >= max_hosts:
                break
            if ping(str(host), timeout_ms):
                alive.append(str(host))

    arp = arp_table()
    for ip in arp:
        if ip not in alive:
            alive.append(ip)

    return [{
        'ip': ip,
        'mac': arp.get(ip, ''),
        'hostname': '',
        'method': 'icmp+arp',
    } for ip in alive]


def emit_neighbours():
    """LLDP/CDP neighbours — the SNMP extension point.

    Return a list shaped like:

        [{'local_mac': 'AA-BB-CC-DD-EE-01', 'local_port': 'Gi0/1',
          'remote_name': 'ap-01', 'remote_port': 'eth0',
          'remote_mac': 'AA-BB-CC-DD-EE-02', 'source': 'lldp'}]

    and the server will build topology from it. Left unimplemented on purpose:
    it needs pysnmp and switch hardware to validate against, and an untested
    walk that silently returns nothing would look like a working feature that
    finds no neighbours.
    """
    return []


def emit_switch_ports():
    """Bridge-table entries — the other SNMP extension point.

        [{'switch_mac': 'AA-BB-CC-DD-EE-01', 'port': 'Gi0/5',
          'vlan': 10, 'mac': 'AA-BB-CC-DD-EE-42', 'ip': '10.0.0.42'}]
    """
    return []


def run_once(args):
    config = fetch_config(args.server, args.key)
    subnets = config.get('subnets') or local_subnets()
    print(f'Scanning: {", ".join(subnets) or "(nothing configured)"}')

    payload = {
        'collector_version': COLLECTOR_VERSION,
        'dry_run': bool(args.dry_run),
        'devices': sweep(subnets, args.max_hosts, args.timeout_ms),
        'neighbours': emit_neighbours(),
        'switch_ports': emit_switch_ports(),
    }
    result = post_results(args.server, args.key, payload)
    print(f'{result.get("devices", 0)} device(s): '
          f'{result.get("created", 0)} created, '
          f'{result.get("updated", 0)} updated, '
          f'{result.get("errors", 0)} error(s)'
          + (' [dry run]' if result.get('dry_run') else ''))
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--once', action='store_true',
                        help='Scan once and exit, rather than looping.')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-hosts', type=int, default=1024)
    parser.add_argument('--timeout-ms', type=int, default=300)
    args = parser.parse_args()

    print('Client St0r site collector — scan only networks you are '
          'authorised to scan.')

    if args.once:
        run_once(args)
        return

    while True:
        try:
            config = run_once(args)
            interval = max(60, int(config.get('scan_interval_minutes', 1440)) * 60)
        except urllib.error.HTTPError as exc:
            print(f'Server rejected us ({exc.code}). '
                  'The key may have been rotated or revoked.', file=sys.stderr)
            interval = 900
        except Exception as exc:  # noqa: BLE001 — a collector must not die
            print(f'Scan failed: {exc}', file=sys.stderr)
            interval = 900
        # A "scan now" request is picked up on the next config fetch, so the
        # wait between scans is also how quickly an on-demand scan lands.
        time.sleep(min(interval, 3600))


if __name__ == '__main__':
    main()
