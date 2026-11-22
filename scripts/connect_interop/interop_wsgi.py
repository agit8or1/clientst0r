"""WSGI entry point of one harness installation: the Django app behind the
harness's inbound address translation (netshim.translate_remote_addr)."""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'interop_settings')

from django.core.wsgi import get_wsgi_application  # noqa: E402

import netshim  # noqa: E402

_app = get_wsgi_application()


def application(environ, start_response):
    remote = environ.get('REMOTE_ADDR', '')
    mapped = netshim.translate_remote_addr(remote)
    if mapped != remote:
        environ['REMOTE_ADDR'] = mapped
    return _app(environ, start_response)
