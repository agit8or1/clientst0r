"""
Security Headers Middleware.
Adds additional security headers not covered by Django's built-in middleware.
- Permissions-Policy (formerly Feature-Policy)
- X-Content-Type-Options (redundant with Django but explicit)
- X-Frame-Options (redundant with Django but explicit)
"""
from django.conf import settings


class SecurityHeadersMiddleware:
    """
    Add additional security headers to all responses.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Permissions-Policy (formerly Feature-Policy)
        if hasattr(settings, 'PERMISSIONS_POLICY'):
            policy_parts = []
            for feature, allowlist in settings.PERMISSIONS_POLICY.items():
                if not allowlist:
                    # Empty list = disabled
                    policy_parts.append(f'{feature}=()')
                else:
                    # List of allowed origins
                    origins = ' '.join(f'"{origin}"' if origin != 'self' else origin for origin in allowlist)
                    policy_parts.append(f'{feature}=({origins})')

            if policy_parts:
                response['Permissions-Policy'] = ', '.join(policy_parts)

        # Additional explicit headers (defensive in depth)
        response['X-Content-Type-Options'] = 'nosniff'
        # DENY unless a view explicitly opted into same-origin framing with
        # @xframe_options_sameorigin (the in-app PDF preview); overwriting that
        # made the decorator a no-op. The CSP frame-ancestors follows suit.
        if response.get('X-Frame-Options', '').upper() != 'SAMEORIGIN':
            response['X-Frame-Options'] = 'DENY'

        # Referrer-Policy
        if hasattr(settings, 'SECURE_REFERRER_POLICY'):
            response['Referrer-Policy'] = settings.SECURE_REFERRER_POLICY

        return response
