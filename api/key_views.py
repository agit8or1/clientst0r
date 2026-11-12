"""
API Key Management Views - Web UI for creating and managing API keys
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from core.middleware import get_request_organization
from .models import APIKey, APIKeyScope
from accounts.models import Role
from accounts.permission_utils import has_perm_for_org, user_has_org_perm

_RANK = {Role.READONLY: 0, Role.EDITOR: 1, Role.ADMIN: 2, Role.OWNER: 3}


def _active_membership(user, org):
    if org is None:
        return None
    return (user.memberships.filter(organization=org, is_active=True)
            .select_related('role_template').first())


def _can_manage_org_keys(user, org):
    """Manage every key of `org`: the api_keys_manage flag in this customer,
    or a legacy (template-less) Owner/Admin membership, which always could.
    Inactive memberships no longer count."""
    if org is None:
        return False
    if user.is_superuser or user_has_org_perm(user, org, 'api_keys_manage'):
        return True
    m = _active_membership(user, org)
    return bool(m and m.role_template_id is None and m.role in (Role.OWNER, Role.ADMIN))


def _max_key_level(user, org):
    """Highest Permission Level this user may give a key in `org`: their own
    simple role there. MSP staff and superusers pick any level (the key is
    still capped by their live permissions at request time)."""
    from psa.visibility import is_msp_staff
    if is_msp_staff(user):
        return Role.OWNER
    m = _active_membership(user, org)
    return m.role if m else Role.READONLY


@login_required
def apikey_list(request):
    """List all API keys for current user."""
    org = get_request_organization(request)

    # Users can see their own keys + admins can see all org keys
    can_manage_all = _can_manage_org_keys(request.user, org)

    if can_manage_all:
        # Admins see all organization keys
        api_keys = APIKey.objects.filter(organization=org).select_related('user')
    else:
        # Regular users see only their keys
        api_keys = APIKey.objects.filter(organization=org, user=request.user)

    return render(request, 'api/apikey_list.html', {
        'api_keys': api_keys,
        'can_manage_all': can_manage_all,
    })


@login_required
def apikey_create(request):
    """Create new API key."""
    org = get_request_organization(request)
    # The role flag `api_access` decides who may use the API at all (it was
    # stored and editable but never read). Keys belong to one customer.
    if org is None:
        messages.error(request, 'Select a customer before creating an API key.')
        return redirect('api:apikey_list')
    if not has_perm_for_org(request.user, org, 'api_access'):
        messages.error(request, 'Your role does not include API access for this customer.')
        return redirect('api:apikey_list')
    max_level = _max_key_level(request.user, org)

    if request.method == 'POST':
        name = request.POST.get('name')
        role = request.POST.get('role', Role.READONLY)
        scope = request.POST.get('scope', APIKeyScope.SINGLE)

        if not name:
            messages.error(request, 'API key name is required.')
            return redirect('api:apikey_list')

        # Validate role
        if role not in dict(Role.choices).keys():
            role = Role.READONLY
        # No key above the creator's own role in this customer.
        if _RANK.get(role, 0) > _RANK.get(max_level, 0):
            messages.error(request, 'A key cannot have a higher permission level than your own role.')
            return redirect('api:apikey_list')

        # Validate scope (issue #134). The key's effective reach is still
        # bounded at request time by what this user can actually access, so a
        # broad scope never grants access beyond the owner's own permissions.
        if scope not in dict(APIKeyScope.choices).keys():
            scope = APIKeyScope.SINGLE

        # Create API key
        api_key_obj, plaintext_key = APIKey.create_key(
            organization=org,
            user=request.user,
            name=name,
            role=role,
            scope=scope,
        )

        # Show the key once (can't be shown again)
        return render(request, 'api/apikey_created.html', {
            'api_key': api_key_obj,
            'plaintext_key': plaintext_key,
        })

    # GET request - show form
    return render(request, 'api/apikey_create.html', {
        'roles': [(v, l) for v, l in Role.choices if _RANK.get(v, 0) <= _RANK.get(max_level, 0)],
        'scopes': APIKeyScope.choices,
    })


@login_required
def apikey_delete(request, pk):
    """Delete an API key."""
    org = get_request_organization(request)
    api_key = get_object_or_404(APIKey, pk=pk, organization=org)

    # Check permissions - users can delete their own keys, admins can delete any
    is_admin = _can_manage_org_keys(request.user, org)

    if api_key.user != request.user and not is_admin:
        messages.error(request, 'You do not have permission to delete this API key.')
        return redirect('api:apikey_list')

    if request.method == 'POST':
        name = api_key.name
        api_key.delete()
        messages.success(request, f'API key "{name}" has been deleted.')
        return redirect('api:apikey_list')

    return render(request, 'api/apikey_confirm_delete.html', {
        'api_key': api_key,
    })


@login_required
@require_POST
def apikey_toggle(request, pk):
    """Toggle API key active status (AJAX endpoint)."""
    org = get_request_organization(request)
    api_key = get_object_or_404(APIKey, pk=pk, organization=org)

    # Check permissions
    is_admin = _can_manage_org_keys(request.user, org)

    if api_key.user != request.user and not is_admin:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    # Toggle active status
    api_key.is_active = not api_key.is_active
    api_key.save()

    return JsonResponse({
        'success': True,
        'is_active': api_key.is_active
    })
