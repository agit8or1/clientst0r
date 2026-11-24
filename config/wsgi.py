"""
WSGI config for Clientst0r
"""
import gc
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()


def _freeze_startup_objects():
    """Load the URLconf (and with it every view module) now, then move
    everything allocated so far out of the garbage collector's reach.

    The modules, classes and URL patterns live as long as the worker, but the
    collector's full passes walk all of them again: with ~200k such objects a
    full pass took ~150 ms in the middle of whichever request triggered it.
    gc.freeze() leaves them out of those passes; objects made by requests are
    collected as before."""
    try:
        from django.urls import get_resolver
        get_resolver().url_patterns  # noqa: B018 - imports the views
    except Exception:  # pragma: no cover - the first request reports it as before
        pass
    gc.collect()
    gc.freeze()


if os.environ.get('CLIENTST0R_GC_FREEZE', '1') != '0':
    _freeze_startup_objects()
