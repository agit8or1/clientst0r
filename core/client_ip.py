"""Resolve client addresses without trusting attacker-supplied XFF prefixes.

Only a peer listed in TRUSTED_PROXY_CIDRS may supply X-Forwarded-For. The
chain is walked from the nearest hop backwards and the first untrusted
address is the client, so a forged prefix sent by the client is ignored.

A request that arrives over gunicorn's unix socket has an empty REMOTE_ADDR.
Only a process on this host can connect to that socket (in practice the
local nginx), so such a peer is treated as a trusted local proxy.
"""
import ipaddress
import time

from django.conf import settings

_LOCAL_PEER = '127.0.0.1'  # what a unix-socket peer with no forwarding chain resolves to

# Proxies added in Settings → Security → API Access Control → Client address
# (api_access.TrustedProxy) are read at most every _MANAGED_TTL seconds per
# worker; the worker that saves a change resets at once.
_MANAGED_TTL = 10.0
_managed = {'at': 0.0, 'networks': ()}


def _parse(values):
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(str(value).strip(), strict=False))
        except ValueError:
            continue
    return networks


def configured_networks():
    """TRUSTED_PROXY_CIDRS from .env (or the default)."""
    return _parse(getattr(settings, 'TRUSTED_PROXY_CIDRS', ['127.0.0.1/32', '::1/128']))


def managed_networks():
    """Active proxies saved in Settings. If they cannot be read, none are used:
    trusting fewer proxies never lets a client choose its own address."""
    now = time.monotonic()
    if now - _managed['at'] < _MANAGED_TTL:
        return list(_managed['networks'])
    try:
        from api_access.models import TrustedProxy
        values = list(TrustedProxy.objects.filter(is_active=True).values_list('network', flat=True))
    except Exception:  # table missing before migrate, database unavailable
        values = []
    networks = tuple(_parse(values))
    _managed.update(at=now, networks=networks)
    return list(networks)


def reset_managed_cache():
    _managed.update(at=0.0, networks=())


def _trusted_networks():
    return configured_networks() + managed_networks()


def _is_trusted(address, networks):
    return any(address in network for network in networks)


def is_trusted_peer(request, networks=None) -> bool:
    """True if the connecting peer is a proxy allowed to supply forwarding headers."""
    peer = request.META.get('REMOTE_ADDR', '')
    if not peer:
        return True  # unix socket: a local process
    try:
        return _is_trusted(ipaddress.ip_address(peer), _trusted_networks() if networks is None else networks)
    except ValueError:
        return False


def get_client_ip(request, networks=None):
    """The client address, or None when forwarding data is malformed.
    ``networks`` overrides the trusted proxies (used to preview a change)."""
    peer = request.META.get('REMOTE_ADDR', '')
    if networks is None:
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


def ratelimit_ip(request):
    """django-ratelimit's ``key='ip'`` (settings.RATELIMIT_IP_META_KEY).

    The real client behind a trusted proxy, not the proxy's own address, so
    rate limits are per visitor instead of one bucket shared by everyone.
    Malformed forwarding data falls back to the peer address."""
    return get_client_ip(request) or request.META.get('REMOTE_ADDR') or '0.0.0.0'
