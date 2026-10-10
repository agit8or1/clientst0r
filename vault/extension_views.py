"""
Browser-extension API endpoints (Phase 28).

These views are the server-side surface for the WebExtension binary
(separate codebase, distributed via Chrome / Firefox / Edge stores). They
all use bearer-token auth except token-issue / token-list / token-revoke
which require the user's Django session (the extension can only get a
token by being signed in to the app first).
"""
import json
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from core.middleware import get_request_organization
from core.client_ip import get_client_ip
from .extension_auth import extension_auth_required
from .models import Password, WebExtensionAuthToken
from .permissions import RevealDenied, consume_approval, gate_reveal


# ---------------------------------------------------------------------------
# Token lifecycle — session-authed (the user issues / revokes from the app)
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(['POST'])
def token_issue(request):
    """
    Issue a new browser-extension auth token for the current user.

    POST body (JSON or form-encoded):
      * label (str, optional) — user-friendly label
      * organization_id (int, optional) — pin to a specific org
      * ttl_days (int, optional) — override default TTL (capped at 365)

    Returns the token string in the response body — the **only** time the
    server will ever surface the secret. If the user loses it, they revoke
    and reissue.
    """
    payload = _parse_body(request)
    label = (payload.get('label') or '')[:120]
    org_id = payload.get('organization_id') or None
    ttl_days = payload.get('ttl_days')
    try:
        ttl_days = int(ttl_days) if ttl_days else None
    except (TypeError, ValueError):
        ttl_days = None
    if ttl_days is not None:
        ttl_days = max(1, min(ttl_days, 365))

    organization = None
    if org_id:
        from core.models import Organization
        try:
            organization = Organization.objects.get(id=int(org_id), is_active=True)
        except (Organization.DoesNotExist, TypeError, ValueError):
            return JsonResponse({'error': 'Invalid organization_id.'}, status=400)
        if not _user_has_org_access(request.user, organization):
            return JsonResponse({'error': 'Forbidden.'}, status=403)

    token_str, row = WebExtensionAuthToken.issue(
        user=request.user,
        organization=organization,
        label=label,
        ttl_days=ttl_days,
    )

    AuditLog.log(
        user=request.user,
        action='create',
        organization=organization,
        object_type='vault.WebExtensionAuthToken',
        object_id=row.pk,
        object_repr=row.label or 'extension token',
        description='Issued browser-extension auth token',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
    )

    return JsonResponse({
        'id': row.pk,
        'token': token_str,
        'label': row.label,
        'organization_id': row.organization_id,
        'expires_at': row.expires_at.isoformat() if row.expires_at else None,
        'created_at': row.created_at.isoformat(),
    }, status=201)


@login_required
@require_http_methods(['GET'])
def token_list(request):
    """List the calling user's extension tokens (no secret material)."""
    rows = (WebExtensionAuthToken.objects
            .filter(user=request.user)
            .order_by('-created_at'))
    return JsonResponse({
        'tokens': [
            {
                'id': r.pk,
                'label': r.label,
                'organization_id': r.organization_id,
                'created_at': r.created_at.isoformat(),
                'last_used_at': r.last_used_at.isoformat() if r.last_used_at else None,
                'expires_at': r.expires_at.isoformat() if r.expires_at else None,
                'revoked_at': r.revoked_at.isoformat() if r.revoked_at else None,
                'is_active': r.is_active,
            }
            for r in rows
        ],
    })


@login_required
@require_http_methods(['DELETE', 'POST'])
def token_revoke(request, pk):
    """
    Revoke a token. Accepts DELETE (preferred) or POST (for form fallback).
    Only the token's owner — or a superuser — can revoke.
    """
    try:
        row = WebExtensionAuthToken.objects.get(pk=pk)
    except WebExtensionAuthToken.DoesNotExist:
        return JsonResponse({'error': 'Token not found.'}, status=404)
    if row.user_id != request.user.pk and not request.user.is_superuser:
        return JsonResponse({'error': 'Forbidden.'}, status=403)
    if row.revoked_at is None:
        row.revoke()
        AuditLog.log(
            user=request.user,
            action='delete',
            organization=row.organization,
            object_type='vault.WebExtensionAuthToken',
            object_id=row.pk,
            object_repr=row.label or 'extension token',
            description='Revoked browser-extension auth token',
            ip_address=get_client_ip(request),
        )
    return JsonResponse({'id': row.pk, 'revoked': True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_body(request):
    """Best-effort: JSON body, fall back to form POST."""
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body or b'{}')
        except (ValueError, json.JSONDecodeError):
            return {}
    return request.POST.dict() if request.method == 'POST' else {}


def _user_has_org_access(user, organization):
    """True if the user is a superuser or has an active membership in `organization`."""
    if user.is_superuser:
        return True
    if hasattr(user, 'profile') and getattr(user.profile, 'is_staff_user', lambda: False)():
        return True
    return user.memberships.filter(organization=organization, is_active=True).exists()


def _has_extension_permission(user, organization, attr_name):
    """
    Check whether `user` has the given extension permission within `organization`.

    Superusers and staff-flagged users always pass. Otherwise the user's
    Membership in `organization` must resolve to a RoleTemplate (or simple
    role fallback) where `attr_name` is True.

    Permission attrs are: 'vault_extension_use', 'vault_extension_offline_cache'.
    """
    if user.is_superuser:
        return True
    if hasattr(user, 'profile') and getattr(user.profile, 'is_staff_user', lambda: False)():
        return True
    if organization is None:
        return False
    membership = user.memberships.filter(
        organization=organization, is_active=True,
    ).select_related('role_template').first()
    if membership is None:
        return False
    perms = membership.get_permissions()
    return bool(getattr(perms, attr_name, False))


def _visible_password_qs(user, organization):
    """
    QuerySet of Password rows visible to `user` in `organization`. The
    extension never sees personal-vault entries; those are session-scoped
    only. When organization is None the caller is in global view.
    """
    if organization is None:
        if user.is_superuser:
            return Password.objects.filter(is_personal=False)
        # Staff users without a chosen org -> all orgs they can see
        if hasattr(user, 'profile') and getattr(user.profile, 'is_staff_user', lambda: False)():
            return Password.objects.filter(is_personal=False)
        # Org users without an org pinned -> nothing
        return Password.objects.none()
    return Password.objects.filter(
        organization=organization, is_personal=False,
    )


def _gate(request, password, event):
    """Run the shared reveal gate; return an error response if it refuses."""
    try:
        gate_reveal(request, password)
    except RevealDenied as denial:
        AuditLog.log(
            user=request.user,
            action='read',
            organization=password.organization,
            object_type='vault.Password',
            object_id=password.pk,
            object_repr=password.title,
            description=f'{event} blocked — {denial.detail}',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            extra_data={'event': event, 'blocked_reason': denial.detail},
            success=False,
        )
        body = {'error': denial.detail}
        if denial.requires_approval:
            body['requires_approval'] = True
        return JsonResponse(body, status=denial.status)
    return None


def _host_from_url(value):
    """Lower-cased host (sans port) from a URL string. None on failure."""
    if not value:
        return None
    try:
        parsed = urlparse(value if '://' in value else 'http://' + value)
    except Exception:
        return None
    host = (parsed.hostname or '').lower()
    return host or None


# ---------------------------------------------------------------------------
# Bearer-authed extension endpoints — Phase 28 v3.17.328
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(['GET'])
@extension_auth_required
def autofill(request):
    """
    Autofill match endpoint.

    GET /vault/api/extension/autofill?url=https://example.com/login

    Returns minimal payload — title, username, totp_available — and
    excludes encrypted blobs / secrets. Audit-logs every call as
    `vault_autofill` regardless of match count (so a tech who hits a
    page where no credential exists still leaves a trail).

    Gated by RoleTemplate.vault_extension_use.
    """
    organization = request.current_organization
    if not _has_extension_permission(request.user, organization, 'vault_extension_use'):
        return JsonResponse({'error': 'Extension use permission required.'}, status=403)

    url = request.GET.get('url', '').strip()
    if not url:
        return JsonResponse({'error': 'url parameter required.'}, status=400)
    target_host = _host_from_url(url)
    if not target_host:
        return JsonResponse({'error': 'Could not parse url.'}, status=400)

    qs = _visible_password_qs(request.user, organization)
    matches = []
    # Match by host suffix — exact host or any subdomain match.
    for pw in qs.exclude(url='')[:500]:
        pw_host = _host_from_url(pw.url)
        if not pw_host:
            continue
        if pw_host == target_host or target_host.endswith('.' + pw_host) \
                or pw_host.endswith('.' + target_host):
            matches.append({
                'id': pw.pk,
                'title': pw.title,
                'username': pw.username,
                'totp_available': bool(pw.otp_secret),
                'url': pw.url,
            })
        if len(matches) >= 50:
            break

    AuditLog.log(
        user=request.user,
        action='read',
        organization=organization,
        object_type='vault.Password',
        object_id=None,
        description=f'vault_autofill — host={target_host} matches={len(matches)}',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        extra_data={'event': 'vault_autofill', 'host': target_host,
                    'match_count': len(matches)},
    )

    return JsonResponse({
        'host': target_host,
        'matches': matches,
        'count': len(matches),
    })


@csrf_exempt
@require_http_methods(['GET'])
@extension_auth_required
def bulk_sync(request):
    """
    Bulk-sync the user's visible passwords as encrypted blobs for offline cache.

    GET /vault/api/extension/sync?cursor=<id>&limit=<n>

    Each row carries the **encrypted** ciphertext blob — the extension
    decrypts client-side using the master-derived key. Server never
    transmits plaintext on this endpoint.

    Gated by RoleTemplate.vault_extension_offline_cache.
    """
    organization = request.current_organization
    if not _has_extension_permission(request.user, organization,
                                      'vault_extension_offline_cache'):
        return JsonResponse(
            {'error': 'Offline cache permission required.'}, status=403,
        )

    try:
        limit = max(1, min(int(request.GET.get('limit', 100)), 500))
    except (TypeError, ValueError):
        limit = 100
    cursor = request.GET.get('cursor')
    qs = _visible_password_qs(request.user, organization).order_by('id')
    if cursor:
        try:
            qs = qs.filter(id__gt=int(cursor))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid cursor.'}, status=400)

    rows = list(qs[:limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].pk if rows and has_more else None

    AuditLog.log(
        user=request.user,
        action='read',
        organization=organization,
        object_type='vault.Password',
        object_id=None,
        description=f'vault_extension_sync — count={len(rows)}',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        extra_data={'event': 'vault_extension_sync', 'count': len(rows)},
    )

    return JsonResponse({
        'count': len(rows),
        'next_cursor': next_cursor,
        'has_more': has_more,
        'passwords': [
            {
                'id': pw.pk,
                'title': pw.title,
                'username': pw.username,
                'url': pw.url,
                'organization_id': pw.organization_id,
                'encrypted_password': pw.encrypted_password,
                'password_type': pw.password_type,
                'totp_available': bool(pw.otp_secret),
                'updated_at': pw.updated_at.isoformat() if pw.updated_at else None,
            }
            for pw in rows
        ],
    })


# ---------------------------------------------------------------------------
# v3.17.329 — TOTP, reveal, master-password verify
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(['GET'])
@extension_auth_required
def totp_code(request, pk):
    """
    Return the current TOTP code for the password's stored otp_secret.

    GET /vault/api/extension/<pk>/totp/

    Returns `{code, valid_until_unix, time_remaining}`. Audit-logs as
    `vault_extension_totp`. Gated by vault_extension_use.
    """
    organization = request.current_organization
    if not _has_extension_permission(request.user, organization, 'vault_extension_use'):
        return JsonResponse({'error': 'Extension use permission required.'}, status=403)

    qs = _visible_password_qs(request.user, organization)
    try:
        password = qs.get(pk=pk)
    except Password.DoesNotExist:
        return JsonResponse({'error': 'Password not found.'}, status=404)

    denied = _gate(request, password, 'vault_extension_totp')
    if denied is not None:
        return denied

    otp_data = password.generate_otp()
    if otp_data is None:
        return JsonResponse({'error': 'No TOTP secret configured.'}, status=400)
    if otp_data.get('error'):
        return JsonResponse({'error': otp_data.get('message', 'TOTP error.')}, status=400)

    import time as _time
    valid_until = int(_time.time()) + otp_data['time_remaining']

    AuditLog.log(
        user=request.user,
        action='read',
        organization=organization,
        object_type='vault.Password',
        object_id=password.pk,
        object_repr=password.title,
        description=f'vault_extension_totp — {password.title}',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        extra_data={'event': 'vault_extension_totp'},
    )

    return JsonResponse({
        'code': otp_data['code'],
        'time_remaining': otp_data['time_remaining'],
        'valid_until_unix': valid_until,
        'issuer': otp_data.get('issuer', ''),
    })


@csrf_exempt
@require_http_methods(['POST'])
@extension_auth_required
def reveal(request, pk):
    """
    Decrypt and return the password plaintext for the extension to autofill.

    POST /vault/api/extension/<pk>/reveal/

    Honours the `requires_reveal_approval` gate — if set, the caller
    must already have an approved VaultRevealRequest on file. Without
    one, returns 403 with `requires_approval: true`. Audit-logs as
    `vault_extension_reveal`. Gated by vault_extension_use.
    """
    organization = request.current_organization
    if not _has_extension_permission(request.user, organization, 'vault_extension_use'):
        return JsonResponse({'error': 'Extension use permission required.'}, status=403)

    qs = _visible_password_qs(request.user, organization)
    try:
        password = qs.get(pk=pk)
    except Password.DoesNotExist:
        return JsonResponse({'error': 'Password not found.'}, status=404)

    denied = _gate(request, password, 'vault_extension_reveal')
    if denied is not None:
        return denied

    try:
        plaintext = password.get_password()
    except Exception as e:
        AuditLog.log(
            user=request.user,
            action='read',
            organization=password.organization,
            object_type='vault.Password',
            object_id=password.pk,
            object_repr=password.title,
            description=f'vault_extension_reveal decrypt failed: {e}',
            ip_address=get_client_ip(request),
            extra_data={'event': 'vault_extension_reveal'},
            success=False,
        )
        return JsonResponse({'error': 'Decrypt failed.'}, status=500)

    consume_approval(password, request.user)

    AuditLog.log(
        user=request.user,
        action='read',
        organization=password.organization,
        object_type='vault.Password',
        object_id=password.pk,
        object_repr=password.title,
        description=f'vault_extension_reveal — {password.title}',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        extra_data={'event': 'vault_extension_reveal'},
    )

    return JsonResponse({'password': plaintext})


# ---------------------------------------------------------------------------
# Master-password verify (Phase 28 v3.17.329)
#
# The extension holds a master password the user typed; from it the
# extension derives an HMAC key. The server issues a per-call nonce, the
# extension returns HMAC_SHA256(derived_key, nonce_bytes). The server
# verifies by computing the same HMAC using the user's stored Django
# password hash (which already encodes the user's password) — this is a
# minimal, drop-in-replaceable proof-of-knowledge that doesn't require
# the server to ever see the master.
#
# This is intentionally minimal — a real production-grade KDF dance
# would store an explicit user-master salt + iteration count separate
# from the Django password hash. This stub gives the extension binary
# a stable contract to call against and the server a known place to
# upgrade to a stronger KDF later without changing the API shape.
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(['GET'])
@extension_auth_required
def verify_master_nonce(request):
    """
    Issue a per-call nonce the extension will HMAC with its derived key.

    GET /vault/api/extension/verify-master/nonce/

    Returns `{nonce}` — a base64-encoded random 32-byte value. Stored
    against the bearer-token row's `last_used_at` timestamp; the matching
    POST must arrive within 60 seconds.
    """
    import secrets
    nonce = secrets.token_urlsafe(32)
    request.extension_token._verify_nonce = nonce  # transient — only used in same call
    # We need to round-trip the nonce, so persist it in the cache for
    # this token id so the POST can find it.
    from django.core.cache import cache
    cache.set(f'extension_master_nonce:{request.extension_token.pk}', nonce, 60)
    return JsonResponse({'nonce': nonce, 'ttl_seconds': 60})


@csrf_exempt
@require_http_methods(['POST'])
@extension_auth_required
def verify_master(request):
    """
    Verify the extension's HMAC of the previously-issued nonce.

    POST /vault/api/extension/verify-master/

    Body (JSON): `{nonce, hmac_hex}` — the extension returns the same
    nonce it received from the GET endpoint plus the HMAC computed
    using its locally-derived key.

    Returns 200 `{verified: true}` on match, 401 otherwise. Server
    never sees the master password, only an HMAC of a server-issued
    nonce keyed by the user's existing password hash.

    Note: this is a minimal stub for the real KDF dance. It's
    drop-in-replaceable later without changing the API shape.
    """
    import hmac
    import hashlib
    from django.core.cache import cache

    payload = _parse_body(request)
    nonce = payload.get('nonce') or ''
    given = payload.get('hmac_hex') or ''
    if not nonce or not given:
        return JsonResponse({'error': 'nonce + hmac_hex required.'}, status=400)

    expected_nonce = cache.get(
        f'extension_master_nonce:{request.extension_token.pk}'
    )
    if not expected_nonce or not hmac.compare_digest(expected_nonce, nonce):
        return JsonResponse({'error': 'Nonce expired or mismatch.'}, status=401)

    # Derive the same HMAC the extension claims to have computed. Use the
    # user's stored Django password hash (which encodes their password);
    # the extension is expected to derive the same HMAC key locally from
    # the user-typed master password using the same KDF.
    user = request.user
    if not user.password:
        return JsonResponse({'error': 'User has no password set.'}, status=400)
    key = hashlib.sha256(user.password.encode('utf-8')).digest()
    expected_hmac = hmac.new(key, nonce.encode('utf-8'), hashlib.sha256).hexdigest()

    ok = hmac.compare_digest(expected_hmac, given)
    AuditLog.log(
        user=user,
        action='read',
        organization=request.current_organization,
        object_type='vault.WebExtensionAuthToken',
        object_id=request.extension_token.pk,
        description='vault_extension_verify_master',
        ip_address=get_client_ip(request),
        extra_data={'event': 'vault_extension_verify_master', 'verified': ok},
        success=ok,
    )
    # Burn the nonce.
    cache.delete(f'extension_master_nonce:{request.extension_token.pk}')

    if not ok:
        return JsonResponse({'error': 'HMAC mismatch.'}, status=401)
    return JsonResponse({'verified': True})


# ---------------------------------------------------------------------------
# Strong-password generator (Phase 28 v3.17.330)
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(['GET'])
@extension_auth_required
def generate(request):
    """
    Generate a strong password for the extension's "fill new credential" UI.

    GET /vault/api/extension/generate?length=24&symbols=1&numbers=1&uppercase=1&lowercase=1

    Returns `{password, length, charset_size, entropy_bits}`. Uses the
    same generator as the in-app `/vault/api/generate/` endpoint so the
    output distribution is identical.

    Gated by vault_extension_use.
    """
    import math
    from .utils import generate_password

    organization = request.current_organization
    if not _has_extension_permission(request.user, organization, 'vault_extension_use'):
        return JsonResponse({'error': 'Extension use permission required.'}, status=403)

    try:
        length = int(request.GET.get('length', 24))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid length.'}, status=400)
    length = max(8, min(length, 128))

    def _bool(name, default):
        v = request.GET.get(name)
        if v is None:
            return default
        return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on')

    use_uppercase = _bool('uppercase', True)
    use_lowercase = _bool('lowercase', True)
    use_digits    = _bool('numbers', _bool('digits', True))
    use_symbols   = _bool('symbols', True)

    if not any([use_uppercase, use_lowercase, use_digits, use_symbols]):
        return JsonResponse(
            {'error': 'At least one character class must be selected.'},
            status=400,
        )

    pw = generate_password(
        length=length,
        use_uppercase=use_uppercase,
        use_lowercase=use_lowercase,
        use_digits=use_digits,
        use_symbols=use_symbols,
    )

    charset_size = (
        (26 if use_uppercase else 0)
        + (26 if use_lowercase else 0)
        + (10 if use_digits else 0)
        + (26 if use_symbols else 0)  # we use 26 symbols in vault.utils.generate_password
    )
    entropy_bits = round(length * math.log2(charset_size), 2) if charset_size else 0.0

    return JsonResponse({
        'password': pw,
        'length': length,
        'charset_size': charset_size,
        'entropy_bits': entropy_bits,
    })
