"""Resolve client addresses without trusting attacker-supplied XFF prefixes."""
import ipaddress
from django.conf import settings


def get_client_ip(request):
    peer = request.META.get('REMOTE_ADDR', '')
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return None
    networks = []
    for value in getattr(settings, 'TRUSTED_PROXY_CIDRS', ['127.0.0.1/32', '::1/128']):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    def trusted(address):
        return any(address in network for network in networks)
    if not trusted(peer_ip):
        return str(peer_ip)
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not forwarded:
        # X-Real-IP is not a chain and cannot establish which peer supplied it.
        return str(peer_ip)
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in forwarded.split(',')]
    except ValueError:
        return None  # Malformed forwarding data must not become a LAN bypass.
    for address in reversed(chain):
        if not trusted(address):
            return str(address)
    return str(chain[0]) if chain else str(peer_ip)
