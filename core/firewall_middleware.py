"""
Firewall middleware for IP and GeoIP-based access control.
"""
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin
import ipaddress
import requests
import logging

logger = logging.getLogger(__name__)


class FirewallMiddleware(MiddlewareMixin):
    """
    Middleware to enforce IP and GeoIP firewall rules.
    """

    def process_request(self, request):
        """Check firewall rules before processing request."""
        from core.models import FirewallSettings, FirewallIPRule, FirewallCountryRule, FirewallLog

        # Get firewall settings
        settings = FirewallSettings.get_settings()

        # Skip if both firewalls are disabled
        if not settings.ip_firewall_enabled and not settings.geoip_firewall_enabled:
            return None

        # Get client IP
        client_ip = self.get_client_ip(request)
        if not client_ip:
            return HttpResponseForbidden('Unable to verify client address')

        # LAN access is never blocked, as long as the private address really is
        # the client. With forwarding headers from an untrusted peer, the
        # address resolved is that peer's own (e.g. an unlisted proxy
        # container), so it must not unlock the exemption for everyone behind it.
        try:
            from core.client_ip import is_trusted_peer
            ip_obj = ipaddress.ip_address(client_ip)
            forwarded = request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('HTTP_X_REAL_IP')
            if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local) and (
                    not forwarded or is_trusted_peer(request)):
                return None
        except ValueError:
            pass

        # Check bypass conditions
        if self.should_bypass(request, settings):
            return None

        # Check IP firewall
        if settings.ip_firewall_enabled:
            ip_blocked, ip_reason = self.check_ip_firewall(client_ip, settings)
            if ip_blocked:
                return self.block_request(request, client_ip, '', '', ip_reason, settings)

        # Check GeoIP firewall
        if settings.geoip_firewall_enabled:
            country_blocked, country_reason, country_code, country_name = self.check_geoip_firewall(
                client_ip, settings
            )
            if country_blocked:
                return self.block_request(
                    request, client_ip, country_code, country_name, country_reason, settings
                )

        return None

    def get_client_ip(self, request):
        from core.client_ip import get_client_ip
        return get_client_ip(request)

    def should_bypass(self, request, settings):
        """Check if request should bypass firewall."""
        # Bypass for staff users if enabled
        if settings.bypass_for_staff and request.user.is_authenticated and request.user.is_staff:
            return True

        # Bypass for API requests if enabled
        if settings.bypass_for_api and request.path.startswith('/api/'):
            return True

        # Always allow all authentication paths (login, SSO/OAuth callbacks, 2FA, etc.)
        # The firewall must not block users mid-flow during login/SSO redirect chains
        AUTH_PREFIXES = (
            '/accounts/login/',
            '/accounts/logout/',
            '/accounts/auth/',   # SSO: Azure/OAuth login + callback
            '/auth/login/',
            '/auth/logout/',
            '/two_factor/',
        )
        if request.path.startswith(AUTH_PREFIXES):
            return True

        return False

    def check_ip_firewall(self, client_ip, settings):
        """
        Check if IP should be blocked based on IP firewall rules.

        Returns:
            tuple: (blocked: bool, reason: str)
        """
        from core.models import FirewallIPRule

        # Get active rules
        rules = FirewallIPRule.objects.filter(is_active=True)

        # Check if IP matches any rule
        matches_rule = False
        for rule in rules:
            if rule.matches_ip(client_ip):
                matches_rule = True
                break

        if settings.ip_firewall_mode == 'blocklist':
            # Block if IP is in blocklist
            if matches_rule:
                return True, 'ip_blocklist'
        else:  # allowlist
            # Block if IP is NOT in allowlist
            if not matches_rule:
                return True, 'ip_not_in_allowlist'

        return False, ''

    def check_geoip_firewall(self, client_ip, settings):
        """
        Check if country should be blocked based on GeoIP firewall rules.

        Returns:
            tuple: (blocked: bool, reason: str, country_code: str, country_name: str)
        """
        from core.models import FirewallCountryRule

        # Lookup country for IP
        country_code, country_name = self.geoip_lookup(client_ip)

        if not country_code:
            # GeoIP lookup failed - block or allow based on configuration
            # For security, we'll block if in allowlist mode
            if settings.geoip_firewall_mode == 'allowlist':
                return True, 'geoip_lookup_failed', '', ''
            else:
                # Allow if in blocklist mode (can't verify country)
                return False, '', '', ''

        # Get active rules
        rules = FirewallCountryRule.objects.filter(is_active=True)
        country_codes = set(rule.country_code.upper() for rule in rules)

        # Check if country matches any rule
        matches_rule = country_code.upper() in country_codes

        if settings.geoip_firewall_mode == 'blocklist':
            # Block if country is in blocklist
            if matches_rule:
                return True, 'country_blocklist', country_code, country_name
        else:  # allowlist
            # Block if country is NOT in allowlist
            if not matches_rule:
                return True, 'country_not_in_allowlist', country_code, country_name

        return False, '', country_code, country_name

    def geoip_lookup(self, ip_address):
        """
        Lookup country for IP address using free GeoIP service.

        Returns:
            tuple: (country_code: str, country_name: str)
        """
        try:
            # Use ip-api.com (free, no API key required, 45 requests/minute)
            response = requests.get(
                f'http://ip-api.com/json/{ip_address}',
                params={'fields': 'status,countryCode,country'},
                timeout=3
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return data.get('countryCode', ''), data.get('country', '')

        except Exception as e:
            logger.warning(f"GeoIP lookup failed for {ip_address}: {e}")

        return '', ''

    def block_request(self, request, ip_address, country_code, country_name, reason, settings):
        """Block the request and log it."""
        from core.models import FirewallLog

        # Log the blocked request if enabled
        if settings.log_blocked_requests:
            FirewallLog.objects.create(
                ip_address=ip_address,
                country_code=country_code,
                country_name=country_name,
                block_reason=reason,
                request_path=request.path,
                request_method=request.method,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                user=request.user if request.user.is_authenticated else None
            )

        # Return 403 Forbidden response
        context = {
            'ip_address': ip_address,
            'country': country_name if country_name else 'Unknown',
            'reason': reason,
        }

        return render(request, 'firewall_blocked.html', context, status=403)
