"""The request being served on this thread, so model signals can name who
made a change (role-change audit). Set by ReadTrackingMiddleware; empty in
management commands, the shell and the scheduler, where the audit entry
says the actor is unknown."""
import threading

_local = threading.local()


def set_request(request):
    _local.request = request


def clear():
    _local.request = None


def current():
    """(user or None, ip or None, path)."""
    request = getattr(_local, 'request', None)
    if request is None:
        return None, None, ''
    user = getattr(request, 'user', None)
    if user is not None and not getattr(user, 'is_authenticated', False):
        user = None
    try:
        from core.client_ip import get_client_ip
        ip = get_client_ip(request)
    except Exception:  # noqa: BLE001
        ip = None
    return user, ip, (getattr(request, 'path', '') or '')[:500]
