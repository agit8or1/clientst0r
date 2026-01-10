"""
Custom CSRF middleware to support wildcard domains in DEBUG mode.
"""
from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.cache import patch_vary_headers


class MultiDomainCsrfViewMiddleware(CsrfViewMiddleware):
    """
    Custom CSRF middleware that allows any origin when:
    - DEBUG mode is enabled
    - ALLOWED_HOSTS contains wildcard '*'

    This enables multi-domain support for development/testing while
    maintaining full CSRF protection in production.
    """

    def _origin_verified(self, request):
        """
        Override origin verification to allow any origin in DEBUG mode with wildcard hosts.
        """
        # In DEBUG mode with wildcard ALLOWED_HOSTS, allow any HTTPS origin
        if settings.DEBUG and '*' in settings.ALLOWED_HOSTS:
            request_origin = request.META.get('HTTP_ORIGIN')
            if request_origin:
                # Allow any HTTPS or HTTP origin in DEBUG mode
                # This is safe because DEBUG should never be True in production
                return True

        # Otherwise, use Django's standard origin verification
        return super()._origin_verified(request)
