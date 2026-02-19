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
from .models import Password, PasswordBreachCheck
from .forms import PasswordForm
from .breach_checker import PasswordBreachChecker
from .encryption import EncryptionError

# Initialize logger for this module
logger = logging.getLogger('vault')


@login_required
@ratelimit(key='user', rate='100/h', method='GET', block=False)
def password_list(request):
    """
    List all passwords in current organization, or all passwords if in global view mode.
    Rate limited to 100 requests per hour per user.
    """
    org = get_request_organization(request)

    # Check if user is in global view mode (no org but is superuser/staff)
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False
    in_global_view = not org and (request.user.is_superuser or is_staff)

    if in_global_view:
        # Global view: show all passwords across all organizations
        passwords = Password.objects.all().select_related('organization').prefetch_related('tags')
    else:
        # Organization view: show only passwords for current org
        passwords = Password.objects.for_organization(org).prefetch_related('tags')

    return render(request, 'vault/password_list.html', {
        'passwords': passwords,
        'in_global_view': in_global_view,
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

    return render(request, 'vault/password_detail.html', {
        'password': password,
        'in_global_view': in_global_view,
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
    password = get_object_or_404(Password, pk=pk, organization=org)

    if request.method == 'POST':
        try:
            plaintext = password.get_password()

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


@login_required
def password_test_breach(request, pk):
    """
    AJAX endpoint to test password against breach database.
    Creates a breach check record and returns the results.
    """
    org = get_request_organization(request)
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
                        "<code>cd ~/clientst0r<br>"
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
                password.save()
                form.save_m2m()
                messages.success(request, f"Password '{password.title}' updated successfully.")
                return redirect('vault:password_detail', pk=password.pk)
            except EncryptionError as e:
                # Handle malformed APP_MASTER_KEY error
                error_msg = str(e)
                if 'Invalid APP_MASTER_KEY format' in error_msg or 'base64' in error_msg.lower():
                    messages.error(
                        request,
                        "🔐 Encryption Key Error: Your APP_MASTER_KEY is malformed. "
                        "Please regenerate it using the following commands:<br><br>"
                        "<code>cd ~/clientst0r<br>"
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
        password.delete()
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
