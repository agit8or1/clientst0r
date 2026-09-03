"""
Vault views - Password management and security features
"""
import logging
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from core.middleware import get_request_organization
from core.decorators import require_write, require_organization_context
from audit.models import AuditLog
from .models import Password, PasswordBreachCheck, VaultAccessRule
from .forms import PasswordForm
from .breach_checker import PasswordBreachChecker
from .encryption import EncryptionError
from .access_rules import evaluate as _evaluate_vault_access
from django.conf import settings

# Initialize logger for this module
logger = logging.getLogger('vault')


@login_required
@ratelimit(key='user', rate='100/h', method='GET', block=False)
def password_list(request):
    """
    List all passwords in current organization, or all passwords if in global view mode.
    Rate limited to 100 requests per hour per user.
    Uses server-side DataTables processing for performance with large datasets.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    # Don't load passwords here - DataTables will fetch via AJAX
    return render(request, 'vault/password_list.html', {
        'in_global_view': in_global_view,
    })


@login_required
@ratelimit(key='user', rate='500/h', method='GET', block=False)
def password_list_datatables(request):
    """
    DataTables server-side processing endpoint for password list.
    Returns paginated JSON data for efficient handling of large datasets.
    Rate limited to 500 requests per hour per user.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    # Get DataTables parameters
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 25))
    search_value = request.GET.get('search[value]', '').strip()
    order_column_index = int(request.GET.get('order[0][column]', 0))
    order_direction = request.GET.get('order[0][dir]', 'asc')

    # Column mapping (must match template column order)
    columns = ['title', 'username', 'url', 'password_type', 'password_status', 'tags', 'id']
    order_column = columns[order_column_index] if order_column_index < len(columns) else 'title'

    # Base queryset
    if in_global_view:
        passwords = Password.objects.all().select_related('organization').prefetch_related('tags')
    else:
        passwords = Password.objects.for_organization(org).prefetch_related('tags')

    # Apply search filter
    if search_value:
        from django.db.models import Q
        passwords = passwords.filter(
            Q(title__icontains=search_value) |
            Q(username__icontains=search_value) |
            Q(url__icontains=search_value) |
            Q(notes__icontains=search_value)
        )

    # Get total count (before pagination)
    filtered_count = passwords.count()

    # Apply ordering
    if order_direction == 'desc':
        order_column = f'-{order_column}'
    passwords = passwords.order_by(order_column)

    # Apply pagination
    passwords = passwords[start:start + length]

    # Build data array
    data = []
    for password in passwords:
        # Get tags HTML
        tags_html = ''.join([
            f'<span class="badge" style="background-color: {tag.color}">{tag.name}</span> '
            for tag in password.tags.all()
        ])

        # Security badge
        if password.password_status == 'breached':
            security_badge = '<span class="badge bg-danger"><i class="fas fa-exclamation-triangle"></i> Breached</span>'
        elif password.password_status == 'weak':
            security_badge = '<span class="badge bg-warning"><i class="fas fa-exclamation-circle"></i> Weak</span>'
        else:
            security_badge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Safe</span>'

        # Expiry badge
        if password.expires_at:
            if password.is_expired:
                security_badge += ' <span class="badge bg-danger"><i class="fas fa-clock"></i> Expired</span>'
            elif password.days_until_expiration is not None and password.days_until_expiration <= 14:
                security_badge += f' <span class="badge bg-warning text-dark"><i class="fas fa-clock"></i> Expires in {password.days_until_expiration}d</span>'

        # URL icon
        url_html = f'<a href="{password.url}" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i></a>' if password.url else '—'

        # Actions
        from django.urls import reverse
        detail_url = reverse('vault:password_detail', args=[password.pk])
        edit_url = reverse('vault:password_edit', args=[password.pk])
        actions_html = f'''
        <div class="btn-group btn-group-sm">
            <a href="{detail_url}" class="btn btn-outline-primary" title="View"><i class="fas fa-eye"></i></a>
            <a href="{edit_url}" class="btn btn-outline-secondary" title="Edit"><i class="fas fa-edit"></i></a>
        </div>
        '''

        data.append([
            f'<a href="{detail_url}">{password.title}</a>',
            password.username or '—',
            url_html,
            f'<span class="badge bg-primary">{password.get_password_type_display()}</span>',
            security_badge,
            tags_html or '—',
            actions_html
        ])

    # Get total records count (without filters)
    if in_global_view:
        total_count = Password.objects.all().count()
    else:
        total_count = Password.objects.for_organization(org).count()

    # Return DataTables JSON response
    return JsonResponse({
        'draw': draw,
        'recordsTotal': total_count,
        'recordsFiltered': filtered_count,
        'data': data
    })


@login_required
@ratelimit(key='user', rate='200/h', method='GET', block=False)
def password_detail(request, pk):
    """
    View password details. Returns decrypted password via separate AJAX endpoint for security.
    Supports global view mode for superusers/staff users.
    Rate limited to 200 requests per hour per user.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: access password from any organization
        password = get_object_or_404(Password, pk=pk)
    else:
        # Organization view: filter by current org
        password = get_object_or_404(Password, pk=pk, organization=org)

    # v3.17.163: VaultAccessRule gate -- GeoIP / IP / time-of-day check.
    decision = _evaluate_vault_access(password, request.user, request)
    AuditLog.log(
        user=request.user,
        action='read',
        organization=password.organization,
        object_type='password',
        object_id=password.pk,
        object_repr=password.title,
        description=(
            ('ALLOWED' if decision['allowed'] else 'DENIED')
            + ' password_detail - ' + decision['reason']
        ),
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        extra_data={
            'matched_rule_id': decision.get('matched_rule_id'),
            'access_ip': decision.get('ip'),
            'access_country': decision.get('country'),
        },
        success=decision['allowed'],
    )
    if not decision['allowed']:
        messages.error(request, decision['reason'])
        return render(request, 'vault/access_denied.html', {
            'password': password,
            'reason': decision['reason'],
            'access_ip': decision.get('ip'),
            'access_country': decision.get('country'),
            'matched_rule_id': decision.get('matched_rule_id'),
        }, status=403)

    # Count active rules that apply to this password (for the "X access
    # rules apply" badge on the detail page).
    active_rules = VaultAccessRule.objects.filter(
        is_active=True,
        organization=password.organization,
    ).order_by('priority', 'pk')
    applicable_rule_count = sum(
        1 for r in active_rules if r.matches_target(password, request.user)
    )

    return render(request, 'vault/password_detail.html', {
        'password': password,
        'in_global_view': in_global_view,
        'applicable_rule_count': applicable_rule_count,
    })


@login_required
@ratelimit(key='user', rate='30/h', method='POST', block=True)
def password_reveal(request, pk):
    """
    AJAX endpoint to reveal decrypted password.
    Logs the reveal action for security audit.
    Rate limited to 30 reveals per hour per user to prevent abuse.
    """
    # Check if rate limited
    if getattr(request, 'limited', False):
        # Log rate limit attempt
        AuditLog.objects.create(
            organization=get_request_organization(request),
            user=request.user,
            username=request.user.username,
            action='password_reveal_rate_limited',
            description=f'Password reveal rate limit exceeded (30/hour)',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )
        return JsonResponse({
            'error': 'Rate limit exceeded. You can only reveal 30 passwords per hour.'
        }, status=429)

    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    if request.method == 'POST':
        # Phase 37 (v3.17.241): per-credential approval gate. If
        # `requires_reveal_approval=True`, the user needs a currently-
        # valid (approved, not expired, not yet used) VaultRevealRequest.
        # The break-glass flow creates an auto-approved request itself,
        # so it ends up satisfying this gate.
        if password.requires_reveal_approval:
            from .models import VaultRevealRequest
            approval = (VaultRevealRequest.objects
                        .filter(password=password, requester=request.user,
                                status='approved', revealed_at__isnull=True)
                        .order_by('-decided_at').first())
            if approval is None or not approval.is_currently_valid:
                AuditLog.objects.create(
                    organization=password.organization,
                    user=request.user, username=request.user.username,
                    action='reveal_blocked_no_approval',
                    object_type='password', object_id=password.pk,
                    object_repr=password.title,
                    description='Password reveal blocked — no valid approval on file',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    success=False,
                )
                return JsonResponse({
                    'error': 'This credential requires approval before reveal. Request approval or use break-glass.',
                    'requires_approval': True,
                }, status=403)
        # v3.17.163: VaultAccessRule gate -- GeoIP / IP / time-of-day check.
        decision = _evaluate_vault_access(password, request.user, request)
        AuditLog.log(
            user=request.user,
            action='read',
            organization=password.organization,
            object_type='password',
            object_id=password.pk,
            object_repr=password.title,
            description=(
                ('ALLOWED' if decision['allowed'] else 'DENIED')
                + ' password_reveal - ' + decision['reason']
            ),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            extra_data={
                'matched_rule_id': decision.get('matched_rule_id'),
                'access_ip': decision.get('ip'),
                'access_country': decision.get('country'),
            },
            success=decision['allowed'],
        )
        if not decision['allowed']:
            return JsonResponse({
                'error': decision['reason'],
                'access_denied': True,
                'matched_rule_id': decision.get('matched_rule_id'),
            }, status=403)

        try:
            plaintext = password.get_password()

            # Phase 37 (v3.17.241): mark the satisfying approval as used so
            # the next reveal needs a fresh request.
            if password.requires_reveal_approval:
                from .models import VaultRevealRequest
                approval = (VaultRevealRequest.objects
                            .filter(password=password, requester=request.user,
                                    status='approved', revealed_at__isnull=True)
                            .order_by('-decided_at').first())
                if approval is not None:
                    approval.mark_revealed()

            # Create audit log for password reveal
            AuditLog.objects.create(
                organization=org,
                user=request.user,
                username=request.user.username,
                action='reveal',
                object_type='password',
                object_id=password.id,
                object_repr=password.title,
                description=f"Password '{password.title}' revealed",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )

            return JsonResponse({'password': plaintext})
        except (ValueError, AttributeError) as e:
            # Encryption/decryption errors
            logger.error(f"Error revealing password {pk}: {e}")
            return JsonResponse({'error': 'Failed to decrypt password'}, status=500)
        except Exception as e:
            # Unexpected errors
            logger.error(f"Unexpected error revealing password {pk}: {e}")
            return JsonResponse({'error': 'An unexpected error occurred'}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


# ---------------------------------------------------------------------------
# Phase 37 (v3.17.241) — Vault Approval & Break-Glass Workflow
# ---------------------------------------------------------------------------

@login_required
def password_request_reveal(request, pk):
    """
    Submit a `VaultRevealRequest` for a password whose
    `requires_reveal_approval=True`. POST: justification (required).
    Notifies superusers via email so they can approve.
    """
    from django.views.decorators.http import require_http_methods
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)
    if in_global_view:
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    if not password.requires_reveal_approval:
        return JsonResponse({'error': 'This password does not require approval'},
                            status=400)

    justification = (request.POST.get('justification') or '').strip()
    if not justification:
        return JsonResponse({'error': 'Justification is required'}, status=400)
    from .models import VaultRevealRequest
    req = VaultRevealRequest.objects.create(
        password=password, requester=request.user,
        justification=justification[:5000],
    )
    AuditLog.objects.create(
        organization=password.organization,
        user=request.user, username=request.user.username,
        action='vault_reveal_requested',
        object_type='password', object_id=password.pk,
        object_repr=password.title,
        description=f'Reveal approval requested: {justification[:200]}',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
    _notify_admins_of_reveal_request(req)
    return JsonResponse({'ok': True, 'request_id': req.pk, 'status': req.status})


@login_required
def password_break_glass(request, pk):
    """
    Emergency reveal — bypasses the approval queue. Creates a
    `VaultRevealRequest` flagged `is_break_glass=True` and immediately
    approves it (with the requester themselves as the approver). Logs
    HARD + emails admins. The justification is mandatory and ≥30 chars
    so the requester has to actually explain themselves.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)
    if in_global_view:
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    if not password.requires_reveal_approval:
        return JsonResponse({'error': 'This password does not require approval'},
                            status=400)
    justification = (request.POST.get('justification') or '').strip()
    if len(justification) < 30:
        return JsonResponse({
            'error': 'Break-glass requires a justification of at least 30 characters.',
        }, status=400)

    from .models import VaultRevealRequest
    req = VaultRevealRequest.objects.create(
        password=password, requester=request.user,
        justification=justification[:5000],
        is_break_glass=True,
    )
    req.approve(user=request.user,
                notes='[BREAK-GLASS] self-approved emergency access')
    AuditLog.objects.create(
        organization=password.organization,
        user=request.user, username=request.user.username,
        action='vault_break_glass',
        object_type='password', object_id=password.pk,
        object_repr=password.title,
        description=f'BREAK-GLASS reveal: {justification[:200]}',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
    _notify_admins_of_break_glass(req)
    return JsonResponse({'ok': True, 'request_id': req.pk,
                         'status': req.status, 'is_break_glass': True})


def _can_decide_vault_reveal(user, request_obj, request_meta):
    """
    Phase 37 v2 (v3.17.247): policy for who can approve/deny a vault
    reveal request.

      - Superuser / MSP staff_user: always allowed (existing behavior).
      - Client-org admin (Membership.is_org_admin=True for the password's
        organization): allowed for reveals OF passwords in their own org.
        Closes the "client-level vault approval rules" sub-bullet so MSPs
        can route a client org's vault approvals to that client's own
        admin instead of an MSP staff member.
      - Self-approval is forbidden (the requester can't approve their
        own request) regardless of role — defense in depth.
    """
    if user.is_superuser:
        return user.id != request_obj.requester_id, 'self_approval_blocked'
    is_staff = getattr(request_meta, 'is_staff_user', False)
    if is_staff:
        return user.id != request_obj.requester_id, 'self_approval_blocked'
    # Client-org admin path.
    from accounts.models import Membership
    if user.id == request_obj.requester_id:
        return False, 'self_approval_blocked'
    is_client_admin = Membership.objects.filter(
        user=user, organization_id=request_obj.password.organization_id,
        is_active=True, is_org_admin=True,
    ).exists()
    return is_client_admin, 'allowed_as_client_admin' if is_client_admin else 'not_allowed'


@login_required
def vault_reveal_request_decide(request, pk):
    """Approve or deny a pending VaultRevealRequest.
    Staff/superuser OR client-org admin (Phase 37 v2)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    from .models import VaultRevealRequest
    req = get_object_or_404(VaultRevealRequest, pk=pk)
    allowed, reason = _can_decide_vault_reveal(request.user, req, request)
    if not allowed:
        if reason == 'self_approval_blocked':
            return JsonResponse(
                {'error': 'You cannot approve your own reveal request.'},
                status=403,
            )
        return JsonResponse(
            {'error': 'Only staff, superuser, or a client-org admin can decide reveal requests.'},
            status=403,
        )
    if req.status != 'pending':
        return JsonResponse({'error': f'Request already {req.status}'}, status=400)
    decision = request.POST.get('decision') or ''
    notes = (request.POST.get('notes') or '').strip()[:5000]
    if decision == 'approve':
        req.approve(user=request.user, notes=notes)
        AuditLog.objects.create(
            organization=req.password.organization,
            user=request.user, username=request.user.username,
            action='vault_reveal_approved',
            object_type='vault.VaultRevealRequest', object_id=req.pk,
            object_repr=str(req),
            description=f'Approved reveal request for {req.password.title}',
            ip_address=request.META.get('REMOTE_ADDR'),
        )
    elif decision == 'deny':
        req.deny(user=request.user, notes=notes)
        AuditLog.objects.create(
            organization=req.password.organization,
            user=request.user, username=request.user.username,
            action='vault_reveal_denied',
            object_type='vault.VaultRevealRequest', object_id=req.pk,
            object_repr=str(req),
            description=f'Denied reveal request for {req.password.title}',
            ip_address=request.META.get('REMOTE_ADDR'),
        )
    else:
        return JsonResponse({'error': 'decision must be approve or deny'},
                            status=400)
    return JsonResponse({'ok': True, 'status': req.status})


@login_required
def vault_reveal_request_list(request):
    """Staff list of pending VaultRevealRequest rows + recent decisions."""
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not (request.user.is_superuser or is_staff):
        return redirect('core:dashboard')
    from .models import VaultRevealRequest
    pending = (VaultRevealRequest.objects.filter(status='pending')
               .select_related('password', 'requester'))
    decided = (VaultRevealRequest.objects.exclude(status='pending')
               .select_related('password', 'requester', 'decided_by')
               .order_by('-decided_at')[:50])
    return render(request, 'vault/reveal_request_list.html', {
        'pending': pending,
        'decided': decided,
    })


def _notify_admins_of_reveal_request(req):
    try:
        from django.core.mail import send_mail
        admin_emails = list(
            User.objects.filter(is_superuser=True, is_active=True)
                         .exclude(email='').values_list('email', flat=True)
        )
        if not admin_emails:
            return
        send_mail(
            subject=f'[Vault] Reveal approval requested: {req.password.title}',
            message=(
                f'{req.requester.username} has requested approval to reveal '
                f'"{req.password.title}".\n\n'
                f'Justification:\n{req.justification}\n\n'
                f'Review at /vault/reveal-requests/'
            ),
            from_email=None,
            recipient_list=admin_emails,
            fail_silently=True,
        )
    except Exception:
        logger.warning('Failed to notify admins of reveal request', exc_info=True)


def _notify_admins_of_break_glass(req):
    try:
        from django.core.mail import send_mail
        admin_emails = list(
            User.objects.filter(is_superuser=True, is_active=True)
                         .exclude(email='').values_list('email', flat=True)
        )
        if not admin_emails:
            return
        send_mail(
            subject=f'[Vault BREAK-GLASS] {req.requester.username} revealed {req.password.title}',
            message=(
                f'BREAK-GLASS emergency access used.\n\n'
                f'Requester: {req.requester.username}\n'
                f'Credential: {req.password.title}\n\n'
                f'Justification:\n{req.justification}\n\n'
                f'Review at /vault/reveal-requests/'
            ),
            from_email=None,
            recipient_list=admin_emails,
            fail_silently=True,
        )
    except Exception:
        logger.warning('Failed to notify admins of break-glass event', exc_info=True)


@login_required
def password_test_breach(request, pk):
    """
    AJAX endpoint to test password against breach database.
    Creates a breach check record and returns the results.
    """
    org = get_request_organization(request)
    _is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not org and (request.user.is_superuser or _is_staff):
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            # Check if this is an OTP type (no password to check)
            if password.password_type == 'otp':
                return JsonResponse({'error': 'Cannot check OTP entries for breaches'}, status=400)

            # Check if password is set
            if not password.encrypted_password:
                return JsonResponse({'error': 'No password set for this entry'}, status=400)

            # Get the plaintext password
            try:
                plaintext = password.get_password()
            except Exception as decrypt_error:
                import logging
                logger = logging.getLogger('vault')
                logger.error(f"Decryption failed for password {password.id}: {decrypt_error}")
                return JsonResponse({'error': 'Failed to decrypt password. The encryption key may have changed.'}, status=500)

            # Validate password is not empty
            if not plaintext or not plaintext.strip():
                return JsonResponse({'error': 'Password is empty'}, status=400)

            # Check against breach database
            checker = PasswordBreachChecker()
            is_breached, count = checker.check_password(plaintext)

            # Create breach check record
            breach_check = PasswordBreachCheck.objects.create(
                password=password,
                is_breached=is_breached,
                breach_count=count
            )

            # Create audit log
            AuditLog.objects.create(
                organization=org,
                user=request.user,
                username=request.user.username,
                action='check',
                object_type='password',
                object_id=password.id,
                object_repr=password.title,
                description=f"Password '{password.title}' checked for breaches - {'BREACHED' if is_breached else 'Safe'}",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )

            return JsonResponse({
                'is_breached': is_breached,
                'breach_count': count,
                'checked_at': breach_check.checked_at.strftime('%b %d, %Y %I:%M %p')
            })
        except (requests.RequestException, requests.Timeout) as e:
            # Network/API errors
            import logging
            logger = logging.getLogger('vault')
            logger.error(f"Network error testing password {password.id} for breaches: {e}")
            return JsonResponse({'error': 'Failed to connect to breach database'}, status=503)
        except (ValueError, KeyError) as e:
            # Data parsing errors
            import logging
            logger = logging.getLogger('vault')
            logger.error(f"Data error testing password {password.id} for breaches: {e}")
            return JsonResponse({'error': 'Failed to parse breach data'}, status=500)
        except Exception as e:
            import logging
            logger = logging.getLogger('vault')
            logger.error(f"Unexpected error testing password {password.id} for breaches: {e}")
            return JsonResponse({'error': 'An unexpected error occurred'}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@require_write
@require_organization_context
def password_create(request):
    """
    Create new password entry.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = PasswordForm(request.POST, organization=org)
        if form.is_valid():
            try:
                password = form.save(commit=False)
                password.organization = org
                password.created_by = request.user
                password.last_modified_by = request.user
                password.save()
                form.save_m2m()  # Save tags
                messages.success(request, f"Password '{password.title}' created successfully.")
                return redirect('vault:password_detail', pk=password.pk)
            except EncryptionError as e:
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart clientst0r-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
    else:
        form = PasswordForm(organization=org)

    return render(request, 'vault/password_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@require_write
def password_edit(request, pk):
    """
    Edit password entry.
    """
    org = get_request_organization(request)
    password = get_object_or_404(Password, pk=pk, organization=org)

    if request.method == 'POST':
        form = PasswordForm(request.POST, instance=password, organization=org)
        if form.is_valid():
            try:
                password = form.save(commit=False)
                password.last_modified_by = request.user
                # If the expiry date changed, reset the notification flag so it fires again
                if 'expires_at' in form.changed_data:
                    password.expiry_notification_sent = False
                password.save()
                form.save_m2m()
                AuditLog.log(
                    user=request.user, action='update',
                    organization=org, object_type='password',
                    object_id=password.pk, object_repr=password.title,
                    description=(
                        f"Password '{password.title}' updated"
                        + (f' (changed: {", ".join(form.changed_data)})'
                           if form.changed_data else '')
                    ),
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    success=True,
                )
                messages.success(request, f"Password '{password.title}' updated successfully.")
                return redirect('vault:password_detail', pk=password.pk)
            except EncryptionError as e:
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                AuditLog.log(
                    user=request.user, action='update',
                    organization=org, object_type='password',
                    object_id=password.pk, object_repr=password.title,
                    description=f"Password update FAILED — encryption error: {error_msg[:200]}",
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    success=False,
                )
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        f"<code>cd {settings.BASE_DIR}<br>"
                        "source venv/bin/activate<br>"
                        "NEW_KEY=$(python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")<br>"
                        "sed -i \"s|^APP_MASTER_KEY=.*|APP_MASTER_KEY=${NEW_KEY}|\" .env<br>"
                        "sudo systemctl restart clientst0r-gunicorn.service</code><br><br>"
                        "The key must be exactly 44 characters (base64-encoded 32 bytes).",
                        extra_tags='safe'
                    )
                else:
                    messages.error(request, f"Encryption error: {error_msg}")
        else:
            AuditLog.log(
                user=request.user, action='update',
                organization=org, object_type='password',
                object_id=password.pk, object_repr=password.title,
                description=(
                    f"Password update FAILED — form validation: "
                    f"{', '.join(form.errors.keys())}"
                ),
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                success=False,
            )
    else:
        form = PasswordForm(instance=password, organization=org)

    return render(request, 'vault/password_form.html', {
        'form': form,
        'password': password,
        'action': 'Edit',
    })


@login_required
@require_write
def password_delete(request, pk):
    """
    Delete password entry.
    """
    org = get_request_organization(request)
    password = get_object_or_404(Password, pk=pk, organization=org)

    if request.method == 'POST':
        title = password.title
        deleted_pk = password.pk
        password.delete()
        AuditLog.log(
            user=request.user, action='delete',
            organization=org, object_type='password',
            object_id=deleted_pk, object_repr=title,
            description=f"Password '{title}' deleted",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            success=True,
        )
        messages.success(request, f"Password '{title}' deleted successfully.")
        return redirect('vault:password_list')

    return render(request, 'vault/password_confirm_delete.html', {
        'password': password,
    })


@login_required
def generate_password_api(request):
    """
    API endpoint to generate secure passwords.
    """
    from .utils import generate_password

    # Security: Validate and bound password length to prevent DoS
    try:
        length = int(request.GET.get('length', 16))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid length parameter'}, status=400)

    # Enforce minimum and maximum length constraints
    MIN_LENGTH = 8
    MAX_LENGTH = 128

    if length < MIN_LENGTH:
        return JsonResponse({'error': f'Password length must be at least {MIN_LENGTH} characters'}, status=400)

    if length > MAX_LENGTH:
        return JsonResponse({'error': f'Password length cannot exceed {MAX_LENGTH} characters'}, status=400)

    use_uppercase = request.GET.get('uppercase', 'true').lower() == 'true'
    use_lowercase = request.GET.get('lowercase', 'true').lower() == 'true'
    use_digits = request.GET.get('digits', 'true').lower() == 'true'
    use_symbols = request.GET.get('symbols', 'true').lower() == 'true'

    # Ensure at least one character type is selected
    if not any([use_uppercase, use_lowercase, use_digits, use_symbols]):
        return JsonResponse({'error': 'At least one character type must be selected'}, status=400)

    password = generate_password(
        length=length,
        use_uppercase=use_uppercase,
        use_lowercase=use_lowercase,
        use_digits=use_digits,
        use_symbols=use_symbols
    )

    return JsonResponse({'password': password})


@login_required
def check_password_strength_api(request):
    """
    API endpoint to check password strength.
    """
    from .utils import calculate_password_strength

    password = request.POST.get('password', '')

    # FIX: Validate and sanitize input
    if not isinstance(password, str):
        return JsonResponse({'error': 'Invalid password format'}, status=400)

    # Limit password length to prevent DOS
    MAX_PASSWORD_LENGTH = 1000
    if len(password) > MAX_PASSWORD_LENGTH:
        return JsonResponse({'error': f'Password too long (max {MAX_PASSWORD_LENGTH} characters)'}, status=400)

    strength_data = calculate_password_strength(password)

    return JsonResponse(strength_data)


@login_required
@ratelimit(key='user', rate='100/h', method='GET', block=True)
def generate_otp_api(request, pk):
    """
    API endpoint to generate TOTP code.
    Works with any password that has a TOTP secret configured.
    Rate limited to 100 requests per hour per user.
    """
    org = get_request_organization(request)
    _is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not org and (request.user.is_superuser or _is_staff):
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    try:
        otp_data = password.generate_otp()
        if otp_data:
            # Check if error dict was returned
            if otp_data.get('error'):
                return JsonResponse({'error': otp_data.get('message', 'Failed to generate OTP code')}, status=400)

            # Log TOTP generation for audit
            AuditLog.objects.create(
                organization=org,
                user=request.user,
                username=request.user.username,
                action='read',
                object_type='password',
                object_id=password.id,
                object_repr=password.title,
                description=f"TOTP code generated for '{password.title}'",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )
            return JsonResponse({
                'otp': otp_data['code'],
                'time_remaining': otp_data['time_remaining'],
                'issuer': otp_data['issuer']
            })
        else:
            return JsonResponse({'error': 'TOTP secret not configured for this password'}, status=400)
    except (ValueError, AttributeError, KeyError) as e:
        # FIX: Catch specific exceptions for better error handling
        logger.error(f"Error generating OTP for password {pk}: {e}")
        return JsonResponse({'error': 'Failed to generate OTP code'}, status=500)
    except Exception as e:
        # Catch-all for unexpected errors
        logger.error(f"Unexpected error generating OTP for password {pk}: {e}")
        return JsonResponse({'error': 'An unexpected error occurred'}, status=500)


@login_required
def password_qrcode(request, pk):
    """
    Generate QR code for TOTP setup.
    """
    from django.http import HttpResponse
    import qrcode
    from io import BytesIO
    import pyotp

    org = get_request_organization(request)
    _is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    if not org and (request.user.is_superuser or _is_staff):
        password = get_object_or_404(Password, pk=pk)
    else:
        password = get_object_or_404(Password, pk=pk, organization=org)

    if password.password_type != 'otp' or not password.otp_secret:
        return HttpResponse("Not an OTP entry or secret not configured", status=400)

    try:
        secret = password.get_otp_secret()
        issuer = password.otp_issuer or org.name
        account_name = password.username or password.title

        # Generate provisioning URI
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=account_name, issuer_name=issuer)

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Return as PNG
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        # Log QR code view for audit
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            username=request.user.username,
            action='read',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            description=f"TOTP QR code viewed for '{password.title}'",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        return HttpResponse(buffer.getvalue(), content_type='image/png')
    except (ValueError, AttributeError) as e:
        # Decryption or data errors
        logger.error(f"Error generating QR code for password {pk}: {e}")
        return HttpResponse("Failed to generate QR code - invalid TOTP secret", status=500)
    except Exception as e:
        # Unexpected errors
        logger.error(f"Unexpected error generating QR code for password {pk}: {e}")
        return HttpResponse("An unexpected error occurred", status=500)


# ============================================================================
# Personal Vault Views (User-specific encrypted notes)
# ============================================================================

@login_required
def personal_vault_list(request):
    """List user's personal vault items."""
    from .models import PersonalVault
    
    items = PersonalVault.objects.filter(user=request.user).order_by('-is_favorite', '-updated_at')
    
    return render(request, 'vault/personal_vault_list.html', {
        'items': items,
    })


@login_required
def personal_vault_detail(request, pk):
    """View personal vault item."""
    from .models import PersonalVault
    
    item = get_object_or_404(PersonalVault, pk=pk, user=request.user)
    
    return render(request, 'vault/personal_vault_detail.html', {
        'item': item,
        'content': item.get_content(),
    })


@login_required
def personal_vault_create(request):
    """Create new personal vault item."""
    from .models import PersonalVault
    
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        category = request.POST.get('category', '')
        is_favorite = request.POST.get('is_favorite') == 'on'
        
        if title and content:
            item = PersonalVault(user=request.user, title=title, category=category, is_favorite=is_favorite)
            item.set_content(content)
            item.save()
            messages.success(request, f"Note '{title}' created successfully.")
            return redirect('vault:personal_vault_detail', pk=item.pk)
        else:
            messages.error(request, "Title and content are required.")
    
    return render(request, 'vault/personal_vault_form.html', {
        'action': 'Create',
    })


@login_required
def personal_vault_edit(request, pk):
    """Edit personal vault item."""
    from .models import PersonalVault
    
    item = get_object_or_404(PersonalVault, pk=pk, user=request.user)
    
    if request.method == 'POST':
        item.title = request.POST.get('title')
        item.category = request.POST.get('category', '')
        item.is_favorite = request.POST.get('is_favorite') == 'on'
        
        content = request.POST.get('content')
        if content:
            item.set_content(content)
        
        item.save()
        messages.success(request, f"Note '{item.title}' updated successfully.")
        return redirect('vault:personal_vault_detail', pk=item.pk)
    
    return render(request, 'vault/personal_vault_form.html', {
        'action': 'Edit',
        'item': item,
        'content': item.get_content(),
    })


@login_required
def personal_vault_delete(request, pk):
    """Delete personal vault item."""
    from .models import PersonalVault
    
    item = get_object_or_404(PersonalVault, pk=pk, user=request.user)
    
    if request.method == 'POST':
        title = item.title
        item.delete()
        messages.success(request, f"Note '{title}' deleted.")
        return redirect('vault:personal_vault_list')
    
    return render(request, 'vault/personal_vault_confirm_delete.html', {
        'item': item,
    })


@login_required
@require_http_methods(["GET", "POST"])
def bitwarden_import(request):
    """Import passwords from Bitwarden/Vaultwarden JSON export."""
    from .bitwarden_import import import_bitwarden_json
    from .forms import BitwardenImportForm
    
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'Organization context required.')
        return redirect('accounts:organization_list')
    
    if request.method == 'POST':
        form = BitwardenImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                json_file = form.cleaned_data['json_file']
                folder_prefix = form.cleaned_data.get('folder_prefix', '')
                update_existing = form.cleaned_data.get('update_existing', False)
                
                # Read file content
                file_content = json_file.read()
                
                # Perform import
                stats = import_bitwarden_json(
                    file_content,
                    org,
                    request.user,
                    folder_prefix,
                    update_existing
                )
                
                # Display results
                if stats['errors']:
                    messages.warning(
                        request,
                        f"Import completed with errors. "
                        f"Created: {stats['passwords_created']}, "
                        f"Updated: {stats['passwords_updated']}, "
                        f"Skipped: {stats['passwords_skipped']}, "
                        f"Folders: {stats['folders_created']}"
                    )
                    for error in stats['errors'][:5]:  # Show first 5 errors
                        messages.error(request, error)
                    if len(stats['errors']) > 5:
                        messages.error(request, f"...and {len(stats['errors']) - 5} more errors")
                else:
                    messages.success(
                        request,
                        f"Successfully imported {stats['passwords_created']} passwords "
                        f"and {stats['folders_created']} folders. "
                        f"Updated: {stats['passwords_updated']}, Skipped: {stats['passwords_skipped']}"
                    )
                
                return redirect('vault:password_list')
                
            except Exception as e:
                import logging
                logger = logging.getLogger('vault')
                logger.error(f"Bitwarden import failed: {str(e)}", exc_info=True)
                messages.error(request, f"Import failed: {str(e)}")
    else:
        form = BitwardenImportForm()
    
    return render(request, 'vault/bitwarden_import.html', {
        'form': form,
        'current_organization': org,
    })


# ---------------------------------------------------------------------------
# VaultAccessRule management views (v3.17.163)
# ---------------------------------------------------------------------------

from accounts.permission_utils import user_has_perm as _user_has_perm
from django.core.exceptions import PermissionDenied
from django.urls import reverse


WEEKDAYS = [
    (0, 'Mon'), (1, 'Tue'), (2, 'Wed'), (3, 'Thu'),
    (4, 'Fri'), (5, 'Sat'), (6, 'Sun'),
]
COMMON_TIMEZONES = [
    'UTC', 'America/New_York', 'America/Chicago', 'America/Denver',
    'America/Los_Angeles', 'America/Toronto', 'America/Vancouver',
    'Europe/London', 'Europe/Paris', 'Europe/Berlin',
    'Asia/Tokyo', 'Asia/Singapore', 'Australia/Sydney',
]


def _require_access_rules_perm(request):
    if not _user_has_perm(request.user, 'vault_manage_access_rules'):
        raise PermissionDenied(
            "You don't have permission to manage vault access rules."
        )


def _parse_csv_codes(raw):
    """Turn 'US, CA , gb' -> ['US', 'CA', 'GB']. Empty -> []."""
    if not raw:
        return []
    out = []
    for tok in raw.replace('\n', ',').split(','):
        tok = tok.strip().upper()
        if tok:
            out.append(tok)
    # Dedup preserving order
    seen = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def _parse_lines(raw):
    if not raw:
        return []
    out = []
    for line in raw.replace(',', '\n').splitlines():
        line = line.strip()
        if line:
            out.append(line)
    seen = set()
    return [t for t in out if not (t in seen or seen.add(t))]


@login_required
def access_rule_list(request):
    """Table of every VaultAccessRule for the current org (or all orgs
    for superuser)."""
    _require_access_rules_perm(request)
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        rules = VaultAccessRule.objects.all().select_related(
            'organization', 'target_password', 'target_user',
        )
    else:
        rules = VaultAccessRule.objects.filter(organization=org).select_related(
            'organization', 'target_password', 'target_user',
        )

    # Filter chips
    status_filter = request.GET.get('status', '').lower()
    if status_filter == 'active':
        rules = rules.filter(is_active=True)
    elif status_filter == 'inactive':
        rules = rules.filter(is_active=False)
    scope_filter = request.GET.get('scope', '').lower()
    if scope_filter in {'item', 'user', 'organization'}:
        rules = rules.filter(scope=scope_filter)
    password_filter = request.GET.get('password')
    if password_filter:
        try:
            rules = rules.filter(target_password_id=int(password_filter))
        except (TypeError, ValueError):
            pass

    rules = rules.order_by('priority', '-updated_at')

    return render(request, 'vault/access_rule_list.html', {
        'rules': rules,
        'in_global_view': in_global_view,
        'status_filter': status_filter,
        'scope_filter': scope_filter,
        'password_filter': password_filter,
    })


@login_required
def access_rule_form(request, pk=None):
    """Create or edit a VaultAccessRule."""
    _require_access_rules_perm(request)
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if pk:
        if in_global_view:
            rule = get_object_or_404(VaultAccessRule, pk=pk)
        else:
            rule = get_object_or_404(VaultAccessRule, pk=pk, organization=org)
    else:
        rule = None

    # Pickers
    if in_global_view:
        passwords_qs = Password.objects.all().order_by('organization__name', 'title')
    else:
        passwords_qs = Password.objects.filter(organization=org).order_by('title')

    from django.contrib.auth.models import User as _User
    if in_global_view:
        users_qs = _User.objects.filter(is_active=True).order_by('username')
    else:
        # Users that are members of this org
        from accounts.models import Membership
        members = Membership.objects.filter(
            organization=org, is_active=True,
        ).values_list('user_id', flat=True)
        users_qs = _User.objects.filter(pk__in=members).order_by('username')

    error = None

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        is_active = bool(request.POST.get('is_active'))
        try:
            priority = int(request.POST.get('priority') or '100')
        except (TypeError, ValueError):
            priority = 100
        effect = request.POST.get('effect') or 'allow'
        if effect not in {'allow', 'deny'}:
            effect = 'allow'
        scope = request.POST.get('scope') or 'organization'
        if scope not in {'item', 'user', 'organization'}:
            scope = 'organization'

        target_password_id = request.POST.get('target_password') or None
        target_user_id = request.POST.get('target_user') or None

        allowed_countries = _parse_csv_codes(request.POST.get('allowed_countries'))
        blocked_countries = _parse_csv_codes(request.POST.get('blocked_countries'))
        allowed_cidrs = _parse_lines(request.POST.get('allowed_cidrs'))
        blocked_cidrs = _parse_lines(request.POST.get('blocked_cidrs'))

        weekdays = []
        for day, _ in WEEKDAYS:
            if request.POST.get(f'weekday_{day}'):
                weekdays.append(day)

        def _parse_time(val):
            val = (val or '').strip()
            if not val:
                return None
            try:
                # Accept HH:MM or HH:MM:SS
                parts = val.split(':')
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                from datetime import time as _time
                return _time(hour=hour, minute=minute)
            except (ValueError, IndexError):
                return None

        allowed_hour_start = _parse_time(request.POST.get('allowed_hour_start'))
        allowed_hour_end = _parse_time(request.POST.get('allowed_hour_end'))
        timezone_name = (request.POST.get('timezone') or 'UTC').strip()

        if not name:
            error = 'Name is required.'
        elif scope == 'item' and not target_password_id:
            error = 'Target password is required when scope is item.'
        elif scope == 'user' and not target_user_id:
            error = 'Target user is required when scope is user.'
        elif (allowed_hour_start and allowed_hour_end
              and allowed_hour_end <= allowed_hour_start):
            error = 'End time must be after start time.'

        if error is None:
            target_org = (rule.organization if rule else None) or org
            if target_org is None and in_global_view:
                # Pick the password's org if scope=item, else first available
                if scope == 'item' and target_password_id:
                    try:
                        tp = Password.objects.get(pk=target_password_id)
                        target_org = tp.organization
                    except Password.DoesNotExist:
                        error = 'Target password not found.'
            if target_org is None and error is None:
                error = 'No organization context. Pick an org first.'

        if error is None:
            if rule is None:
                rule = VaultAccessRule(
                    organization=target_org,
                    created_by=request.user,
                )
            rule.name = name
            rule.description = description
            rule.is_active = is_active
            rule.priority = priority
            rule.effect = effect
            rule.scope = scope
            rule.target_password_id = (
                int(target_password_id) if target_password_id else None
            )
            rule.target_user_id = (
                int(target_user_id) if target_user_id else None
            )
            rule.allowed_countries = allowed_countries
            rule.blocked_countries = blocked_countries
            rule.allowed_cidrs = allowed_cidrs
            rule.blocked_cidrs = blocked_cidrs
            rule.allowed_weekdays = weekdays
            rule.allowed_hour_start = allowed_hour_start
            rule.allowed_hour_end = allowed_hour_end
            rule.timezone = timezone_name or 'UTC'
            try:
                rule.full_clean()
                rule.save()
                AuditLog.log(
                    user=request.user,
                    action='update' if pk else 'create',
                    organization=rule.organization,
                    object_type='vault.VaultAccessRule',
                    object_id=rule.pk,
                    object_repr=rule.name,
                    description=(
                        f'{"Updated" if pk else "Created"} access rule '
                        f'(scope={rule.scope}, effect={rule.effect})'
                    ),
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                )
                messages.success(
                    request,
                    f'Access rule "{rule.name}" '
                    f'{"updated" if pk else "created"}.',
                )
                return redirect('vault:access_rule_list')
            except Exception as exc:
                error = str(exc)

    # v3.17.522 — click-to-select world map over the country fields. The map
    # writes back into the same inputs, so the POST handling above is unchanged.
    from core.geoip_map import (
        COLOR_ALLOW, COLOR_BLOCK, build_lists, map_background_context,
    )
    from core.models import SystemSetting

    geoip_ctx = map_background_context(SystemSetting.get_settings())
    lists_json = build_lists(
        ('allowed', 'Allowed', COLOR_ALLOW, 'id_allowed_countries',
         rule.allowed_countries if rule else []),
        ('blocked', 'Blocked', COLOR_BLOCK, 'id_blocked_countries',
         rule.blocked_countries if rule else []),
    )

    return render(request, 'vault/access_rule_form.html', {
        'rule': rule,
        'passwords': passwords_qs,
        'users': users_qs,
        'weekdays': WEEKDAYS,
        'common_timezones': COMMON_TIMEZONES,
        'error': error,
        'in_global_view': in_global_view,
        'lists_json': lists_json,
        **geoip_ctx,
    })


@login_required
def access_rule_delete(request, pk):
    """Delete an access rule (with confirmation page)."""
    _require_access_rules_perm(request)
    org = get_request_organization(request)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        rule = get_object_or_404(VaultAccessRule, pk=pk)
    else:
        rule = get_object_or_404(VaultAccessRule, pk=pk, organization=org)

    if request.method == 'POST':
        name = rule.name
        rule_org = rule.organization
        rule.delete()
        AuditLog.log(
            user=request.user,
            action='delete',
            organization=rule_org,
            object_type='vault.VaultAccessRule',
            object_id=pk,
            object_repr=name,
            description=f'Deleted access rule "{name}"',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
        messages.success(request, f'Access rule "{name}" deleted.')
        return redirect('vault:access_rule_list')

    return render(request, 'vault/access_rule_confirm_delete.html', {
        'rule': rule,
    })
