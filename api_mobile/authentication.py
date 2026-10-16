"""
DRF authentication for the mobile API: ``Authorization: Token <key>``.

Same header format as DRF's TokenAuthentication (what the shipped mobile
app sends), but the key is looked up by its HMAC in MobileAuthToken, and
revoked / expired tokens and inactive users are rejected.
"""
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from .models import MobileAuthToken


class MobileTokenAuthentication(BaseAuthentication):
    keyword = 'Token'

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed('Invalid token header.')
        try:
            raw = auth[1].decode()
        except UnicodeError:
            raise exceptions.AuthenticationFailed('Invalid token header.')

        row = MobileAuthToken.lookup(raw)
        # One message for every failure: the response must not tell a
        # prober whether a token exists, was revoked, or has expired.
        if row is None or not row.is_active or not row.user.is_active:
            raise exceptions.AuthenticationFailed('Invalid token.')
        try:
            row.touch()
        except Exception:
            pass
        return row.user, row

    def authenticate_header(self, request):
        return self.keyword
