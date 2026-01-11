"""
Password breach checking service using HaveIBeenPwned API.
Uses k-anonymity model to protect password privacy.
"""
import hashlib
import requests
from django.core.cache import cache
from django.conf import settings
import logging

logger = logging.getLogger('vault')


class PasswordBreachChecker:
    """Check passwords against HaveIBeenPwned using k-anonymity."""

    API_URL = 'https://api.pwnedpasswords.com/range/{}'
    CACHE_TTL = 86400  # 24 hours

    def check_password(self, password: str) -> tuple:
        """
        Check if password appears in breach database.

        Args:
            password: Plain text password to check

        Returns:
            tuple: (is_breached: bool, breach_count: int)
        """
        if not getattr(settings, 'HIBP_ENABLED', True):
            return False, 0

        # Generate SHA-1 hash
        sha1_hash = hashlib.sha1(password.encode('utf-8')).hexdigest().upper()
        hash_prefix = sha1_hash[:5]
        hash_suffix = sha1_hash[5:]

        # Check cache first
        cache_key = f'hibp_check_{hash_prefix}'
        cached_result = cache.get(cache_key)
        if cached_result:
            return self._check_suffix(hash_suffix, cached_result)

        # Call API
        try:
            headers = {}
            api_key = getattr(settings, 'HIBP_API_KEY', '')
            if api_key:
                headers['hibp-api-key'] = api_key

            response = requests.get(
                self.API_URL.format(hash_prefix),
                headers=headers,
                timeout=5
            )
            response.raise_for_status()

            # Cache response
            cache.set(cache_key, response.text, self.CACHE_TTL)

            return self._check_suffix(hash_suffix, response.text)

        except requests.RequestException as e:
            logger.error(f"HIBP API error: {e}")
            return False, 0  # Fail open - don't block on API errors

    def _check_suffix(self, suffix: str, response_text: str) -> tuple:
        """
        Parse API response and check for suffix match.

        Args:
            suffix: SHA-1 hash suffix (35 characters)
            response_text: API response with hash suffixes and counts

        Returns:
            tuple: (is_breached: bool, breach_count: int)
        """
        for line in response_text.split('\n'):
            if ':' not in line:
                continue
            hash_part, count = line.split(':')
            if hash_part.strip() == suffix:
                return True, int(count.strip())
        return False, 0
