"""This installation's Connect identity (= this MSP) and its public URLs."""
from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.urls import reverse

from agit8or_connect import discovery

from . import catalog


def get():
    from .models import InstallationIdentity
    ident = InstallationIdentity.objects.order_by('pk').first()
    if ident is None:
        name = ''
        try:
            from core.models import SystemSetting
            s = SystemSetting.get_settings()
            name = getattr(s, 'custom_company_name', '') or getattr(s, 'site_name', '') or ''
        except Exception:
            name = ''
        ident = InstallationIdentity.objects.create(display_name=(name or 'Clientst0r')[:200])
    return ident


def installation_id() -> str:
    return str(get().installation_id)


def app_info() -> dict:
    from config.version import VERSION
    ident = get()
    return {'type': catalog.APP_TYPE, 'version': VERSION, 'display_name': ident.display_name,
            'installation_id': str(ident.installation_id)}


def enabled() -> bool:
    return bool(getattr(settings, 'AGIT8OR_CONNECT_ENABLED', False))


def kill_switch_engaged() -> bool:
    from .models import InstallationIdentity
    return InstallationIdentity.objects.filter(kill_switch_engaged=True).exists()


def public_base(request=None) -> str:
    """The https base other apps reach us at. AGIT8OR_CONNECT_PUBLIC_URL when
    set (required behind a proxy that rewrites the scheme or host)."""
    base = getattr(settings, 'AGIT8OR_CONNECT_PUBLIC_URL', '')
    if base:
        return base.rstrip('/')
    if request is not None:
        return f'{request.scheme}://{request.get_host()}'
    return ''


def url(name: str, request=None, **kwargs) -> str:
    return public_base(request) + reverse(f'connect_api:{name}', kwargs=kwargs or None)


def token_endpoint(request=None) -> str:
    return url('token', request)


def endpoints(request=None) -> dict:
    base = public_base(request)
    return {
        'pairing': url('pairing_submit', request),
        'pairing_status': base + reverse('connect_api:pairing_status', kwargs={'request_id': 'REQ'}).replace(
            'REQ', '{request_id}'),
        'token': token_endpoint(request),
        'jwks': base + reverse('connect_api:jwks', kwargs={'connection_id': '00000000-0000-0000-0000-000000000000'})
        .replace('00000000-0000-0000-0000-000000000000', '{connection_id}'),
        'health': url('health', request),
        'capabilities': url('capabilities', request),
        'events': url('events', request),
        'test': url('test', request),
        'api_base': base + '/connect/v1',
    }


def document(request=None) -> dict:
    return discovery.build_document(app=app_info(), endpoints=endpoints(request), catalog=catalog.CATALOG,
                                    events=list(catalog.OUTBOUND_EVENT_TYPES), tenant_model=catalog.TENANT_MODEL,
                                    extra={'msp': {'single_msp_installation': True}})


def pairing_pepper() -> bytes:
    secret = (getattr(settings, 'API_KEY_SECRET', '') or settings.SECRET_KEY).encode('utf-8')
    return hmac.new(secret, b'agit8or-connect pairing-code pepper v1', hashlib.sha256).digest()
