"""Resolve client addresses without trusting attacker-supplied XFF prefixes.

Only a peer listed in TRUSTED_PROXY_CIDRS may supply X-Forwarded-For. The
chain is walked from the nearest hop backwards and the first untrusted
address is the client, so a forged prefix sent by the client is ignored.

A request that arrives over gunicorn's unix socket has an empty REMOTE_ADDR.
Only a process on this host can connect to that socket (in practice the
local nginx), so such a peer is treated as a trusted local proxy.
"""
import ipaddress

from django.conf import settings

_LOCAL_PEER = '127.0.0.1'  # what a unix-socket peer with no forwarding chain resolves to


def _trusted_networks():
    networks = []
    for value in getattr(settings, 'TRUSTED_PROXY_CIDRS', ['127.0.0.1/32', '::1/128']):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted(address, networks):
    return any(address in network for network in networks)


def is_trusted_peer(request) -> bool:
    """True if the connecting peer is a proxy allowed to supply forwarding headers."""
    peer = request.META.get('REMOTE_ADDR', '')
    if not peer:
        return True  # unix socket: a local process
    try:
        return _is_trusted(ipaddress.ip_address(peer), _trusted_networks())
    except ValueError:
        return False


def get_client_ip(request):
    peer = request.META.get('REMOTE_ADDR', '')
    networks = _trusted_networks()
    if peer:
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return None
        if not _is_trusted(peer_ip, networks):
            return str(peer_ip)
        fallback = str(peer_ip)
    else:
        fallback = _LOCAL_PEER
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not forwarded:
        # X-Real-IP is not a chain and cannot establish which peer supplied it.
        return fallback
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in forwarded.split(',')]
    except ValueError:
        return None  # Malformed forwarding data must not become a LAN bypass.
    for address in reversed(chain):
        if not _is_trusted(address, networks):
            return str(address)
    return str(chain[0]) if chain else fallback
