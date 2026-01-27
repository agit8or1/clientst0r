"""
Accounts views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from core.models import Organization
from core.decorators import require_owner
from .models import Membership, UserProfile
from .forms import OrganizationForm, MembershipForm, UserProfileForm, PasswordChangeForm, UserCreateForm, UserEditForm, UserPasswordResetForm


@login_required
def switch_organization(request, org_id):
    """
    Switch the current organization context.
    """
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Staff users can access any organization
    is_staff = hasattr(request.user, 'profile') and request.user.profile.is_staff_user()

    if not is_staff:
        # Verify regular user has membership
        membership = Membership.objects.filter(
            user=request.user,
            organization=org,
            is_active=True
        ).first()

        if not membership:
            messages.error(request, "You don't have access to this organization.")
            return redirect('core:dashboard')

    request.session['current_organization_id'] = org.id
    request.session.modified = True  # Force session save
    messages.success(request, f"Switched to {org.name}")
    return redirect('core:dashboard')


@login_required
def switch_to_global_view(request):
    """
    Switch to global view (clear organization context).
    Superuser only.
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to access global view.")
        return redirect('core:dashboard')

    # Clear organization context
    if 'current_organization_id' in request.session:
        del request.session['current_organization_id']
        request.session.modified = True

    messages.success(request, "Switched to Global View")
    return redirect('core:global_dashboard')


@login_required
def access_management(request):
    """
    Access Management dashboard - consolidated view for orgs, users, members, roles.
    Superuser only.
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to access this page.")
        return redirect('core:dashboard')

    # Get counts
    org_count = Organization.objects.count()
    user_count = User.objects.count()
    member_count = Membership.objects.count()

    # Get recent data
    recent_orgs = Organization.objects.order_by('-created_at')[:5]
    recent_users = User.objects.order_by('-date_joined')[:5]
    recent_members = Membership.objects.select_related('user', 'organization').order_by('-created_at')[:10]

    return render(request, 'accounts/access_management.html', {
        'org_count': org_count,
        'user_count': user_count,
        'member_count': member_count,
        'recent_orgs': recent_orgs,
        'recent_users': recent_users,
        'recent_members': recent_members,
    })


@login_required
def profile(request):
    """
    User profile view showing memberships and personal info.
    """
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    memberships = request.user.memberships.filter(is_active=True).select_related('organization')

    return render(request, 'accounts/profile.html', {
        'profile': profile,
        'memberships': memberships,
    })


@login_required
def profile_edit(request):
    """
    Edit user profile and personal information.
    """
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    return render(request, 'accounts/profile_edit.html', {
        'form': form,
        'profile': profile,
    })


@login_required
def toggle_theme(request):
    """
    Toggle between light and dark theme.
    AJAX endpoint that switches theme and returns JSON response.
    """
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # Define dark themes
    dark_themes = ['dark', 'dracula', 'monokai', 'nord']

    # Toggle theme
    if profile.theme in dark_themes:
        # Switch to light theme (default)
        profile.theme = 'default'
    else:
        # Switch to dark theme
        profile.theme = 'dark'

    profile.save()

    return JsonResponse({'success': True, 'theme': profile.theme})


@login_required
def password_change(request):
    """
    Change user password.
    """
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            try:
                # Save OTP device state before password change
                otp_device_id = request.session.get('_auth_user_otp_device_id')

                user = form.save()

                # CRITICAL: Update session to prevent logout after password change
                update_session_auth_hash(request, user)

                # Restore OTP verification state if it existed
                if otp_device_id:
                    request.session['_auth_user_otp_device_id'] = otp_device_id
                    request.session.modified = True

                messages.success(request, 'Your password was successfully updated!')
                return redirect('accounts:profile')
            except Exception as e:
                messages.error(request, f'Error updating password: {str(e)}')
        else:
            # Form has validation errors - they will be displayed in template
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'accounts/password_change.html', {
        'form': form,
    })


@login_required
def two_factor_setup(request):
    """
    Setup 2FA/TOTP for user account.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # Check for inconsistent state: profile says 2FA enabled but no TOTPDevice
    # This can happen if user enabled 2FA before TOTPDevice integration was added
    has_device = TOTPDevice.objects.filter(user=request.user, confirmed=True).exists()
    if profile.two_factor_enabled and not has_device:
        # Auto-fix: reset profile state to match device state
        profile.two_factor_enabled = False
        profile.save()
        messages.warning(request, '2FA configuration was inconsistent and has been reset. Please enable 2FA again.')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'enable':
            # Generate new TOTP secret
            import pyotp
            secret = pyotp.random_base32()

            # Store in session temporarily
            request.session['totp_secret'] = secret

            # Generate QR code URL
            totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=request.user.email or request.user.username,
                issuer_name='HuduGlue'
            )

            return render(request, 'accounts/two_factor_setup.html', {
                'profile': profile,
                'secret': secret,
                'totp_uri': totp_uri,
                'step': 'verify',
            })

        elif action == 'verify':
            # Verify TOTP code
            secret = request.session.get('totp_secret')
            code = request.POST.get('code')

            if secret and code:
                import pyotp
                import base64
                from django_otp.plugins.otp_totp.models import TOTPDevice

                totp = pyotp.TOTP(secret)

                if totp.verify(code, valid_window=1):
                    # Convert base32 secret to hex (TOTPDevice expects hex-encoded keys)
                    key_bytes = base64.b32decode(secret)
                    hex_key = key_bytes.hex()

                    # Create or update TOTPDevice for django-two-factor-auth
                    device, created = TOTPDevice.objects.get_or_create(
                        user=request.user,
                        name='default',
                        defaults={'key': hex_key, 'confirmed': True}
                    )
                    if not created:
                        # Update existing device
                        device.key = hex_key
                        device.confirmed = True
                        device.save()

                    # Save to profile for compatibility
                    profile.two_factor_enabled = True
                    profile.two_factor_method = 'totp'
                    profile.save()

                    # Clear session
                    del request.session['totp_secret']

                    messages.success(request, '2FA enabled successfully! You will now be prompted for a code when logging in.')
                    return redirect('accounts:profile')
                else:
                    messages.error(request, 'Invalid code. Please try again.')

        elif action == 'disable':
            # Delete TOTPDevice
            from django_otp.plugins.otp_totp.models import TOTPDevice
            TOTPDevice.objects.filter(user=request.user).delete()

            # Update profile
            profile.two_factor_enabled = False
            profile.save()

            messages.success(request, '2FA disabled. You will no longer be prompted for a code when logging in.')
            return redirect('accounts:profile')

    return render(request, 'accounts/two_factor_setup.html', {
        'profile': profile,
        'step': 'initial',
    })


# Organization Management Views (Admin Only)

@login_required
def organization_list(request):
    """
    List all organizations. Shows all orgs for superusers, only owned orgs for others.
    """
    if request.user.is_superuser:
        organizations = Organization.objects.all()
    else:
        # Show organizations where user is an owner
        owned_org_ids = Membership.objects.filter(
            user=request.user,
            role='owner',
            is_active=True
        ).values_list('organization_id', flat=True)
        organizations = Organization.objects.filter(id__in=owned_org_ids)

    return render(request, 'accounts/organization_list.html', {
        'organizations': organizations,
    })


@login_required
def organization_create(request):
    """
    Create new organization. User becomes owner automatically.
    """
    if request.method == 'POST':
        form = OrganizationForm(request.POST)
        if form.is_valid():
            org = form.save()

            # Make creator the owner
            Membership.objects.create(
                user=request.user,
                organization=org,
                role='owner',
                is_active=True
            )

            messages.success(request, f"Organization '{org.name}' created successfully. You are now the owner.")
            return redirect('accounts:organization_detail', org_id=org.id)
    else:
        form = OrganizationForm()

    return render(request, 'accounts/organization_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def organization_detail(request, org_id):
    """
    View organization details and members.
    Only accessible to members of the organization.
    """
    org = get_object_or_404(Organization, id=org_id)

    # Check if user has access
    membership = Membership.objects.filter(
        user=request.user,
        organization=org,
        is_active=True
    ).first()

    if not membership and not request.user.is_superuser:
        messages.error(request, "You don't have access to this organization.")
        return redirect('accounts:organization_list')

    # Get all members
    members = Membership.objects.filter(
        organization=org,
        is_active=True
    ).select_related('user').order_by('role', 'user__username')

    # Get all locations for this organization
    from locations.models import Location
    locations = Location.objects.filter(
        organization=org
    ).order_by('name')

    return render(request, 'accounts/organization_detail.html', {
        'organization': org,
        'members': members,
        'user_membership': membership,
        'locations': locations,
    })


@login_required
@require_owner
def organization_edit(request, org_id):
    """
    Edit organization details. Only owners can edit.
    """
    org = get_object_or_404(Organization, id=org_id)

    if request.method == 'POST':
        form = OrganizationForm(request.POST, instance=org)
        if form.is_valid():
            org = form.save()
            messages.success(request, f"Organization '{org.name}' updated successfully.")
            return redirect('accounts:organization_detail', org_id=org.id)
    else:
        form = OrganizationForm(instance=org)

    return render(request, 'accounts/organization_form.html', {
        'form': form,
        'organization': org,
        'action': 'Edit',
    })


@login_required
@require_owner
def organization_delete(request, org_id):
    """
    Delete organization. Only owners can delete.
    WARNING: This will cascade delete ALL data associated with the organization.
    """
    org = get_object_or_404(Organization, id=org_id)

    if request.method == 'POST':
        org_name = org.name

        # Check if this is the user's current organization
        current_org_id = request.session.get('organization_id')

        # Delete the organization (cascade will handle related data)
        org.delete()

        # Clear session if this was the current org
        if current_org_id == org_id:
            request.session.pop('organization_id', None)

        messages.success(request, f"Organization '{org_name}' and all associated data have been deleted.")
        return redirect('accounts:organization_list')

    # Get counts of data that will be deleted
    from assets.models import Asset
    from docs.models import Document, Diagram
    from vault.models import Password
    from processes.models import Process, ProcessExecution

    data_counts = {
        'members': Membership.objects.filter(organization=org).count(),
        'assets': Asset.objects.filter(organization=org).count(),
        'documents': Document.objects.filter(organization=org).count(),
        'passwords': Password.objects.filter(organization=org).count(),
        'processes': Process.objects.filter(organization=org).count(),
        'process_executions': ProcessExecution.objects.filter(organization=org).count(),
        'diagrams': Diagram.objects.filter(organization=org).count(),
    }

    return render(request, 'accounts/organization_confirm_delete.html', {
        'organization': org,
        'data_counts': data_counts,
    })


@login_required
def member_list(request):
    """
    List all members in the current organization.
    """
    from core.middleware import get_request_organization

    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Get user's membership to check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership:
        messages.error(request, 'You are not a member of this organization.')
        return redirect('accounts:organization_list')

    # Get all members (including suspended)
    members = Membership.objects.filter(
        organization=org
    ).select_related('user', 'role_template').order_by('-created_at')

    return render(request, 'accounts/member_list.html', {
        'current_organization': org,
        'members': members,
        'current_membership': membership,
    })


@login_required
def member_suspend(request, member_id):
    """Suspend a member (set is_active=False)."""
    from core.middleware import get_request_organization

    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_manage_users():
        messages.error(request, 'You do not have permission to suspend members.')
        return redirect('accounts:member_list')

    # Get member to suspend
    member = get_object_or_404(Membership, pk=member_id, organization=org)

    # Cannot suspend yourself
    if member.user == request.user:
        messages.error(request, 'You cannot suspend yourself.')
        return redirect('accounts:member_list')

    # Suspend the member
    member.is_active = False
    member.save()

    messages.success(request, f'User {member.user.username} has been suspended.')
    return redirect('accounts:member_list')


@login_required
def member_reactivate(request, member_id):
    """Reactivate a suspended member (set is_active=True)."""
    from core.middleware import get_request_organization

    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_manage_users():
        messages.error(request, 'You do not have permission to reactivate members.')
        return redirect('accounts:member_list')

    # Get member to reactivate
    member = get_object_or_404(Membership, pk=member_id, organization=org)

    # Reactivate the member
    member.is_active = True
    member.save()

    messages.success(request, f'User {member.user.username} has been reactivated.')
    return redirect('accounts:member_list')


@login_required
@require_owner
def member_add(request, org_id):
    """
    Add member to organization. Only owners can add members.
    """
    org = get_object_or_404(Organization, id=org_id)

    if request.method == 'POST':
        form = MembershipForm(request.POST, organization=org)
        if form.is_valid():
            # Check if adding by email or selecting existing user
            email = form.cleaned_data.get('email')
            user = form.cleaned_data.get('user')

            if email:
                # Try to find user by email
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    messages.error(request, f"No user found with email: {email}")
                    return redirect('accounts:member_add', org_id=org.id)

            if user:
                # Check if already a member
                existing = Membership.objects.filter(
                    user=user,
                    organization=org,
                    is_active=True
                ).exists()

                if existing:
                    messages.warning(request, f"{user.username} is already a member of this organization.")
                else:
                    membership = form.save(commit=False)
                    membership.user = user
                    membership.organization = org
                    membership.is_active = True
                    membership.save()
                    messages.success(request, f"Added {user.username} to {org.name} as {membership.get_role_display()}.")

                return redirect('accounts:organization_detail', org_id=org.id)
            else:
                messages.error(request, "Please select a user or enter an email address.")
    else:
        form = MembershipForm(organization=org)

    return render(request, 'accounts/member_form.html', {
        'form': form,
        'organization': org,
        'action': 'Add',
    })


@login_required
@require_owner
def member_edit(request, org_id, member_id):
    """
    Edit member role. Only owners can edit members.
    """
    org = get_object_or_404(Organization, id=org_id)
    membership = get_object_or_404(Membership, id=member_id, organization=org)

    if request.method == 'POST':
        form = MembershipForm(request.POST, instance=membership, organization=org)
        if form.is_valid():
            membership = form.save()
            messages.success(request, f"Updated {membership.user.username}'s role to {membership.get_role_display()}.")
            return redirect('accounts:organization_detail', org_id=org.id)
    else:
        form = MembershipForm(instance=membership, organization=org)

    return render(request, 'accounts/member_form.html', {
        'form': form,
        'organization': org,
        'membership': membership,
        'action': 'Edit',
    })


@login_required
@require_owner
def member_remove(request, org_id, member_id):
    """
    Remove member from organization. Only owners can remove members.
    """
    org = get_object_or_404(Organization, id=org_id)
    membership = get_object_or_404(Membership, id=member_id, organization=org)

    # Prevent removing the last owner
    if membership.role == 'owner':
        owner_count = Membership.objects.filter(
            organization=org,
            role='owner',
            is_active=True
        ).count()

        if owner_count <= 1:
            messages.error(request, "Cannot remove the last owner. Assign another owner first.")
            return redirect('accounts:organization_detail', org_id=org.id)

    if request.method == 'POST':
        username = membership.user.username
        membership.is_active = False
        membership.save()
        messages.success(request, f"Removed {username} from {org.name}.")
        return redirect('accounts:organization_detail', org_id=org.id)

    return render(request, 'accounts/member_confirm_remove.html', {
        'organization': org,
        'membership': membership,
    })


# User Management Views (Superuser Only)

@login_required
def user_list(request):
    """
    List all users (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to manage users.")
        return redirect('core:dashboard')

    users = User.objects.all().select_related('profile').prefetch_related('memberships')

    return render(request, 'accounts/user_list.html', {
        'users': users,
    })


@login_required
def user_create(request):
    """
    Create new user (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to create users.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create profile
            UserProfile.objects.get_or_create(user=user)
            messages.success(request, f"User '{user.username}' created successfully.")
            return redirect('accounts:user_detail', user_id=user.id)
    else:
        form = UserCreateForm()

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
def user_detail(request, user_id):
    """
    View user details (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to view user details.")
        return redirect('core:dashboard')

    user = get_object_or_404(User, id=user_id)
    profile, created = UserProfile.objects.get_or_create(user=user)
    memberships = user.memberships.filter(is_active=True).select_related('organization')

    return render(request, 'accounts/user_detail.html', {
        'viewed_user': user,
        'profile': profile,
        'memberships': memberships,
    })


@login_required
def user_edit(request, user_id):
    """
    Edit user (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to edit users.")
        return redirect('core:dashboard')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User '{user.username}' updated successfully.")
            return redirect('accounts:user_detail', user_id=user.id)
    else:
        form = UserEditForm(instance=user)

    # Get user's memberships and available organizations
    from .models import RoleTemplate
    memberships = user.memberships.select_related('organization', 'role_template').order_by('-created_at')
    current_org_ids = memberships.values_list('organization_id', flat=True)
    available_organizations = Organization.objects.exclude(id__in=current_org_ids).filter(is_active=True)
    system_role_templates = RoleTemplate.objects.filter(is_system_template=True)

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'action': 'Edit',
        'user_obj': user,
        'memberships': memberships,
        'available_organizations': available_organizations,
        'system_role_templates': system_role_templates,
    })


@login_required
def user_password_reset(request, user_id):
    """
    Reset user password (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to reset passwords.")
        return redirect('core:dashboard')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        form = UserPasswordResetForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password1'])
            user.save()
            messages.success(request, f"Password for user '{user.username}' has been reset.")
            return redirect('accounts:user_detail', user_id=user.id)
    else:
        form = UserPasswordResetForm()

    return render(request, 'accounts/user_password_reset.html', {
        'form': form,
        'user_obj': user,
    })


@login_required
def user_add_membership(request, user_id):
    """
    Add user to an organization (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to add memberships.")
        return redirect('core:dashboard')

    user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        organization_id = request.POST.get('organization_id')
        role = request.POST.get('role')
        role_template_id = request.POST.get('role_template_id')

        if not organization_id or not role:
            messages.error(request, "Organization and role are required.")
            return redirect('accounts:user_edit', user_id=user_id)

        organization = get_object_or_404(Organization, id=organization_id)

        # Check if membership already exists
        existing = Membership.objects.filter(user=user, organization=organization).first()
        if existing:
            if existing.is_active:
                messages.warning(request, f"{user.username} is already a member of {organization.name}.")
            else:
                # Reactivate membership
                existing.is_active = True
                existing.role = role
                if role_template_id:
                    from .models import RoleTemplate
                    existing.role_template = get_object_or_404(RoleTemplate, id=role_template_id)
                else:
                    existing.role_template = None
                existing.save()
                messages.success(request, f"Reactivated {user.username}'s membership in {organization.name}.")
        else:
            # Create new membership
            membership = Membership(
                user=user,
                organization=organization,
                role=role,
                is_active=True
            )
            if role_template_id:
                from .models import RoleTemplate
                membership.role_template = get_object_or_404(RoleTemplate, id=role_template_id)
            membership.save()
            messages.success(request, f"Added {user.username} to {organization.name} as {membership.get_role_display()}.")

    return redirect('accounts:user_edit', user_id=user_id)


@login_required
def user_delete(request, user_id):
    """
    Delete/deactivate user (superuser only).
    """
    if not request.user.is_superuser:
        messages.error(request, "You don't have permission to delete users.")
        return redirect('core:dashboard')

    user = get_object_or_404(User, id=user_id)

    # Prevent deleting yourself
    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('accounts:user_list')

    # Prevent deleting other superusers
    if user.is_superuser:
        messages.error(request, "Cannot delete superuser accounts.")
        return redirect('accounts:user_list')

    if request.method == 'POST':
        username = user.username
        # Deactivate instead of delete to preserve data integrity
        user.is_active = False
        user.save()
        messages.success(request, f"User '{username}' has been deactivated.")
        return redirect('accounts:user_list')

    return render(request, 'accounts/user_confirm_delete.html', {
        'user_obj': user,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def organization_merge(request):
    """
    Merge multiple organizations into one.
    Handles reassignment of all related records.
    """
    from django.db import transaction
    from assets.models import Asset
    from core.models import Organization
    
    if request.method == 'POST':
        # Get selected organizations
        source_org_ids = request.POST.getlist('source_orgs')
        target_org_id = request.POST.get('target_org')
        
        if not source_org_ids or not target_org_id:
            messages.error(request, 'Please select organizations to merge.')
            return redirect('accounts:organization_merge')
        
        if target_org_id in source_org_ids:
            messages.error(request, 'Target organization cannot be in source list.')
            return redirect('accounts:organization_merge')
        
        try:
            target_org = Organization.objects.get(pk=target_org_id)
            source_orgs = Organization.objects.filter(pk__in=source_org_ids)
            
            if not source_orgs.exists():
                messages.error(request, 'No valid source organizations selected.')
                return redirect('accounts:organization_merge')
            
            # Perform merge in transaction
            with transaction.atomic():
                merge_stats = {
                    'assets': 0,
                    'devices': 0,
                    'contacts': 0,
                    'documents': 0,
                    'tickets': 0,
                    'memberships': 0,
                    'rmm_connections': 0,
                    'psa_connections': 0,
                }
                
                for source_org in source_orgs:
                    # Move Assets
                    assets_moved = Asset.objects.filter(organization=source_org).update(organization=target_org)
                    merge_stats['assets'] += assets_moved
                    
                    # Move Devices (from assets app)
                    try:
                        from assets.models import Device
                        devices_moved = Device.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['devices'] += devices_moved
                    except:
                        pass
                    
                    # Move Contacts
                    try:
                        from contacts.models import Contact
                        contacts_moved = Contact.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['contacts'] += contacts_moved
                    except:
                        pass
                    
                    # Move Documents
                    try:
                        from docs.models import Document
                        docs_moved = Document.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['documents'] += docs_moved
                    except:
                        pass
                    
                    # Move Tickets
                    try:
                        from tickets.models import Ticket
                        tickets_moved = Ticket.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['tickets'] += tickets_moved
                    except:
                        pass
                    
                    # Move Memberships
                    from accounts.models import Membership
                    memberships_moved = Membership.objects.filter(organization=source_org).update(organization=target_org)
                    merge_stats['memberships'] += memberships_moved
                    
                    # Move RMM Connections
                    try:
                        from integrations.models import RMMConnection
                        rmm_moved = RMMConnection.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['rmm_connections'] += rmm_moved
                    except:
                        pass
                    
                    # Move PSA Connections
                    try:
                        from integrations.models import PSAConnection
                        psa_moved = PSAConnection.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['psa_connections'] += psa_moved
                    except:
                        pass
                    
                    # Log merge operation
                    AuditLog.objects.create(
                        user=request.user,
                        action='MERGE',
                        resource_type='organization',
                        resource_id=source_org.id,
                        details=f"Merged organization '{source_org.name}' into '{target_org.name}'"
                    )
                    
                    # Delete source organization
                    source_org_name = source_org.name
                    source_org.delete()
                
                # Log target organization update
                AuditLog.objects.create(
                    user=request.user,
                    action='UPDATE',
                    resource_type='organization',
                    resource_id=target_org.id,
                    details=f"Merged {len(source_orgs)} organizations into '{target_org.name}': {merge_stats}"
                )
                
                # Build success message
                stats_msg = []
                for key, count in merge_stats.items():
                    if count > 0:
                        stats_msg.append(f"{count} {key.replace('_', ' ')}")
                
                messages.success(
                    request,
                    f"Successfully merged {len(source_orgs)} organization(s) into '{target_org.name}'. "
                    f"Moved: {', '.join(stats_msg) if stats_msg else 'no records'}."
                )
                
                return redirect('accounts:organization_detail', org_id=target_org.id)
                
        except Organization.DoesNotExist:
            messages.error(request, 'Target organization not found.')
            return redirect('accounts:organization_merge')
        except Exception as e:
            messages.error(request, f'Error merging organizations: {str(e)}')
            logger.error(f"Organization merge error: {str(e)}", exc_info=True)
            return redirect('accounts:organization_merge')
    
    # GET request - show merge form
    from core.models import Organization
    # Show all organizations (active and inactive) to allow merging imported orgs
    organizations = Organization.objects.all().order_by('name')

    return render(request, 'accounts/organization_merge.html', {
        'organizations': organizations,
    })
