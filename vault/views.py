"""
Vault views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from core.decorators import require_write
from audit.models import AuditLog
from .models import Password
from .forms import PasswordForm


@login_required
def password_list(request):
    """
    List all passwords in current organization.
    """
    org = get_request_organization(request)
    passwords = Password.objects.for_organization(org).prefetch_related('tags')

    return render(request, 'vault/password_list.html', {
        'passwords': passwords,
    })


@login_required
def password_detail(request, pk):
    """
    View password details. Returns decrypted password via separate AJAX endpoint for security.
    """
    org = get_request_organization(request)
    password = get_object_or_404(Password, pk=pk, organization=org)

    return render(request, 'vault/password_detail.html', {
        'password': password,
    })


@login_required
def password_reveal(request, pk):
    """
    AJAX endpoint to reveal decrypted password.
    Logs the reveal action for security audit.
    """
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
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@require_write
def password_create(request):
    """
    Create new password entry.
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        form = PasswordForm(request.POST, organization=org)
        if form.is_valid():
            password = form.save(commit=False)
            password.organization = org
            password.created_by = request.user
            password.last_modified_by = request.user
            password.save()
            form.save_m2m()  # Save tags
            messages.success(request, f"Password '{password.title}' created successfully.")
            return redirect('vault:password_detail', pk=password.pk)
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
            password = form.save(commit=False)
            password.last_modified_by = request.user
            password.save()
            form.save_m2m()
            messages.success(request, f"Password '{password.title}' updated successfully.")
            return redirect('vault:password_detail', pk=password.pk)
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
    strength_data = calculate_password_strength(password)

    return JsonResponse(strength_data)


@login_required
def generate_otp_api(request, pk):
    """
    API endpoint to generate OTP code.
    """
    org = get_request_organization(request)
    password = get_object_or_404(Password, pk=pk, organization=org)

    if password.password_type != 'otp':
        return JsonResponse({'error': 'Not an OTP entry'}, status=400)

    try:
        otp_code = password.generate_otp()
        if otp_code:
            # Calculate time remaining until code changes (30 second window)
            import time
            import pyotp
            totp = pyotp.TOTP(password.get_otp_secret())
            time_remaining = 30 - (int(time.time()) % 30)

            # Log OTP generation for audit
            AuditLog.objects.create(
                organization=org,
                user=request.user,
                username=request.user.username,
                action='read',
                object_type='password',
                object_id=password.id,
                object_repr=password.title,
                description=f"OTP generated for '{password.title}'",
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )
            return JsonResponse({
                'otp': otp_code,
                'time_remaining': time_remaining
            })
        else:
            return JsonResponse({'error': 'OTP secret not configured'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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
    except Exception as e:
        return HttpResponse(f"Error generating QR code: {str(e)}", status=500)


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
