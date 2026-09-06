"""
Phase 32 (v3.17.556) — network discovery views.

Two audiences: authenticated technicians generating and reviewing, and the
script itself, which arrives with nothing but a token.
"""
from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.permission_utils import user_has_perm
from core.models import Organization
from locations.models import Location

from .importer import import_payload
from .models import (
    DEFAULT_TOKEN_TTL_MINUTES, MAX_DEVICES_PER_UPLOAD,
    NetworkDiscoveryImport, NetworkDiscoveryToken,
)
from .script import render_discovery_script

logger = logging.getLogger(__name__)

# 8 MB. A sweep of five thousand devices is well under a megabyte of JSON; this
# is the point past which something is wrong rather than large.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# Uploads per source IP per hour. A site re-running a failed sweep a few times
# is normal; twenty is somebody testing tokens.
UPLOAD_RATE_LIMIT = 20
UPLOAD_RATE_WINDOW_SECONDS = 3600


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _audit(user, action, *, organization=None, description='', request=None,
           object_id=None, success=True):
    try:
        from audit.models import AuditLog
        AuditLog.log(
            user=user, action=action, organization=organization,
            object_type='network_discovery.NetworkDiscoveryToken',
            object_id=object_id, description=description[:1000],
            ip_address=_client_ip(request) if request else None,
            path=request.path if request else '', success=success,
        )
    except Exception:
        logger.exception('Could not write network discovery audit log')


def _scope(request, org_id, location_id):
    """The org and location for a management view, or 404.

    A location that does not belong to the organization in the URL is a 404
    rather than a redirect: the pairing is the whole scope of everything here,
    and a mismatched pair is not a request worth interpreting.
    """
    organization = get_object_or_404(Organization, pk=org_id)
    location = get_object_or_404(Location, pk=location_id)
    if location.organization_id and location.organization_id != organization.pk:
        raise Http404('That location does not belong to that organization')
    return organization, location


# ---------------------------------------------------------------------------
# Management (authenticated)
# ---------------------------------------------------------------------------

@login_required
def discovery_home(request, org_id, location_id):
    """Tokens and import history for one org + location."""
    organization, location = _scope(request, org_id, location_id)

    tokens = NetworkDiscoveryToken.objects.filter(
        organization=organization, location=location
    ).select_related('created_by')[:25]
    imports = NetworkDiscoveryImport.objects.filter(
        organization=organization, location=location
    ).select_related('token')[:25]

    return render(request, 'network_discovery/home.html', {
        'organization': organization,
        'location': location,
        'tokens': tokens,
        'imports': imports,
        'can_generate': user_has_perm(request.user, 'network_discovery_generate'),
        'default_ttl': DEFAULT_TOKEN_TTL_MINUTES,
        # Shown once, immediately after generation, then gone from the session.
        'new_token': request.session.pop('nd_new_token', None),
        'new_token_id': request.session.pop('nd_new_token_id', None),
    })


@login_required
@require_POST
def generate(request, org_id, location_id):
    """Issue a token and show its plaintext once."""
    organization, location = _scope(request, org_id, location_id)

    if not user_has_perm(request.user, 'network_discovery_generate'):
        _audit(request.user, 'error', organization=organization, request=request,
               description='Denied: no network_discovery_generate permission',
               success=False)
        messages.error(
            request,
            "You don't have permission to generate network discovery scripts.")
        return redirect('network_discovery:home', org_id=org_id,
                        location_id=location_id)

    try:
        ttl = int(request.POST.get('ttl_minutes') or DEFAULT_TOKEN_TTL_MINUTES)
    except (TypeError, ValueError):
        ttl = DEFAULT_TOKEN_TTL_MINUTES
    # Capped at a day. A token that lives for a week is a standing credential,
    # which is the thing this feature exists not to create.
    ttl = max(1, min(ttl, 1440))

    token, plaintext = NetworkDiscoveryToken.issue(
        organization=organization, location=location,
        created_by=request.user, ttl_minutes=ttl,
        notes=(request.POST.get('notes') or '').strip()[:255],
    )

    # Through the session rather than the URL or a message: it must not end up
    # in a browser history entry, a log line or a shared link.
    request.session['nd_new_token'] = plaintext
    request.session['nd_new_token_id'] = token.pk

    _audit(request.user, 'create', organization=organization, request=request,
           object_id=token.pk,
           description=f'Generated discovery token for location {location.pk}, '
                       f'valid {ttl} minute(s)')

    messages.success(
        request,
        'Token generated. It is shown once below — copy the script now, '
        'because it cannot be recovered afterwards.')
    return redirect('network_discovery:home', org_id=org_id,
                    location_id=location_id)


@login_required
def download_script(request, org_id, location_id, token_id):
    """Re-download the script for a token whose plaintext is still in session.

    The roadmap asks for a re-download that keeps the token hidden. That is only
    honestly possible while the plaintext is still in the generating user's
    session — the server holds a hash and cannot reconstruct it. Once the
    session is gone, so is the script, and the answer is a new token.
    """
    organization, location = _scope(request, org_id, location_id)
    token = get_object_or_404(
        NetworkDiscoveryToken, pk=token_id,
        organization=organization, location=location)

    plaintext = request.session.get('nd_new_token')
    if not plaintext or request.session.get('nd_new_token_id') != token.pk:
        messages.error(
            request,
            'That script is no longer available — the token is stored hashed '
            'and cannot be rebuilt. Generate a new one.')
        return redirect('network_discovery:home', org_id=org_id,
                        location_id=location_id)

    body = render_discovery_script(
        request, organization=organization, location=location,
        token_plaintext=plaintext, expires_at=token.expires_at)

    _audit(request.user, 'view', organization=organization, request=request,
           object_id=token.pk, description='Downloaded discovery script')

    response = HttpResponse(body, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="clientst0r-discovery-{location.pk}.ps1"')
    response['Cache-Control'] = 'no-store, private'
    return response


@login_required
@require_POST
def revoke(request, org_id, location_id, token_id):
    organization, location = _scope(request, org_id, location_id)
    token = get_object_or_404(
        NetworkDiscoveryToken, pk=token_id,
        organization=organization, location=location)

    if not user_has_perm(request.user, 'network_discovery_generate'):
        messages.error(request, "You don't have permission to revoke tokens.")
        return redirect('network_discovery:home', org_id=org_id,
                        location_id=location_id)

    token.revoke()
    _audit(request.user, 'update', organization=organization, request=request,
           object_id=token.pk, description='Revoked discovery token')
    messages.success(request, 'Token revoked. Any script holding it now fails.')
    return redirect('network_discovery:home', org_id=org_id,
                    location_id=location_id)


@login_required
def import_detail(request, org_id, location_id, import_id):
    organization, location = _scope(request, org_id, location_id)
    discovery_import = get_object_or_404(
        NetworkDiscoveryImport, pk=import_id,
        organization=organization, location=location)
    return render(request, 'network_discovery/import_detail.html', {
        'organization': organization,
        'location': location,
        'discovery_import': discovery_import,
        'results': discovery_import.results.select_related('asset')[:1000],
    })


# ---------------------------------------------------------------------------
# Upload (token-only)
# ---------------------------------------------------------------------------

def _rate_limited(source_ip) -> bool:
    """True when this source IP has uploaded too often lately.

    Counted from the import rows themselves rather than a cache, so the limit
    survives a restart and cannot be cleared by bouncing the process.
    """
    if not source_ip:
        return False
    since = timezone.now() - timezone.timedelta(seconds=UPLOAD_RATE_WINDOW_SECONDS)
    recent = NetworkDiscoveryImport.objects.filter(
        source_ip=source_ip, created_at__gte=since).count()
    return recent >= UPLOAD_RATE_LIMIT


@csrf_exempt
@require_POST
def upload(request):
    """Accept a discovery payload. Token-only auth, write-only, no session.

    CSRF-exempt because the caller is a PowerShell script with no cookie and no
    session — there is no ambient authority for a cross-site request to ride on.
    The token in the body is the only thing that authorises anything, and it can
    only add device records to the one location it was issued for.

    Every failure returns the same shape and says as little as possible: an
    anonymous caller must not learn whether a token exists, has expired, or was
    revoked.
    """
    source_ip = _client_ip(request)

    if len(request.body or b'') > MAX_UPLOAD_BYTES:
        return JsonResponse({'ok': False, 'error': 'payload too large'}, status=413)

    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'invalid JSON'}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'invalid payload'}, status=400)

    token = NetworkDiscoveryToken.find_usable(payload.get('token') or '')
    if token is None:
        # Deliberately indistinguishable from expired, revoked, spent and
        # never-existed.
        return JsonResponse({'ok': False, 'error': 'invalid token'}, status=403)

    if _rate_limited(source_ip):
        return JsonResponse(
            {'ok': False, 'error': 'too many uploads'}, status=429)

    devices = payload.get('devices')
    if not isinstance(devices, list):
        return JsonResponse(
            {'ok': False, 'error': 'devices must be a list'}, status=400)
    if len(devices) > MAX_DEVICES_PER_UPLOAD:
        return JsonResponse(
            {'ok': False, 'error': 'too many devices'}, status=413)

    dry_run = bool(payload.get('dry_run'))

    discovery_import = NetworkDiscoveryImport.objects.create(
        organization=token.organization,
        location=token.location,
        token=token,
        uploaded_by_user=token.created_by,
        source_ip=source_ip,
        is_dry_run=dry_run,
        raw_payload={
            'device_count': len(devices),
            'script_version': str(payload.get('script_version') or '')[:40],
            'hostname': str(payload.get('scanner_hostname') or '')[:120],
            'subnets': [str(s)[:40] for s in (payload.get('subnets') or [])[:20]]
                       if isinstance(payload.get('subnets'), list) else [],
            'dry_run': dry_run,
        },
    )

    counts = import_payload(discovery_import, devices, dry_run=dry_run)

    # Spend the token only once the work is done. Spending it first and then
    # failing would leave the technician holding a dead token and no import.
    token.record_use(
        source_ip=source_ip,
        user_agent=request.META.get('HTTP_USER_AGENT', ''))

    _audit(token.created_by, 'create', organization=token.organization,
           request=request, object_id=token.pk,
           description=(
               f'Discovery upload for location {token.location_id}: '
               f'{counts["device"]} device(s), {counts["imported"]} created, '
               f'{counts["updated"]} updated, {counts["skipped"]} skipped, '
               f'{counts["error"]} error(s)'
               + (' [dry run]' if dry_run else '')))

    return JsonResponse({
        'ok': True,
        'import_id': discovery_import.pk,
        'dry_run': dry_run,
        'devices': counts['device'],
        'created': counts['imported'],
        'updated': counts['updated'],
        'skipped': counts['skipped'],
        'errors': counts['error'],
    })
