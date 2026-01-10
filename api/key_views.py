"""
API Key Management Views - Web UI for creating and managing API keys
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from core.middleware import get_request_organization
from .models import APIKey
from accounts.models import Role


@login_required
def apikey_list(request):
    """List all API keys for current user."""
    org = get_request_organization(request)

    # Users can see their own keys + admins can see all org keys
    user_membership = request.user.memberships.filter(organization=org).first()

    if user_membership and user_membership.role in [Role.OWNER, Role.ADMIN]:
        # Admins see all organization keys
        api_keys = APIKey.objects.filter(organization=org).select_related('user')
    else:
        # Regular users see only their keys
        api_keys = APIKey.objects.filter(organization=org, user=request.user)

    return render(request, 'api/apikey_list.html', {
        'api_keys': api_keys,
        'can_manage_all': user_membership and user_membership.role in [Role.OWNER, Role.ADMIN],
    })


@login_required
def apikey_create(request):
    """Create new API key."""
    org = get_request_organization(request)

    if request.method == 'POST':
        name = request.POST.get('name')
        role = request.POST.get('role', Role.READONLY)

        if not name:
            messages.error(request, 'API key name is required.')
            return redirect('api:apikey_list')

        # Validate role
        if role not in dict(Role.choices).keys():
            role = Role.READONLY

        # Create API key
        api_key_obj, plaintext_key = APIKey.create_key(
            organization=org,
            user=request.user,
            name=name,
            role=role
        )

        # Show the key once (can't be shown again)
        return render(request, 'api/apikey_created.html', {
            'api_key': api_key_obj,
            'plaintext_key': plaintext_key,
        })

    # GET request - show form
    return render(request, 'api/apikey_create.html', {
        'roles': Role.choices,
    })


@login_required
def apikey_delete(request, pk):
    """Delete an API key."""
    org = get_request_organization(request)
    api_key = get_object_or_404(APIKey, pk=pk, organization=org)

    # Check permissions - users can delete their own keys, admins can delete any
    user_membership = request.user.memberships.filter(organization=org).first()
    is_admin = user_membership and user_membership.role in [Role.OWNER, Role.ADMIN]

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
def apikey_toggle(request, pk):
    """Toggle API key active status (AJAX endpoint)."""
    org = get_request_organization(request)
    api_key = get_object_or_404(APIKey, pk=pk, organization=org)

    # Check permissions
    user_membership = request.user.memberships.filter(organization=org).first()
    is_admin = user_membership and user_membership.role in [Role.OWNER, Role.ADMIN]

    if api_key.user != request.user and not is_admin:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    # Toggle active status
    api_key.is_active = not api_key.is_active
    api_key.save()

    return JsonResponse({
        'success': True,
        'is_active': api_key.is_active
    })
