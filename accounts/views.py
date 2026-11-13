"""
Accounts views
"""
import logging
import datetime
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
from core.models import Organization, SupportRating
from core.decorators import require_owner
from audit.models import AuditLog
from .models import Membership, UserProfile
from .context_processors import background_is_locked
from .forms import OrganizationForm, MembershipForm, UserProfileForm, PasswordChangeForm, UserCreateForm, UserEditForm, UserPasswordResetForm

logger = logging.getLogger('accounts')


@login_required
def switch_organization(request, org_id):
    """
    Switch the current organization context (stay-on-current-page option).
    """
    org = get_object_or_404(Organization, id=org_id, is_active=True)

    # Superusers and staff users can access any organization
    is_staff = hasattr(request.user, 'profile') and request.user.profile.is_staff_user()

    if is_staff and not request.user.is_superuser:
        from .permission_utils import staff_client_org_ids
        scope = staff_client_org_ids(request.user)
        if scope is not None and org.pk not in scope:
            messages.error(request, "This organization is outside your client scope.")
            return redirect('core:dashboard')
    if not (request.user.is_superuser or is_staff):
        # Verify regular user has membership
        membership = Membership.objects.filter(
            user=request.user,
            organization=org,
            is_active=True
        ).first()

        if not membership:
            messages.error(request, "You don't have access to this organization.")
            return redirect('core:dashboard')

    from core.org_handoff import switch_session_org
    switch_session_org(request, org)
    messages.success(request, f"Switched to {org.name}")

    # An explicit same-site ?next= (e.g. the Integrations page's organization
    # picker) wins over the stay-on-page setting.
    next_url = request.GET.get('next', '')
    if next_url:
        from django.utils.http import url_has_allowed_host_and_scheme
        if (next_url.startswith('/') and not next_url.startswith('//')
                and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})):
            return redirect(next_url)

    # Check if user wants to stay on current page
    from core.models import SystemSetting
    settings = SystemSetting.get_settings()

    if settings.stay_on_page_after_org_switch:
        # Get the referring page (where the user came from)
        referer = request.META.get('HTTP_REFERER', '')
        if referer:
            from django.utils.http import url_has_allowed_host_and_scheme
            from urllib.parse import urlparse
            if url_has_allowed_host_and_scheme(
                url=referer,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                try:
                    path = urlparse(referer).path
                    # Only redirect to same-origin relative paths
                    if path.startswith('/') and not path.startswith('//'):
                        return redirect(path)
                except Exception:
                    pass

    return redirect('core:dashboard')


@login_required
def switch_to_global_view(request):
    """
    Switch to global view (clear organization context).
    Available to superusers and staff users (MSP techs), not tenant users.
    Stay-on-current-page option.
    """
    # Check if user is staff (MSP tech) or superuser
    is_staff = request.is_staff_user if hasattr(request, 'is_staff_user') else False

    if not (request.user.is_superuser or is_staff):
        messages.error(request, "You don't have permission to access global view.")
        return redirect('core:dashboard')
    if not request.user.is_superuser:
        from .permission_utils import staff_client_org_ids
        if staff_client_org_ids(request.user) is not None:
            messages.error(request, "Global View is not available with a limited client scope.")
            return redirect('core:dashboard')

    # Clear organization context and enable global view mode
    if 'current_organization_id' in request.session:
        del request.session['current_organization_id']
    request.session['global_view_mode'] = True
    request.session.modified = True

    messages.success(request, "Switched to Global View")

    # An explicit same-site ?next= (e.g. the Integrations page's organization
    # picker) wins over the stay-on-page setting.
    next_url = request.GET.get('next', '')
    if next_url:
        from django.utils.http import url_has_allowed_host_and_scheme
        if (next_url.startswith('/') and not next_url.startswith('//')
                and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()})):
            return redirect(next_url)

    # Check if user wants to stay on current page
    from core.models import SystemSetting
    settings = SystemSetting.get_settings()

    if settings.stay_on_page_after_org_switch:
        # Get the referring page (where the user came from)
        referer = request.META.get('HTTP_REFERER', '')
        if referer:
            # Extract the path from the referer URL
            from django.urls import resolve
            from urllib.parse import urlparse
            try:
                parsed = urlparse(referer)
                path = parsed.path
                # Try to resolve the URL to make sure it's valid
                resolve(path)
                return redirect(path)
            except Exception:
                # If we can't resolve, fall back to global dashboard
                pass

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
        'mobile_sessions': _active_mobile_sessions(request.user),
    })


def _active_mobile_sessions(user):
    try:
        from api_mobile.models import MobileAuthToken
        return list(MobileAuthToken.active_for(user))
    except Exception:
        return []


@login_required
@require_POST
def mobile_sessions_revoke(request, user_id=None):
    """Sign out every mobile-app session of a user.

    Without `user_id`: the requesting user's own sessions. With it: an
    administrator ending another user's sessions (superuser only — the same
    rule as the rest of the user-management pages).
    """
    from api_mobile.models import MobileAuthToken
    from audit.models import AuditLog

    if user_id is None or user_id == request.user.id:
        target = request.user
        back = redirect('accounts:profile')
    else:
        if not request.user.is_superuser:
            messages.error(request, "You don't have permission to manage this user's sessions.")
            return redirect('core:dashboard')
        target = get_object_or_404(User, id=user_id)
        back = redirect('accounts:user_detail', user_id=target.id)

    n = MobileAuthToken.revoke_all_for(target)
    try:
        AuditLog.log(
            user=request.user, action='update',
            object_type='user', object_id=target.pk, object_repr=target.username,
            description=f'Signed out {n} mobile app session(s) of {target.username}',
            extra_data={'op': 'revoke_all_mobile_sessions', 'revoked': n},
        )
    except Exception:
        pass
    messages.success(request, f'Signed out {n} mobile app session(s).')
    return back


@login_required
def profile_edit(request):
    """
    Edit user profile and personal information.
    """
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # v3.17.527: when an administrator has set a system-wide background policy,
    # the profile's background controls render inside a disabled <fieldset>, and
    # a disabled fieldset submits nothing at all. `background_mode` is a required
    # form field, so left alone that means the user cannot save their profile —
    # not merely that their background gets blanked. Substituting the stored
    # values into the POST fixes both: the form validates, and it writes back
    # exactly what was already there.
    locked = background_is_locked()
    post_data = request.POST
    if locked and request.method == 'POST':
        post_data = request.POST.copy()
        post_data['background_mode'] = profile.background_mode
        post_data['background_color'] = profile.background_color
        post_data['preset_background'] = profile.preset_background

    if request.method == 'POST':
        form = UserProfileForm(post_data, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            # Save normally: this form's save() also writes first_name/last_name/
            # email onto the User, which commit=False would skip.
            form.save()
            messages.success(request, 'Profile updated successfully.')
            if getattr(form, 'email_proposal', None):
                messages.info(request, 'Your new e-mail address takes effect once another administrator '
                                       'approves it. Your current address has been told.')
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=profile, user=request.user)

    from tech_access.services import pending_email_change
    return render(request, 'accounts/profile_edit.html', {
        'form': form,
        'profile': profile,
        'email_protected': form.email_change_protected(),
        'email_pending': pending_email_change(request.user),
        'email_needs_otp': _has_otp_device(request.user),
    })


def _has_otp_device(user):
    # Same devices tech_access.protected.verify_credentials checks.
    from django_otp.plugins.otp_totp.models import TOTPDevice
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


@login_required
def quick_actions_edit(request):
    """
    v3.17.230: customize the dashboard Quick Actions tile set.

    POST keys: `selected[]` (list of action keys, in user-preferred order
    as the JS submits them — drag-to-reorder works in the form).
    """
    from core.quick_actions import QUICK_ACTIONS_REGISTRY, DEFAULT_QUICK_ACTION_KEYS, get_action
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        if 'reset' in request.POST:
            profile.quick_actions_config = []
            profile.save(update_fields=['quick_actions_config'])
            messages.success(request, 'Quick Actions reset to defaults.')
            return redirect('accounts:quick_actions_edit')
        chosen = request.POST.getlist('selected')
        valid = [k for k in chosen if get_action(k)]
        profile.quick_actions_config = valid
        profile.save(update_fields=['quick_actions_config'])
        messages.success(request, f'Saved {len(valid)} Quick Actions.')
        return redirect('accounts:quick_actions_edit')

    saved = profile.quick_actions_config or []
    if not saved:
        saved = list(DEFAULT_QUICK_ACTION_KEYS)
    saved_keys = list(saved)
    saved_set = set(saved_keys)

    selected = []
    for k in saved_keys:
        action = get_action(k)
        if action:
            selected.append({'key': k, 'label': action['label'], 'icon': action['icon']})

    available = []
    for action in QUICK_ACTIONS_REGISTRY:
        if action['key'] not in saved_set:
            available.append({
                'key': action['key'],
                'label': action['label'],
                'icon': action['icon'],
                'tooltip': action.get('tooltip', ''),
            })

    return render(request, 'accounts/quick_actions_edit.html', {
        'selected': selected,
        'available': available,
        'profile': profile,
    })


@login_required
def toggle_theme(request):
    """
    Toggle between light and dark theme.
    AJAX endpoint that switches theme and returns JSON response.

    v3.17.677: a dark palette (Professional Dark, Dark, Dracula, Monokai)
    switches to Default Blue; anything else, Nord included (it is a light
    palette), switches to Professional Dark.
    """
    from django.http import JsonResponse

    from .context_processors import TOGGLE_DARK_THEME, TOGGLE_LIGHT_THEME, is_dark_theme

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    profile.theme = TOGGLE_LIGHT_THEME if is_dark_theme(profile.theme) else TOGGLE_DARK_THEME
    profile.save(update_fields=['theme'])

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


_TOTP_ENROL_AAD = 'accounts.session.totp_secret'


def _pending_totp_secret(request):
    """The not-yet-confirmed TOTP secret from the session, or None."""
    from vault.secret_fields import is_sealed, unseal
    value = request.session.get('totp_secret')
    if not value or not is_sealed(value):
        return None
    try:
        return unseal(value, _TOTP_ENROL_AAD)
    except Exception:
        return None


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

            # Kept in the session until the code is confirmed — encrypted,
            # since sessions live in the database too.
            from vault.secret_fields import seal
            request.session['totp_secret'] = seal(secret, _TOTP_ENROL_AAD)

            # Generate QR code URL
            totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=request.user.email or request.user.username,
                issuer_name='Client St0r'
            )

            return render(request, 'accounts/two_factor_setup.html', {
                'profile': profile,
                'secret': secret,
                'totp_uri': totp_uri,
                'step': 'verify',
            })

        elif action == 'verify':
            # Verify TOTP code
            secret = _pending_totp_secret(request)
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
    Supports filtering by organization_type, sorting, search, view-mode toggle
    (grid/list), and pagination.
    """
    # Superusers see every client, others the clients they own. Shared with
    # the navbar client switcher's "View all clients" link.
    from core.client_switcher import organization_list_queryset
    organizations = organization_list_queryset(request.user)

    # Annotate active member and asset counts once on the queryset (avoids N+1
    # when the list view iterates).  These attributes are used by both grid
    # and list templates.
    organizations = organizations.annotate(
        active_member_count=Count(
            'memberships',
            filter=Q(memberships__is_active=True),
            distinct=True,
        ),
        asset_count=Count('assets', distinct=True),
    )

    # Search by name or slug
    search_query = request.GET.get('q', '').strip()
    if search_query:
        organizations = organizations.filter(
            Q(name__icontains=search_query) | Q(slug__icontains=search_query)
        )

    # Filter by organization type
    type_filter = request.GET.get('type', '')
    if type_filter:
        organizations = organizations.filter(organization_type=type_filter)

    # Sort organizations
    sort_by = request.GET.get('sort', 'name')
    valid_sort_fields = ['name', '-name', 'organization_type', '-organization_type', 'created_at', '-created_at']
    if sort_by in valid_sort_fields:
        organizations = organizations.order_by(sort_by)
    else:
        organizations = organizations.order_by('name')

    # View-mode toggle: grid (default) or list
    view_mode = request.GET.get('view', 'grid')
    if view_mode not in ('grid', 'list'):
        view_mode = 'grid'

    # Pagination — 24 cards in grid mode, 50 rows in list mode
    paginate_by = 50 if view_mode == 'list' else 24
    paginator = Paginator(organizations, paginate_by)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)

    # Pre-build a querystring fragment that callers can paste into hrefs to
    # preserve search/filter/sort/view across pagination links.
    preserved_params = []
    if search_query:
        preserved_params.append(f'q={search_query}')
    if type_filter:
        preserved_params.append(f'type={type_filter}')
    if sort_by and sort_by != 'name':
        preserved_params.append(f'sort={sort_by}')
    if view_mode != 'grid':
        preserved_params.append(f'view={view_mode}')
    preserved_qs = '&'.join(preserved_params)

    return render(request, 'accounts/organization_list.html', {
        'organizations': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'view_mode': view_mode,
        'search_query': search_query,
        'preserved_qs': preserved_qs,
        'org_type_choices': Organization.ORGANIZATION_TYPE_CHOICES[1:],  # Exclude empty choice
    })


@login_required
def organization_create(request):
    """
    Create new organization. User becomes owner automatically.
    Issue #56: Auto-create location option.
    """
    # Customer (portal) users don't create organizations: a new organization
    # with themselves as owner, possibly under another organization's
    # hierarchy, is not theirs to make.
    from .delegation import is_customer_actor
    if is_customer_actor(request.user):
        messages.error(request, "You don't have permission to create organizations.")
        return redirect('core:dashboard')
    if request.method == 'POST':
        form = OrganizationForm(request.POST)
        if form.is_valid():
            parent = form.cleaned_data.get('parent')
            if parent is not None and not request.user.is_superuser:
                from .permission_utils import user_has_org_perm
                if not user_has_org_perm(request.user, parent, 'org_manage_settings'):
                    messages.error(request, 'You need settings rights at the parent organization to create '
                                            'an organization under it.')
                    return redirect('accounts:organization_create')
            org = form.save()

            # Make creator the owner
            Membership.objects.create(
                user=request.user,
                organization=org,
                role='owner',
                is_active=True
            )

            # Issue #56: Auto-create location if requested
            auto_create = form.cleaned_data.get('auto_create_location', False)
            if auto_create and org.street_address and org.city:
                from locations.models import Location
                from locations.services.geocoding import GeocodingService

                location_name = form.cleaned_data.get('location_name') or 'Headquarters'

                location = Location.objects.create(
                    organization=org,
                    name=location_name,
                    location_type='office',
                    street_address=org.street_address,
                    street_address_2=org.street_address_2 or '',
                    city=org.city,
                    state=org.state or '',
                    postal_code=org.postal_code or '',
                    country=org.country,
                    status='active',
                    is_primary=True
                )

                # Auto-geocode the location
                try:
                    geocoder = GeocodingService()
                    result = geocoder.geocode_address(location.full_address)
                    if result:
                        location.latitude = result['latitude']
                        location.longitude = result['longitude']
                        location.save()
                        messages.success(request, f"Organization '{org.name}' created with primary location '{location_name}' (geocoded). You are now the owner.")
                    else:
                        messages.success(request, f"Organization '{org.name}' created with primary location '{location_name}' (geocoding failed - edit location to retry). You are now the owner.")
                except Exception as e:
                    messages.warning(request, f"Organization '{org.name}' created with primary location '{location_name}', but geocoding failed: {e}")
            else:
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

    Open to anyone who may open this customer (core.tenancy.
    accessible_org_ids): superusers, MSP staff — whose reach is every
    customer, with or without a global role or technician access
    assignments — and members of the customer or of a parent customer.
    Until the development branch after v3.17.659 only direct members and
    superusers got in; MSP technicians were bounced to the list, which they
    usually can't see either. Management buttons still follow the
    membership role (or superuser) in the template.
    """
    org = get_object_or_404(Organization, id=org_id)

    # Check if user has access
    membership = Membership.objects.filter(
        user=request.user,
        organization=org,
        is_active=True
    ).first()

    from core.tenancy import accessible_org_ids
    allowed = accessible_org_ids(request)
    if not (allowed is None or org.pk in allowed or membership is not None):
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

    # Support ratings — build a dict keyed by category for easy template access
    ratings_qs = SupportRating.objects.filter(organization=org)
    ratings_by_category = {r.category: r for r in ratings_qs}
    # Ensure all categories present (None if not yet rated)
    all_categories = SupportRating.CATEGORY_CHOICES
    ratings = [(key, label, ratings_by_category.get(key)) for key, label in all_categories]

    SERVICES = [
        {'slug': 'voip',       'label': 'VoIP',       'icon': 'fa-phone'},
        {'slug': 'email',      'label': 'Email',       'icon': 'fa-envelope'},
        {'slug': 'o365',       'label': 'O365',        'icon': 'fa-microsoft'},
        {'slug': 'web',        'label': 'Web',         'icon': 'fa-globe'},
        {'slug': 'firewall',   'label': 'Firewall',    'icon': 'fa-shield-alt'},
        {'slug': 'procedures', 'label': 'Procedures',  'icon': 'fa-clipboard-list'},
    ]

    return render(request, 'accounts/organization_detail.html', {
        'organization': org,
        'members': members,
        'user_membership': membership,
        'locations': locations,
        'support_ratings': ratings,
        'rating_choices': SupportRating.RATING_CHOICES,
        'services': SERVICES,
    })


@login_required
@require_owner
def organization_edit(request, org_id):
    """
    Edit organization details: org_manage_settings at THIS organization
    (the URL's, not the selected one). Moving it under another parent - which
    gives the parent's members sight of this organization - takes a
    superuser or org_manage_settings at the new parent too.
    """
    org = get_object_or_404(Organization, id=org_id)
    from .permission_utils import user_has_org_perm
    from .role_audit import record_delegation_denied, record_denied
    if not user_has_org_perm(request.user, org, 'org_manage_settings'):
        record_denied(request, 'org_manage_settings', organization=org)
        messages.error(request, "You don't have permission to change this organization's settings.")
        return redirect('accounts:organization_detail', org_id=org.id)
    old_parent_id = org.parent_id
    old_active = org.is_active

    if request.method == 'POST':
        form = OrganizationForm(request.POST, instance=org)
        if form.is_valid():
            new_parent = form.cleaned_data.get('parent')
            if (getattr(new_parent, 'pk', None) != old_parent_id and not request.user.is_superuser
                    and (new_parent is not None and not user_has_org_perm(request.user, new_parent,
                                                                          'org_manage_settings')
                         or old_parent_id is not None and not user_has_org_perm(request.user, old_parent_id,
                                                                                'org_manage_settings'))):
                record_delegation_denied(request, 'change organization parent',
                                         'no org_manage_settings at the old or new parent', organization=org)
                messages.error(request, 'Changing the parent organization needs settings rights at both the '
                                        'old and the new parent.')
                return redirect('accounts:organization_edit', org_id=org.id)
            org = form.save()
            if org.parent_id != old_parent_id or org.is_active != old_active:
                from .role_audit import record as audit_record
                audit_record('organization.scope_changed', target_type='organization', target_id=org.pk,
                             target_repr=org.name, organization=org, request=request,
                             before={'parent_id': old_parent_id, 'is_active': old_active},
                             after={'parent_id': org.parent_id, 'is_active': org.is_active})

            # #116: Support auto-creating a location from the edit form too
            auto_create = form.cleaned_data.get('auto_create_location', False)
            if auto_create and org.street_address and org.city:
                from locations.models import Location
                from locations.services.geocoding import GeocodingService

                location_name = form.cleaned_data.get('location_name') or 'Headquarters'

                location = Location.objects.create(
                    organization=org,
                    name=location_name,
                    location_type='office',
                    street_address=org.street_address,
                    street_address_2=org.street_address_2 or '',
                    city=org.city,
                    state=org.state or '',
                    postal_code=org.postal_code or '',
                    country=org.country,
                    status='active',
                    is_primary=True,
                )

                try:
                    geocoder = GeocodingService()
                    result = geocoder.geocode_address(location.full_address)
                    if result:
                        location.latitude = result['latitude']
                        location.longitude = result['longitude']
                        location.save()
                        messages.success(request, f"Organization '{org.name}' updated and location '{location_name}' created (geocoded).")
                    else:
                        messages.success(request, f"Organization '{org.name}' updated and location '{location_name}' created.")
                except Exception as e:
                    messages.warning(request, f"Organization '{org.name}' updated and location '{location_name}' created, but geocoding failed: {e}")
            else:
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
    Delete organization: an owner of THIS organization or a superuser.
    WARNING: This will cascade delete ALL data associated with the organization.
    """
    org = get_object_or_404(Organization, id=org_id)
    own = Membership.objects.filter(user=request.user, organization=org, is_active=True).first()
    if not (request.user.is_superuser or (own is not None and own.is_owner())):
        from .role_audit import record_delegation_denied
        record_delegation_denied(request, 'delete organization', 'not an owner of it', organization=org)
        messages.error(request, 'Only an owner of this organization can delete it.')
        return redirect('accounts:organization_detail', org_id=org.id)

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

    from .permission_utils import user_has_org_perm
    return render(request, 'accounts/member_list.html', {
        'current_organization': org,
        'members': members,
        'current_membership': membership,
        'can_manage_members': user_has_org_perm(request.user, org, 'org_manage_members'),
        'is_owner': membership.is_owner() or request.user.is_superuser,
    })


@login_required
def member_suspend(request, member_id):
    """Suspend a member (set is_active=False)."""
    from core.middleware import get_request_organization

    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    if request.method != 'POST':
        return redirect('accounts:member_list')

    # Get member to suspend
    member = get_object_or_404(Membership, pk=member_id, organization=org)

    # Cannot suspend yourself
    if member.user == request.user:
        messages.error(request, 'You cannot suspend yourself.')
        return redirect('accounts:member_list')

    from .delegation import can_manage_member, check_owner_change
    from .role_audit import record_delegation_denied
    verdict = can_manage_member(request.user, org, member)
    if verdict:
        verdict = check_owner_change(member, deactivate=True)
    if not verdict:
        record_delegation_denied(request, 'suspend member', verdict.reason, organization=org, target=member)
        messages.error(request, verdict.reason)
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

    if request.method != 'POST':
        return redirect('accounts:member_list')

    # Get member to reactivate
    member = get_object_or_404(Membership, pk=member_id, organization=org)

    # Reactivating restores everything the membership holds, so it takes the
    # same authority as assigning that role.
    from .delegation import can_assign_role
    from .role_audit import record_delegation_denied
    verdict = can_assign_role(request.user, org, member.role_template, simple_role=member.role,
                              target_membership=member, additional_roles=list(member.additional_roles.all()))
    if not verdict:
        record_delegation_denied(request, 'reactivate member', verdict.reason, organization=org, target=member)
        messages.error(request, verdict.reason)
        return redirect('accounts:member_list')

    # Reactivate the member
    member.is_active = True
    member.save()

    messages.success(request, f'User {member.user.username} has been reactivated.')
    return redirect('accounts:member_list')


@login_required
def organization_support_rating(request, org_id):
    """
    AJAX endpoint — save a support difficulty rating for one category.
    Accessible to owners, admins, and superusers.
    """
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    org = get_object_or_404(Organization, id=org_id)

    membership = Membership.objects.filter(
        user=request.user, organization=org, is_active=True
    ).first()
    if not membership and not request.user.is_superuser:
        return JsonResponse({'ok': False, 'error': 'Access denied'}, status=403)
    if membership and membership.role not in ('owner', 'admin') and not request.user.is_superuser:
        return JsonResponse({'ok': False, 'error': 'Admins only'}, status=403)

    category = request.POST.get('category', '')
    rating_val = request.POST.get('rating', '')
    notes = request.POST.get('notes', '').strip()

    valid_categories = dict(SupportRating.CATEGORY_CHOICES).keys()
    valid_ratings = {str(r[0]) for r in SupportRating.RATING_CHOICES}

    if category not in valid_categories:
        return JsonResponse({'ok': False, 'error': 'Invalid category'}, status=400)
    if rating_val not in valid_ratings:
        return JsonResponse({'ok': False, 'error': 'Invalid rating'}, status=400)

    obj, _ = SupportRating.objects.update_or_create(
        organization=org,
        category=category,
        defaults={'rating': int(rating_val), 'notes': notes, 'rated_by': request.user},
    )
    return JsonResponse({
        'ok': True,
        'rating': obj.rating,
        'label': obj.get_rating_display(),
        'notes': obj.notes,
    })


@login_required
def organization_service_info(request, org_id, service_slug):
    """
    Service quick-info page — aggregates passwords, documents, and assets
    relevant to a given service category for an organization.
    """
    from django.db.models import Q
    from vault.models import Password
    from docs.models import Document
    from assets.models import Asset

    org = get_object_or_404(Organization, id=org_id)
    membership = Membership.objects.filter(user=request.user, organization=org, is_active=True).first()
    if not membership and not request.user.is_superuser:
        messages.error(request, "You don't have access to this organization.")
        return redirect('accounts:organization_list')

    SERVICE_CONFIG = {
        'voip': {
            'label': 'VoIP / Phone',
            'icon': 'fa-phone',
            'color': 'primary',
            'keywords': ['voip', 'sip', 'phone', 'pbx', '3cx', 'ringcentral', 'teams voice', 'telo'],
            'password_types': ['network_device', 'other'],
        },
        'email': {
            'label': 'Email',
            'icon': 'fa-envelope',
            'color': 'info',
            'keywords': ['email', 'smtp', 'imap', 'pop3', 'mail', 'exchange', 'postfix'],
            'password_types': ['email'],
        },
        'o365': {
            'label': 'O365 / Microsoft',
            'icon': 'fa-microsoft',
            'color': 'warning',
            'keywords': ['o365', 'office365', 'microsoft', 'azure', 'sharepoint', 'teams', 'entra', 'intune'],
            'password_types': ['windows_ad', 'website'],
        },
        'web': {
            'label': 'Web / Hosting',
            'icon': 'fa-globe',
            'color': 'success',
            'keywords': ['web', 'website', 'hosting', 'domain', 'ssl', 'dns', 'wordpress', 'cpanel', 'plesk', 'wix'],
            'password_types': ['website', 'ftp'],
        },
        'firewall': {
            'label': 'Firewall / VPN',
            'icon': 'fa-shield-alt',
            'color': 'danger',
            'keywords': ['firewall', 'vpn', 'router', 'cisco', 'fortinet', 'fortigate', 'sophos', 'palo alto', 'watchguard', 'meraki', 'pfSense'],
            'password_types': ['network_device', 'vpn'],
        },
        'procedures': {
            'label': 'Procedures',
            'icon': 'fa-clipboard-list',
            'color': 'secondary',
            'keywords': ['procedure', 'runbook', 'process', 'sop', 'checklist', 'guide', 'how to', 'howto', 'onboard', 'offboard'],
            'password_types': [],
        },
    }

    if service_slug not in SERVICE_CONFIG:
        messages.error(request, "Unknown service.")
        return redirect('accounts:organization_detail', org_id=org_id)

    cfg = SERVICE_CONFIG[service_slug]
    keywords = cfg['keywords']

    # Build keyword Q for title/name/notes searches
    def kw_q(fields):
        q = Q()
        for kw in keywords:
            for field in fields:
                q |= Q(**{f'{field}__icontains': kw})
        return q

    # Passwords — match by keyword in title/url/notes OR by password_type
    pw_q = kw_q(['title', 'url', 'notes', 'folder__name'])
    if cfg['password_types']:
        pw_q |= Q(password_type__in=cfg['password_types'])
    from vault.permissions import visible_passwords
    passwords = visible_passwords(request.user, Password.objects.filter(organization=org)).filter(pw_q).select_related('folder').order_by('title')

    # Documents — match by keyword in title or tag name
    doc_q = kw_q(['title', 'tags__name', 'category__name'])
    documents = Document.objects.filter(organization=org).filter(doc_q).distinct().order_by('title')

    # Assets — match by keyword in name, notes, asset_type (CharField), tags
    asset_q = kw_q(['name', 'notes', 'asset_type', 'tags__name'])
    assets = Asset.objects.filter(organization=org).filter(asset_q).distinct().order_by('name')

    # Each section only for users whose role grants its view flag here —
    # the same rule the /vault/, /docs/ and /assets/ section gate applies.
    from accounts.permission_utils import has_perm_for_org
    if not has_perm_for_org(request.user, org, 'vault_view'):
        passwords = passwords.none()
    if not has_perm_for_org(request.user, org, 'docs_view'):
        documents = documents.none()
    if not has_perm_for_org(request.user, org, 'assets_view'):
        assets = assets.none()

    SERVICES = [
        {'slug': 'voip',       'label': 'VoIP',       'icon': 'fa-phone'},
        {'slug': 'email',      'label': 'Email',       'icon': 'fa-envelope'},
        {'slug': 'o365',       'label': 'O365',        'icon': 'fa-microsoft'},
        {'slug': 'web',        'label': 'Web',         'icon': 'fa-globe'},
        {'slug': 'firewall',   'label': 'Firewall',    'icon': 'fa-shield-alt'},
        {'slug': 'procedures', 'label': 'Procedures',  'icon': 'fa-clipboard-list'},
    ]

    return render(request, 'accounts/organization_service_info.html', {
        'organization': org,
        'user_membership': membership,
        'service_slug': service_slug,
        'service': cfg,
        'passwords': passwords,
        'documents': documents,
        'assets': assets,
        'services': SERVICES,
    })


def send_member_welcome_email(membership, request=None, *, invited_by=None):
    """
    v3.17.214: Send a short welcome email to a user who was just added
    to an organization. Best-effort — failures are logged, never raised
    (so a transient SMTP outage can't block the membership creation).

    Returns True on send, False on skip / failure. Skips when:
    - the user has no email on file
    - the user is being added to their own / the staff org and is_active=False
      (uninitialized account — portal_invite handles those)
    """
    from django.core.mail import EmailMultiAlternatives
    user = membership.user
    if not user.email:
        return False
    org_name = membership.organization.name
    role_label = membership.get_role_display()
    inviter = invited_by or getattr(membership, 'invited_by', None)
    inviter_line = ''
    if inviter and getattr(inviter, 'username', ''):
        full = (f'{inviter.first_name} {inviter.last_name}').strip() or inviter.username
        inviter_line = f'You were added by {full}.\n\n'
    login_url = ''
    if request is not None:
        try:
            login_url = request.build_absolute_uri('/')
        except Exception:
            login_url = ''
    subject = f'You have been added to {org_name}'
    text = (
        f'Hello{(" " + (user.first_name or user.username))},\n\n'
        f'You now have access to {org_name} as {role_label}.\n\n'
        f'{inviter_line}'
        + (f'Sign in here: {login_url}\n\n' if login_url else '')
        + 'If you did not expect this, please contact your administrator.\n'
    )
    try:
        msg = EmailMultiAlternatives(subject, text, to=[user.email])
        msg.send(fail_silently=False)
        return True
    except Exception as exc:
        logger.warning('member welcome email failed for %s: %s', user.email, exc)
        return False


def _member_admin_or_redirect(request, org, perm='org_manage_members'):
    """The URL's organization decides, not the selected one: a role held at
    one customer never manages another customer's members."""
    from .permission_utils import user_has_org_perm
    if user_has_org_perm(request.user, org, perm):
        return None
    if perm == 'org_manage_members' and user_has_org_perm(request.user, org, 'org_invite_members'):
        return None
    from .role_audit import record_denied
    record_denied(request, perm, organization=org)
    messages.error(request, "You don't have permission to manage members of this organization.")
    return redirect('accounts:organization_detail', org_id=org.id)


@login_required
@require_owner
def member_add(request, org_id):
    """
    Add member to organization: needs org_invite_members (or
    org_manage_members) at this organization, and the role must be within
    the actor's delegation authority (accounts.delegation).
    """
    org = get_object_or_404(Organization, id=org_id)
    denied = _member_admin_or_redirect(request, org)
    if denied:
        return denied

    if request.method == 'POST':
        form = MembershipForm(request.POST, organization=org, actor=request.user)
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
                from .delegation import can_assign_role
                verdict = can_assign_role(request.user, org, form.cleaned_data.get('role_template'),
                                          simple_role=form.cleaned_data.get('role'), target_user=user,
                                          additional_roles=list(form.cleaned_data.get('additional_roles') or []))
                if not verdict:
                    from .role_audit import record_delegation_denied
                    record_delegation_denied(request, 'add member', verdict.reason, organization=org, target=user)
                    messages.error(request, verdict.reason)
                    return redirect('accounts:member_add', org_id=org.id)
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
                    membership.invited_by = request.user
                    membership.save()
                    form.save_m2m()
                    from .role_audit import record as audit_record
                    audit_record('invite.sent', target_type='membership', target_id=membership.pk,
                                 target_repr=f'{user.username} @ {org.name}', organization=org, request=request,
                                 after={'role': membership.role,
                                        'role_template': getattr(membership.role_template, 'name', None)})
                    sent = send_member_welcome_email(membership, request=request,
                                                     invited_by=request.user)
                    msg = f"Added {user.username} to {org.name} as {membership.get_role_display()}."
                    if sent:
                        msg += ' Welcome email sent.'
                    messages.success(request, msg)

                return redirect('accounts:organization_detail', org_id=org.id)
            else:
                messages.error(request, "Please select a user or enter an email address.")
    else:
        form = MembershipForm(organization=org, actor=request.user)

    return render(request, 'accounts/member_form.html', {
        'form': form,
        'organization': org,
        'action': 'Add',
    })


@login_required
@require_owner
def member_edit(request, org_id, member_id):
    """
    Edit a member's roles and scope. Delegation rules (no self-promotion,
    subset of the actor's own permissions, privileged roles need
    org_manage_privileged, last owner kept, ownership only by transfer) are
    enforced by MembershipForm.clean().
    """
    org = get_object_or_404(Organization, id=org_id)
    membership = get_object_or_404(Membership, id=member_id, organization=org)
    from .permission_utils import user_has_org_perm
    if not user_has_org_perm(request.user, org, 'org_manage_members'):
        from .role_audit import record_denied
        record_denied(request, 'org_manage_members', organization=org)
        messages.error(request, "You don't have permission to manage members of this organization.")
        return redirect('accounts:organization_detail', org_id=org.id)

    if request.method == 'POST':
        form = MembershipForm(request.POST, instance=membership, organization=org, actor=request.user)
        if form.is_valid():
            membership = form.save()
            messages.success(request, f"Updated {membership.user.username}'s role to {membership.get_role_display()}.")
            return redirect('accounts:organization_detail', org_id=org.id)
        if form.non_field_errors():
            from .role_audit import record_delegation_denied
            record_delegation_denied(request, 'edit member', '; '.join(form.non_field_errors()),
                                     organization=org, target=membership)
    else:
        form = MembershipForm(instance=membership, organization=org, actor=request.user)

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
    Remove member from organization: org_manage_members at this
    organization, the member's access within the actor's own, never the
    last active owner.
    """
    org = get_object_or_404(Organization, id=org_id)
    membership = get_object_or_404(Membership, id=member_id, organization=org)

    from .delegation import can_manage_member, check_owner_change
    verdict = can_manage_member(request.user, org, membership)
    if verdict:
        verdict = check_owner_change(membership, deactivate=True)
    if not verdict:
        from .role_audit import record_delegation_denied
        record_delegation_denied(request, 'remove member', verdict.reason, organization=org, target=membership)
        messages.error(request, verdict.reason)
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


@login_required
def ownership_transfer(request, org_id):
    """Transfer ownership of an organization (accounts.ownership)."""
    from .delegation import DelegationError
    from .models import RoleTemplate
    from .ownership import transfer_ownership
    org = get_object_or_404(Organization, id=org_id)
    own = Membership.objects.filter(user=request.user, organization=org, is_active=True).first()
    if not (request.user.is_superuser or (own is not None and own.is_owner())):
        messages.error(request, 'Only a current owner can transfer ownership.')
        return redirect('accounts:organization_detail', org_id=org.id)
    members = (Membership.objects.filter(organization=org, is_active=True, user__is_active=True)
               .exclude(user=request.user).select_related('user').order_by('user__username'))
    roles = [r for r in RoleTemplate.objects.filter(Q(organization__isnull=True) | Q(organization=org),
                                                    is_archived=False, org_owner=False).order_by('name')]
    if request.method == 'POST':
        to_user = User.objects.filter(pk=request.POST.get('to_user') or 0).first()
        keep = request.POST.get('previous_owner_role') or ''
        keep_role = RoleTemplate.objects.filter(pk=keep).first() if keep.isdigit() else None
        try:
            transfer_ownership(request.user, org, to_user, password=request.POST.get('password', ''),
                               confirm_name=request.POST.get('confirm_name', ''), previous_owner_role=keep_role,
                               request=request)
        except DelegationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Ownership of {org.name} transferred to {to_user.username}.')
            return redirect('accounts:organization_detail', org_id=org.id)
    return render(request, 'accounts/ownership_transfer.html', {
        'organization': org, 'members': members, 'roles': roles,
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


_TIER_ROLE_PENDING = ('The global role was not changed yet: it gives or takes an RMM tier. Confirm the request '
                      'under Settings → Security → Technician Access; a different administrator then approves it.')
_SUPERUSER_PENDING = ('Superuser was not granted yet. Confirm the request under Admin → Security → '
                      'Superuser Approval; a different administrator then approves it.')


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
            from tech_access.services import propose_superuser_grant, superuser_policy_on
            # With the superuser-grant policy on, the account starts without
            # superuser and a second administrator approves the grant.
            hold = superuser_policy_on() and form.cleaned_data.get('is_superuser')
            if hold:
                form.instance.is_superuser = False
            # A global role with an RMM tier waits for a second administrator
            # (tech_access.services.propose_global_role); the account starts
            # without a global role.
            from tech_access.services import global_role_change_is_protected, propose_global_role
            tier_role = form.cleaned_data.get('global_role_template')
            if not global_role_change_is_protected(None, tier_role):
                tier_role = None
            else:
                form.cleaned_data['global_role_template'] = None
            with transaction.atomic():
                user = form.save()
                # Create profile
                UserProfile.objects.get_or_create(user=user)
                proposal = role_change = None
                if hold:
                    try:
                        proposal = propose_superuser_grant(user, request.user, request=request)
                    except ValueError as exc:
                        transaction.set_rollback(True)
                        form.add_error('is_superuser', str(exc))
                if tier_role is not None and not form.errors:
                    try:
                        role_change = propose_global_role(user, tier_role, request.user, request=request)
                    except ValueError as exc:
                        transaction.set_rollback(True)
                        form.add_error('global_role_template', str(exc))
            if not form.errors:
                messages.success(request, f"User '{user.username}' created successfully.")
                if proposal:
                    messages.warning(request, _SUPERUSER_PENDING)
                if role_change:
                    messages.warning(request, _TIER_ROLE_PENDING)
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
        'mobile_sessions': _active_mobile_sessions(user),
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
        before = User.objects.get(pk=user.pk)
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            from tech_access.services import email_is_protected, propose_email_change
            new_email = (form.cleaned_data.get('email') or '').strip()
            proposal = None
            if (new_email.lower() != (before.email or '').lower()
                    and (email_is_protected(before) or form.cleaned_data.get('is_superuser'))):
                # A protected account's address moves only with a second
                # administrator's approval (tech_access.services).
                try:
                    proposal = propose_email_change(before, new_email, request.user, request=request)
                except ValueError as exc:
                    form.add_error('email', str(exc))
                else:
                    form.instance.email = before.email
            grant = None
            if (not form.errors and not before.is_superuser and form.cleaned_data.get('is_superuser')):
                from tech_access.services import propose_superuser_grant, superuser_policy_on
                if superuser_policy_on():
                    try:
                        grant = propose_superuser_grant(before, request.user, request=request)
                    except ValueError as exc:
                        form.add_error('is_superuser', str(exc))
                    else:
                        form.instance.is_superuser = False
            role_change = None
            if not form.errors:
                from tech_access.services import global_role_change_is_protected, propose_global_role
                old_role = UserProfile.objects.get_or_create(user=before)[0].global_role_template
                new_role = form.cleaned_data.get('global_role_template')
                if global_role_change_is_protected(old_role, new_role):
                    # Giving or taking an RMM tier waits for a second
                    # administrator; the rest of the edit saves now.
                    try:
                        role_change = propose_global_role(before, new_role, request.user, request=request)
                    except ValueError as exc:
                        form.add_error('global_role_template', str(exc))
                    else:
                        form.cleaned_data['global_role_template'] = old_role
            if not form.errors:
                user = form.save()
                messages.success(request, f"User '{user.username}' updated successfully.")
                if grant:
                    messages.warning(request, _SUPERUSER_PENDING)
                if role_change:
                    messages.warning(request, _TIER_ROLE_PENDING)
                if proposal:
                    messages.info(request, 'The new e-mail address needs approval. Confirm it under '
                                           'Settings → Security → Technician Access; a second administrator '
                                           'then approves it.')
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
        if role_template_id:
            from .models import RoleTemplate
            chosen = get_object_or_404(RoleTemplate, id=role_template_id)
            if chosen.organization_id not in (None, organization.pk) or chosen.is_archived:
                messages.error(request, "That role belongs to another organization or is archived.")
                return redirect('accounts:user_edit', user_id=user_id)

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
                existing.invited_by = request.user
                existing.save()
                send_member_welcome_email(existing, request=request, invited_by=request.user)
                messages.success(request, f"Reactivated {user.username}'s membership in {organization.name}.")
        else:
            # Create new membership
            membership = Membership(
                user=user,
                organization=organization,
                role=role,
                is_active=True,
                invited_by=request.user,
            )
            if role_template_id:
                from .models import RoleTemplate
                membership.role_template = get_object_or_404(RoleTemplate, id=role_template_id)
            membership.save()
            send_member_welcome_email(membership, request=request, invited_by=request.user)
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

    from .delegation import last_owner_orgs
    stranded = last_owner_orgs(user)
    if stranded:
        messages.error(request, f"{user.username} is the last active owner of "
                                + ', '.join(o.name for o in stranded[:5])
                                + '. Transfer ownership first.')
        return redirect('accounts:user_detail', user_id=user.id)

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
                    except Exception:
                        pass
                    
                    # Move Contacts
                    try:
                        from contacts.models import Contact
                        contacts_moved = Contact.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['contacts'] += contacts_moved
                    except Exception:
                        pass
                    
                    # Move Documents
                    try:
                        from docs.models import Document
                        docs_moved = Document.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['documents'] += docs_moved
                    except Exception:
                        pass
                    
                    # Move Tickets
                    try:
                        from tickets.models import Ticket
                        tickets_moved = Ticket.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['tickets'] += tickets_moved
                    except Exception:
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
                    except Exception:
                        pass
                    
                    # Move PSA Connections
                    try:
                        from integrations.models import PSAConnection
                        psa_moved = PSAConnection.objects.filter(organization=source_org).update(organization=target_org)
                        merge_stats['psa_connections'] += psa_moved
                    except Exception:
                        pass

                    # Move ExternalObjectMap entries (PSA company mappings)
                    try:
                        from integrations.models import ExternalObjectMap
                        # Update both organization FK and local_id for organization mappings
                        external_maps = ExternalObjectMap.objects.filter(
                            organization=source_org,
                            local_type='organization'
                        )
                        for ext_map in external_maps:
                            ext_map.organization = target_org
                            ext_map.local_id = target_org.id
                            ext_map.save()

                        # Also move any other external object mappings
                        other_maps = ExternalObjectMap.objects.filter(
                            organization=source_org
                        ).exclude(local_type='organization')
                        other_maps.update(organization=target_org)

                        if 'external_mappings' not in merge_stats:
                            merge_stats['external_mappings'] = 0
                        merge_stats['external_mappings'] += external_maps.count() + other_maps.count()
                    except Exception as e:
                        logger.warning(f"Error moving external object maps: {e}")

                    # Log merge operation
                    AuditLog.objects.create(
                        user=request.user,
                        username=request.user.username,
                        action='delete',
                        object_type='organization',
                        object_id=source_org.id,
                        object_repr=source_org.name,
                        description=f"Merged organization '{source_org.name}' into '{target_org.name}'",
                        organization=target_org,
                        ip_address=request.META.get('REMOTE_ADDR'),
                        user_agent=request.META.get('HTTP_USER_AGENT', ''),
                        path=request.path
                    )

                    # Delete source organization
                    source_org_name = source_org.name
                    source_org.delete()

                # Log target organization update
                AuditLog.objects.create(
                    user=request.user,
                    username=request.user.username,
                    action='update',
                    object_type='organization',
                    object_id=target_org.id,
                    object_repr=target_org.name,
                    description=f"Merged {len(source_orgs)} organizations into '{target_org.name}': {merge_stats}",
                    organization=target_org,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    path=request.path
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


def lockout(request):
    """
    Custom account-locked page shown after too many failed login attempts.
    Provides remaining lockout time and auto-redirects once the lockout expires.
    """
    from django.utils import timezone
    from axes.models import AccessAttempt
    from core import security_policy

    cooloff = security_policy.lockout_cooloff()
    cooloff_minutes = int(cooloff.total_seconds() // 60)
    if cooloff_minutes >= 60 and cooloff_minutes % 60 == 0:
        hours = cooloff_minutes // 60
        cooloff_display = f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        cooloff_display = f"{cooloff_minutes} minute{'s' if cooloff_minutes != 1 else ''}"
    failure_limit = security_policy.lockout_failure_limit()
    ip = request.META.get('REMOTE_ADDR')

    unlock_time = None
    time_remaining = None
    unlock_timestamp = None

    attempt = AccessAttempt.objects.filter(ip_address=ip).order_by('-attempt_time').first()
    if attempt:
        unlock_time = attempt.attempt_time + cooloff
        remaining = unlock_time - timezone.now()
        if remaining.total_seconds() > 0:
            total_minutes = int(remaining.total_seconds() / 60)
            if total_minutes >= 60:
                h = total_minutes // 60
                m = total_minutes % 60
                time_remaining = f"{h}h {m}m" if m else f"{h}h"
            else:
                time_remaining = f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
            unlock_timestamp = int(unlock_time.timestamp())

    return render(request, 'axes/lockout.html', {
        'cooloff_minutes': cooloff_minutes,
        'cooloff_display': cooloff_display,
        'failure_limit': failure_limit,
        'time_remaining': time_remaining,
        'unlock_time': unlock_time,
        'unlock_timestamp': unlock_timestamp,
    })


# ---------------------------------------------------------------------------
# Portal user invite — old link. Invitations sent before the portal had its
# own sign-in point here; the page now lives on the portal surface.
# ---------------------------------------------------------------------------

def portal_set_password(request, uidb64, token):
    """Redirect old invitation links to portal_auth:set_password."""
    from django.shortcuts import redirect
    from django.urls import reverse
    from core.portal_surface import portal_absolute_url
    path = reverse('portal_auth:set_password', kwargs={'uidb64': uidb64, 'token': token})
    return redirect(portal_absolute_url(path, request))


# ---------------------------------------------------------------------------
# Staff sign-in
# ---------------------------------------------------------------------------

from django import forms as _forms  # noqa: E402
from django.contrib.auth.forms import AuthenticationForm as _AuthenticationForm  # noqa: E402
from two_factor.forms import (  # noqa: E402
    AuthenticationTokenForm as _AuthenticationTokenForm,
    BackupTokenForm as _BackupTokenForm,
)
from two_factor.views.core import LoginView as _TwoFactorLoginView  # noqa: E402


class StaffAuthenticationForm(_AuthenticationForm):
    """The staff sign-in form. Customer portal accounts (core.portal_surface.
    is_portal_user) are refused and pointed at the portal sign-in."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        from core.portal_surface import is_portal_user, portal_login_url
        if is_portal_user(user):
            raise _forms.ValidationError(
                'This is the staff sign-in. Customer accounts sign in at the '
                'customer portal: %(url)s',
                code='portal_account',
                params={'url': portal_login_url(self.request)},
            )


class StaffLoginView(_TwoFactorLoginView):
    """two_factor's login wizard with StaffAuthenticationForm. Served at
    /account/login/ ahead of two_factor:login (config/urls.py)."""
    form_list = (
        (_TwoFactorLoginView.AUTH_STEP, StaffAuthenticationForm),
        (_TwoFactorLoginView.TOKEN_STEP, _AuthenticationTokenForm),
        (_TwoFactorLoginView.BACKUP_STEP, _BackupTokenForm),
    )

    @classmethod
    def get_prefix(cls, request, *args, **kwargs):
        # Field names stay "login_view-..." as with two_factor's own view.
        return 'login_view'

    def done(self, form_list, **kwargs):
        response = super().done(form_list, **kwargs)
        self.request.session['_auth_surface'] = 'staff'
        return response
