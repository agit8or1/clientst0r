"""
Browser-extension bearer-token authentication (Phase 28 — v3.17.327).

Browser extensions exchange the user's password for a `WebExtensionAuthToken`
once (via the Settings UI) and then carry the opaque token on every API call
in the `Authorization: Bearer <token>` header. They never carry a Django
session cookie because they live in a different origin from the app.

The `extension_auth_required` decorator resolves the bearer token, validates
expiry / revocation, attaches the token's user to the request, bumps
`last_used_at`, and resolves the request's organization context from the
`X-Organization-Id` header (falling back to the token's pinned org).
"""
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone

from .models import WebExtensionAuthToken


def _extract_bearer_token(request):
    """Return the bearer token string or None."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != 'bearer':
        return None
    return token.strip() or None


def resolve_extension_token(request):
    """
    Look up the bearer token, return the (token_row, error_response) pair.
    On success: (row, None). On failure: (None, JsonResponse 401).
    """
    raw = _extract_bearer_token(request)
    if not raw:
        return None, JsonResponse(
            {'error': 'Missing bearer token in Authorization header.'},
            status=401,
        )
    # Stored hashed: look up by HMAC of the presented token.
    row = WebExtensionAuthToken.lookup(raw)
    if row is None:
        return None, JsonResponse({'error': 'Invalid token.'}, status=401)
    if row.revoked_at is not None:
        return None, JsonResponse({'error': 'Token has been revoked.'}, status=401)
    if row.expires_at and row.expires_at <= timezone.now():
        return None, JsonResponse({'error': 'Token has expired.'}, status=401)
    if not row.user.is_active:
        return None, JsonResponse({'error': 'Invalid token.'}, status=401)
    return row, None


def _resolve_organization_from_request(request, token_row):
    """
    Determine the organization for this extension call.

    Precedence:
      1. The token's pinned `organization` — a pinned token never acts for
         another customer, whatever the header says.
      2. `X-Organization-Id` header (extension explicitly chose an org).
      3. None (caller is in global view).

    Returns the Organization or None.
    """
    from core.models import Organization

    if token_row.organization_id:
        return token_row.organization
    header_val = request.META.get('HTTP_X_ORGANIZATION_ID')
    if header_val:
        try:
            org_id = int(header_val)
        except (TypeError, ValueError):
            return None
        try:
            return Organization.objects.get(id=org_id, is_active=True)
        except Organization.DoesNotExist:
            return None
    return token_row.organization


def extension_auth_required(view_func):
    """
    Decorator: validate bearer token, attach user + org to request, dispatch.

    On success:
      * `request.user`            — the token's user
      * `request.extension_token` — the WebExtensionAuthToken row
      * `request.current_organization` — resolved per the rules above

    Bumps `last_used_at` on every successful call.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        token_row, err = resolve_extension_token(request)
        if err is not None:
            return err

        request.user = token_row.user
        request.extension_token = token_row
        request.current_organization = _resolve_organization_from_request(
            request, token_row,
        )
        # Bump last_used_at — non-fatal on errors (e.g. read-only DB during
        # a maintenance window shouldn't block the call).
        try:
            token_row.touch()
        except Exception:
            pass
        return view_func(request, *args, **kwargs)

    return _wrapped
