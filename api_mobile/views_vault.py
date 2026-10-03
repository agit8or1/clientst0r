"""
Mobile API vault endpoints (v3.17.449).

Backs the `mobile/app/vault/` screens. Mirrors the security guarantees
of the web vault:

  * Org-scoped via `accessible_org_ids` — users can only list / read
    passwords for organizations they belong to.
  * Per-user reveal rate limit (30/hour) via `MobileVaultRevealRateThrottle`.
  * Per-credential approval gate honored — a `Password.requires_reveal_approval`
    entry returns 202 + `request_url` so the mobile UI can deep-link
    to the web approval flow rather than silently failing.
  * VaultAccessRule (GeoIP / IP / time-of-day) honored on reveal.
  * Audit logging for both list/detail reads and reveal attempts.

The list + detail endpoints NEVER include the secret. Only the reveal
endpoint returns plaintext, and it does so once per request — the
mobile client is documented to hold it in memory only.
"""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permission_utils import user_has_org_perm
from vault.permissions import can_access_password

from .scoping import accessible_org_ids
from .throttles import MobileVaultRevealRateThrottle


def _serialize_entry(p):
    """Common projection for list + detail. Never includes the secret."""
    return {
        'id': p.id,
        'title': p.title,
        'username': p.username or None,
        'url': p.url or None,
        'category': getattr(p, 'password_type', None) or None,
        'organization_id': p.organization_id,
        'organization_name': p.organization.name if p.organization_id else None,
        'notes': p.notes or None,
        'updated_at': p.updated_at.isoformat() if getattr(p, 'updated_at', None) else None,
        'requires_reveal_approval': bool(getattr(p, 'requires_reveal_approval', False)),
    }


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def vault_list_view(request):
    """
    GET  /api/mobile/v1/vault/?search=&organization_id=&page=
    POST /api/mobile/v1/vault/    (create — v3.17.479)

    Paginated list of vault entries the user can see. Org-scoped to
    `accessible_org_ids`. Search matches title / username / url / notes.

    POST body: `{organization_id, title, password, username?, url?,
                 notes?, category?}` — `category` maps to `password_type`
    (must be one of Password.PASSWORD_TYPES; defaults to 'website').
    Requires the `vault_create` role-template perm.
    """
    from vault.models import Password

    org_ids = list(accessible_org_ids(request.user))

    if request.method == 'POST':
        data = request.data or {}
        org_id = data.get('organization_id')
        try:
            org_id = int(org_id) if org_id is not None else None
        except (TypeError, ValueError):
            return Response({'detail': 'organization_id must be an integer'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not org_id or org_id not in org_ids:
            return Response(
                {'detail': 'organization_id required and must be accessible'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user_has_org_perm(request.user, org_id, 'vault_create'):
            return Response({'detail': 'Vault create permission required'},
                            status=status.HTTP_403_FORBIDDEN)
        title = (data.get('title') or '').strip()
        if not title:
            return Response({'detail': 'title is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        secret = data.get('password')
        if not isinstance(secret, str) or not secret:
            return Response({'detail': 'password is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        category = (data.get('category') or 'website').strip().lower()
        valid_types = {code for code, _ in Password.PASSWORD_TYPES}
        if category not in valid_types:
            category = 'website'
        entry = Password(
            organization_id=org_id,
            title=title[:255],
            username=(data.get('username') or '')[:255],
            url=(data.get('url') or '')[:2000],
            notes=(data.get('notes') or ''),
            password_type=category,
            created_by=request.user,
            last_modified_by=request.user,
        )
        try:
            entry.set_password(secret)
            entry.save()
        except Exception as exc:
            return Response({'detail': f'Failed to encrypt: {exc}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        _audit_vault_mutation(request, entry, action='create',
                              description=f"Vault entry '{entry.title}' created via mobile")
        return Response(_serialize_entry(entry),
                        status=status.HTTP_201_CREATED)

    qs = Password.objects.filter(organization_id__in=org_ids).select_related('organization')

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(username__icontains=search)
            | Q(url__icontains=search)
            | Q(notes__icontains=search)
        )

    organization_id = request.query_params.get('organization_id')
    if organization_id:
        try:
            org_id = int(organization_id)
            if org_id in org_ids:
                qs = qs.filter(organization_id=org_id)
            else:
                qs = qs.none()
        except ValueError:
            pass

    qs = qs.order_by('organization__name', 'title')

    try:
        page = max(int(request.query_params.get('page', 1)), 1)
    except ValueError:
        page = 1
    page_size = 50
    start = (page - 1) * page_size
    total = qs.count()
    rows = qs[start:start + page_size]

    return Response({
        'count': total,
        # Mobile PageResult expects next/previous as nullable URLs. We don't
        # build absolute URLs here (mobile uses ?page=N); pass null so the
        # client falls back to its own pagination logic.
        'next': None if (start + page_size) >= total else f'?page={page + 1}',
        'previous': None if page <= 1 else f'?page={page - 1}',
        'page': page,
        'page_size': page_size,
        'results': [_serialize_entry(p) for p in rows],
    })


def _audit_vault_mutation(request, password, *, action: str, description: str):
    """v3.17.479 — uniform audit logging for create / edit / rotate."""
    from audit.models import AuditLog
    try:
        AuditLog.objects.create(
            organization=password.organization,
            user=request.user, username=request.user.username,
            action=action,
            object_type='password', object_id=password.pk,
            object_repr=password.title,
            description=description,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:255],
            extra_data={'channel': 'mobile'},
        )
    except Exception:
        pass


@api_view(['GET', 'PATCH'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def vault_detail_view(request, pk: int):
    """
    GET   /api/mobile/v1/vault/<id>/
    PATCH /api/mobile/v1/vault/<id>/   (edit fields / rotate — v3.17.479)

    Cross-org reads return 404 (don't leak existence).

    PATCH body accepts any of: `{title, username, url, notes, category,
    password}`. `password` rotates the encrypted ciphertext via
    `Password.set_password()`. Requires the `vault_edit` role-template
    perm. Every mutation emits an audit-log row.
    """
    from vault.models import Password

    org_ids = list(accessible_org_ids(request.user))
    try:
        password = Password.objects.select_related('organization').get(
            pk=pk, organization_id__in=org_ids,
        )
    except Password.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(_serialize_entry(password))

    # PATCH
    if not can_access_password(request.user, password, 'vault_edit'):
        return Response(
            {'detail': "You don't have permission to edit vault items."},
            status=status.HTTP_403_FORBIDDEN,
        )
    data = request.data or {}
    fields_changed: list[str] = []
    rotated = False

    if 'title' in data:
        new_title = (data.get('title') or '').strip()
        if not new_title:
            return Response({'detail': 'title cannot be blank'},
                            status=status.HTTP_400_BAD_REQUEST)
        password.title = new_title[:255]
        fields_changed.append('title')
    if 'username' in data:
        password.username = (data.get('username') or '')[:255]
        fields_changed.append('username')
    if 'url' in data:
        password.url = (data.get('url') or '')[:2000]
        fields_changed.append('url')
    if 'notes' in data:
        password.notes = data.get('notes') or ''
        fields_changed.append('notes')
    if 'category' in data:
        category = (data.get('category') or '').strip().lower()
        valid_types = {code for code, _ in Password.PASSWORD_TYPES}
        if category and category not in valid_types:
            return Response(
                {'detail': f'invalid category; expected one of {sorted(valid_types)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if category:
            password.password_type = category
            fields_changed.append('category')

    if 'password' in data:
        secret = data.get('password')
        if not isinstance(secret, str) or not secret:
            return Response({'detail': 'password cannot be blank'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            password.set_password(secret)
            rotated = True
        except Exception as exc:
            return Response({'detail': f'Failed to encrypt: {exc}'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if not fields_changed and not rotated:
        return Response(_serialize_entry(password))

    password.last_modified_by = request.user
    password.save()

    if rotated:
        _audit_vault_mutation(
            request, password, action='update',
            description=(f"Vault password rotated for '{password.title}' via mobile"
                         + (f"; also updated {', '.join(fields_changed)}"
                            if fields_changed else '')),
        )
    else:
        _audit_vault_mutation(
            request, password, action='update',
            description=f"Vault fields {fields_changed} updated for '{password.title}' via mobile",
        )

    return Response(_serialize_entry(password))


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([MobileVaultRevealRateThrottle])
def vault_reveal_view(request, pk: int):
    """
    POST /api/mobile/v1/vault/<id>/reveal/

    Returns one of:
      * 200 `{secret}`           — decrypted plaintext
      * 202 `{request_url}`      — credential requires approval; client
                                   should open the web flow
      * 403 `{detail}`           — VaultAccessRule denied (GeoIP/IP/time)
      * 404                      — wrong org or no such credential
      * 429                      — per-user 30/hour throttle hit

    The mobile client MUST hold the secret in memory only — never
    SecureStore, never AsyncStorage, never any logger.
    """
    from vault.models import Password
    from audit.models import AuditLog

    org_ids = list(accessible_org_ids(request.user))
    try:
        password = Password.objects.select_related('organization').get(
            pk=pk, organization_id__in=org_ids,
        )
    except Password.DoesNotExist:
        return Response({'detail': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    if not can_access_password(request.user, password):
        return Response({'detail': 'Password reveal permission required'},
                        status=status.HTTP_403_FORBIDDEN)

    ip = request.META.get('REMOTE_ADDR')
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:255]

    # === Approval gate (Phase 37 / v3.17.241) ===
    if getattr(password, 'requires_reveal_approval', False):
        from vault.models import VaultRevealRequest
        approval = (VaultRevealRequest.objects
                    .filter(password=password, requester=request.user,
                            status='approved', revealed_at__isnull=True)
                    .order_by('-decided_at').first())
        if approval is None or not approval.is_currently_valid:
            try:
                AuditLog.objects.create(
                    organization=password.organization,
                    user=request.user, username=request.user.username,
                    action='reveal_blocked_no_approval',
                    object_type='password', object_id=password.pk,
                    object_repr=password.title,
                    description='Mobile password reveal blocked — no valid approval on file',
                    ip_address=ip, user_agent=ua,
                    success=False,
                )
            except Exception:
                pass
            # Tell the mobile client to deep-link the user to the web approval UI.
            return Response({
                'detail': 'This credential requires approval before reveal.',
                'request_url': f'/vault/passwords/{password.pk}/request-reveal/',
            }, status=status.HTTP_202_ACCEPTED)

    # === VaultAccessRule (GeoIP/IP/time-of-day) ===
    try:
        from vault.access_rules import evaluate as evaluate_access
        decision = evaluate_access(password, request.user, request)
    except Exception:
        # A policy outage must never release a protected credential.
        return Response({'detail': 'Vault access policy is temporarily unavailable'},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        AuditLog.log(
            user=request.user,
            action='read',
            organization=password.organization,
            object_type='password', object_id=password.pk,
            object_repr=password.title,
            description=(
                ('ALLOWED' if decision.get('allowed') else 'DENIED')
                + ' mobile_password_reveal - ' + str(decision.get('reason', ''))
            ),
            ip_address=ip, user_agent=ua,
            extra_data={
                'matched_rule_id': decision.get('matched_rule_id'),
                'access_ip': decision.get('ip'),
                'access_country': decision.get('country'),
                'channel': 'mobile',
            },
            success=bool(decision.get('allowed')),
        )
    except Exception:
        pass

    if not decision.get('allowed', False):
        return Response({
            'detail': decision.get('reason', 'Access denied'),
            'matched_rule_id': decision.get('matched_rule_id'),
        }, status=status.HTTP_403_FORBIDDEN)

    # === Decrypt + audit + mark approval used ===
    try:
        plaintext = password.get_password()
    except Exception as exc:
        try:
            AuditLog.objects.create(
                organization=password.organization,
                user=request.user, username=request.user.username,
                action='reveal_failed',
                object_type='password', object_id=password.pk,
                object_repr=password.title,
                description=f'Mobile decrypt failed: {exc}',
                ip_address=ip, user_agent=ua,
                success=False,
            )
        except Exception:
            pass
        return Response({'detail': 'Failed to decrypt password.'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if getattr(password, 'requires_reveal_approval', False):
        try:
            from vault.models import VaultRevealRequest
            approval = (VaultRevealRequest.objects
                        .filter(password=password, requester=request.user,
                                status='approved', revealed_at__isnull=True)
                        .order_by('-decided_at').first())
            if approval is not None:
                approval.mark_revealed()
        except Exception:
            pass

    try:
        AuditLog.objects.create(
            organization=password.organization,
            user=request.user, username=request.user.username,
            action='reveal',
            object_type='password', object_id=password.pk,
            object_repr=password.title,
            description=f"Password '{password.title}' revealed via mobile",
            ip_address=ip, user_agent=ua,
            extra_data={'channel': 'mobile'},
        )
    except Exception:
        pass

    return Response({'secret': plaintext}, status=status.HTTP_200_OK)
