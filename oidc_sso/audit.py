"""Audit entries for single sign-on. Never records tokens, codes or secrets.

Actions (audit.AuditLog.action): sso_login, sso_login_denied, sso_link,
sso_unlink, sso_step_up, sso_backchannel_logout, sso_config_change.
"""
import logging

logger = logging.getLogger('oidc_sso')

_FORBIDDEN = ('token', 'secret', 'code', 'verifier', 'nonce', 'assertion', 'private', 'password')


def _clean(extra):
    out = {}
    for k, v in (extra or {}).items():
        if any(f in str(k).lower() for f in _FORBIDDEN):
            continue
        if isinstance(v, (list, tuple, set)):
            v = [str(i)[:200] for i in list(v)[:50]]
        elif not isinstance(v, (bool, int, float)) and v is not None:
            v = str(v)[:300]
        out[k] = v
    return out


def log(event, *, request=None, user=None, provider=None, success=True, description='', **extra):
    try:
        from audit.models import AuditLog
        ip = ua = path = ''
        if request is not None:
            try:
                from core.client_ip import get_client_ip
                ip = get_client_ip(request)
            except Exception:
                ip = request.META.get('REMOTE_ADDR')
            ua = request.META.get('HTTP_USER_AGENT', '')[:255]
            path = request.path[:500]
        data = _clean(extra)
        data['event'] = event
        if provider is not None:
            data.update({'provider': provider.slug, 'provider_id': provider.pk})
        AuditLog.objects.create(
            user=user, username=getattr(user, 'username', '') or '', action=event,
            object_type='oidc_provider' if provider is not None else '',
            object_id=provider.pk if provider is not None else None,
            object_repr=str(provider or '')[:255], description=description[:1000],
            ip_address=ip or None, user_agent=ua, path=path, extra_data=data, success=success)
    except Exception:
        logger.exception('SSO audit write failed for %s', event)
