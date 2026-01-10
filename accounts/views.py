"""
Accounts views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
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

    # Verify user has membership
    membership = Membership.objects.filter(
        user=request.user,
        organization=org,
        is_active=True
    ).first()

    if not membership:
        messages.error(request, "You don't have access to this organization.")
        return redirect('home')

    request.session['current_organization_id'] = org.id
    request.session.modified = True  # Force session save
    messages.success(request, f"Switched to {org.name}")
    return redirect('core:dashboard')


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
    profile, created = UserProfile.objects.get_or_create(user=request.user)

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
                totp = pyotp.TOTP(secret)

                if totp.verify(code, valid_window=1):
                    # Save to profile
                    profile.two_factor_enabled = True
                    profile.two_factor_method = 'totp'
                    profile.save()

                    # Clear session
                    del request.session['totp_secret']

                    messages.success(request, '2FA enabled successfully!')
                    return redirect('accounts:profile')
                else:
                    messages.error(request, 'Invalid code. Please try again.')

        elif action == 'disable':
            profile.two_factor_enabled = False
            profile.save()
            messages.success(request, '2FA disabled.')
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

    return render(request, 'accounts/organization_detail.html', {
        'organization': org,
        'members': members,
        'user_membership': membership,
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
        return redirect('home')

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
        return redirect('home')

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
        return redirect('home')

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
        return redirect('home')

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
        return redirect('home')

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
        return redirect('home')

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
        return redirect('home')

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
