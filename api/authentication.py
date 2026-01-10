"""
API authentication - API key authentication for DRF
"""
from rest_framework import authentication, exceptions
from django.utils import timezone
from .models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    API key authentication for DRF.
    Expects header: Authorization: Bearer itdocs_live_<key>
    """
    keyword = 'Bearer'

    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header:
            return None

        parts = auth_header.split()

        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            return None

        plaintext_key = parts[1]

        # Verify key
        api_key = APIKey.verify_key(plaintext_key)

        if not api_key:
            raise exceptions.AuthenticationFailed('Invalid API key')

        # Update last used
        api_key.last_used_at = timezone.now()
        api_key.last_used_ip = self.get_client_ip(request)
        api_key.save(update_fields=['last_used_at', 'last_used_ip'])

        # Return user and set organization context
        request.current_organization = api_key.organization
        request.api_key = api_key

        return (api_key.user, None)

    def authenticate_header(self, request):
        return self.keyword

    def get_client_ip(self, request):
        """Get client IP address."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
