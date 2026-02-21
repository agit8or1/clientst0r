#!/usr/bin/env python3
"""
Network Scanner for Client St0r
Scans network ranges and generates importable asset data.

Usage:
    python3 network_scanner.py 192.168.1.0/24
    python3 network_scanner.py 192.168.1.1-192.168.1.254
    python3 network_scanner.py --input targets.txt --output scan_results.json

Requirements:
    pip install python-nmap netifaces
    sudo apt-get install nmap (on Linux)
"""

import json
import argparse
import sys
import subprocess
import re
from datetime import datetime
from pathlib import Path

try:
    import nmap
except ImportError:
    print("ERROR: python-nmap not installed")
    print("Install with: pip install python-nmap")
    sys.exit(1)


class NetworkScanner:
    """Network scanner using nmap to discover devices."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.nm = nmap.PortScanner()
        self.results = []

    def log(self, message):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(f"[*] {message}")

    def scan_network(self, targets, ports="1-1000", scan_type="-sS"):
        """
        Scan network targets.

        Args:
            targets: IP range (CIDR, range, or single IP)
            ports: Port range to scan (default: 1-1000)
            scan_type: Nmap scan type (default: -sS for SYN scan)

        Returns:
            List of discovered devices
        """
        self.log(f"Starting scan of {targets}")
        self.log(f"Port range: {ports}")
        self.log(f"Scan type: {scan_type}")

        try:
            # Run nmap scan
            # -sS: SYN scan
            # -O: OS detection
            # -sV: Version detection
            # --osscan-guess: Aggressive OS guessing
            # -T4: Aggressive timing
            arguments = f"{scan_type} -O -sV --osscan-guess -T4"

            self.log(f"Executing: nmap {arguments} -p {ports} {targets}")
            self.nm.scan(hosts=targets, ports=ports, arguments=arguments)

            # Parse results
            for host in self.nm.all_hosts():
                device_info = self.parse_host(host)
                if device_info:
                    self.results.append(device_info)
                    self.log(f"Found device: {device_info['ip']} ({device_info['hostname']})")

            self.log(f"Scan complete. Found {len(self.results)} devices.")
            return self.results

        except nmap.PortScannerError as e:
            print(f"ERROR: Nmap scan failed: {e}")
            print("Make sure nmap is installed: sudo apt-get install nmap")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: Scan failed: {e}")
            sys.exit(1)

    def parse_host(self, host):
        """Parse nmap host data into device info."""
        if host not in self.nm.all_hosts():
            return None

        host_data = self.nm[host]

        # Skip hosts that are down
        if host_data.state() == 'down':
            return None

        device = {
            'ip': host,
            'hostname': host_data.hostname() if host_data.hostname() else '',
            'mac_address': '',
            'vendor': '',
            'os': '',
            'device_type': 'other',
            'ports': [],
            'status': 'up',
            'last_seen': datetime.now().isoformat(),
        }

        # MAC address and vendor
        if 'mac' in host_data['addresses']:
            device['mac_address'] = host_data['addresses']['mac']
            if 'vendor' in host_data and host_data['vendor']:
                device['vendor'] = list(host_data['vendor'].values())[0]

        # OS detection
        if 'osmatch' in host_data and host_data['osmatch']:
            os_match = host_data['osmatch'][0]
            device['os'] = os_match['name']
            device['os_accuracy'] = os_match['accuracy']

        # Port information
        for proto in host_data.all_protocols():
            ports = host_data[proto].keys()
            for port in ports:
                port_info = host_data[proto][port]
                if port_info['state'] == 'open':
                    device['ports'].append({
                        'port': port,
                        'protocol': proto,
                        'state': port_info['state'],
                        'service': port_info.get('name', ''),
                        'product': port_info.get('product', ''),
                        'version': port_info.get('version', ''),
                    })

        # Guess device type based on open ports and OS
        device['device_type'] = self.guess_device_type(device)

        return device

    def guess_device_type(self, device):
        """Guess device type based on open ports and OS info."""
        open_ports = [p['port'] for p in device['ports']]
        os_lower = device['os'].lower()

        # Server indicators
        if any(p in open_ports for p in [22, 3389, 5900]):  # SSH, RDP, VNC
            if 'windows' in os_lower:
                return 'server'  # Windows Server
            elif any(keyword in os_lower for keyword in ['linux', 'unix', 'ubuntu', 'debian', 'centos', 'redhat']):
                return 'server'  # Linux Server

        # Network equipment
        if any(p in open_ports for p in [23, 161, 179, 830]):  # Telnet, SNMP, BGP, NETCONF
            if any(keyword in os_lower for keyword in ['cisco', 'juniper', 'arista']):
                return 'router'
            return 'switch'

        # Web servers
        if any(p in open_ports for p in [80, 443, 8080, 8443]):
            if any(keyword in os_lower for keyword in ['appliance', 'firewall']):
                return 'firewall'
            if any(p in open_ports for p in [22, 3389]):
                return 'server'

        # Printers
        if any(p in open_ports for p in [515, 631, 9100]):  # LPD, IPP, JetDirect
            return 'printer'

        # IP Phones
        if any(p in open_ports for p in [5060, 5061]):  # SIP
            return 'phone'

        # Security cameras
        if any(p in open_ports for p in [554, 8000, 8001]):  # RTSP, camera admin
            return 'security_camera'

        # Wireless APs
        if 'access point' in os_lower or 'wireless' in os_lower:
            return 'wireless_ap'

        # Default to workstation/desktop
        if 'windows' in os_lower and '3389' in str(open_ports):
            return 'desktop'

        return 'other'

    def save_results(self, output_file):
        """Save scan results to JSON file."""
        output_path = Path(output_file)

        scan_data = {
            'scan_date': datetime.now().isoformat(),
            'scanner_version': '1.0',
            'device_count': len(self.results),
            'devices': self.results
        }

        with open(output_path, 'w') as f:
            json.dump(scan_data, f, indent=2)

        self.log(f"Results saved to {output_path}")
        print(f"\n✓ Scan results saved to: {output_path}")
        print(f"  Devices found: {len(self.results)}")
        print(f"\nTo import into Client St0r:")
        print(f"  1. Log into Client St0r")
        print(f"  2. Go to Assets → Import Network Scan")
        print(f"  3. Upload: {output_path.absolute()}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Network Scanner for Client St0r',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Scan single subnet:
    python3 network_scanner.py 192.168.1.0/24

  Scan IP range:
    python3 network_scanner.py 192.168.1.1-192.168.1.254

  Scan multiple targets from file:
    python3 network_scanner.py --input targets.txt

  Custom port range:
    python3 network_scanner.py 192.168.1.0/24 --ports 1-65535

  Quick scan (top 100 ports):
    python3 network_scanner.py 192.168.1.0/24 --quick

  Custom output file:
    python3 network_scanner.py 192.168.1.0/24 --output my_scan.json
        """
    )

    parser.add_argument(
        'targets',
        nargs='?',
        help='Network targets (CIDR, range, or single IP)'
    )

    parser.add_argument(
        '-i', '--input',
        help='Read targets from file (one per line)'
    )

    parser.add_argument(
        '-o', '--output',
        default='network_scan.json',
        help='Output JSON file (default: network_scan.json)'
    )

    parser.add_argument(
        '-p', '--ports',
        default='1-1000',
        help='Port range to scan (default: 1-1000)'
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick scan (top 100 ports only)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    return parser.parse_args()


def check_nmap_installed():
    """Check if nmap is installed."""
    try:
        result = subprocess.run(['nmap', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def main():
    """Main entry point."""
    args = parse_arguments()

    # Validate arguments
    if not args.targets and not args.input:
        print("ERROR: Must specify targets or --input file")
        sys.exit(1)

    # Check nmap installation
    if not check_nmap_installed():
        print("ERROR: nmap is not installed")
        print("\nInstall nmap:")
        print("  Ubuntu/Debian: sudo apt-get install nmap")
        print("  CentOS/RHEL:   sudo yum install nmap")
        print("  macOS:         brew install nmap")
        sys.exit(1)

    # Determine targets
    if args.input:
        with open(args.input) as f:
            targets = ' '.join([line.strip() for line in f if line.strip()])
    else:
        targets = args.targets

    # Port configuration
    if args.quick:
        ports = '21,22,23,25,53,80,110,111,135,139,143,443,445,993,995,1723,3306,3389,5900,8080'
    else:
        ports = args.ports

    # Run scan
    print("=" * 70)
    print("Client St0r Network Scanner")
    print("=" * 70)
    print(f"Targets: {targets}")
    print(f"Ports:   {ports}")
    print(f"Output:  {args.output}")
    print("=" * 70)
    print()

    scanner = NetworkScanner(verbose=args.verbose)
    scanner.scan_network(targets, ports=ports)
    scanner.save_results(args.output)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Scan interrupted by user")
        sys.exit(1)
