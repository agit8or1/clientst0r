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
from django.core.exceptions import ValidationError
from . import key_lifecycle

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

        try:
            expires_at = key_lifecycle.parse_expiry(request.POST.get('expiry'),
                                                    request.POST.get('expiry_date'))
            rate = key_lifecycle.parse_rate(request.POST.get('rate_limit_per_minute'))
            sources = key_lifecycle.parse_sources(request.POST.get('allowed_sources'))
            cert = key_lifecycle.parse_cert(request.POST.get('client_cert_sha256'))
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
            return redirect('api:apikey_create')

        # Create API key
        api_key_obj, plaintext_key = APIKey.create_key(
            organization=org,
            user=request.user,
            name=name,
            role=role,
            scope=scope,
        )
        api_key_obj.expires_at = expires_at
        api_key_obj.rate_limit_per_minute = rate
        api_key_obj.client_cert_sha256 = cert
        api_key_obj.save(update_fields=['expires_at', 'rate_limit_per_minute', 'client_cert_sha256'])
        if sources:
            key_lifecycle.set_sources(api_key_obj, sources, request.user)

        # Show the key once (can't be shown again)
        return render(request, 'api/apikey_created.html', {
            'api_key': api_key_obj,
            'plaintext_key': plaintext_key,
        })

    # GET request - show form
    return render(request, 'api/apikey_create.html', {
        'roles': [(v, l) for v, l in Role.choices if _RANK.get(v, 0) <= _RANK.get(max_level, 0)],
        'scopes': APIKeyScope.choices,
        'expiry_choices': key_lifecycle.EXPIRY_CHOICES,
        'your_ip': _client_ip(request),
        'your_cert': _client_cert(request),
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


def _client_ip(request):
    from core.client_ip import get_client_ip
    return get_client_ip(request) or ''


def _client_cert(request):
    from api_access.mtls import client_certificate
    return client_certificate(request)[0] or ''


def _key_for_change(request, pk):
    """The key, if the user owns it or manages this customer's keys."""
    org = get_request_organization(request)
    api_key = get_object_or_404(APIKey, pk=pk, organization=org)
    if api_key.user != request.user and not _can_manage_org_keys(request.user, org):
        return None
    return api_key


@login_required
def apikey_edit(request, pk):
    """Name, expiry, rate limit and allowed sources. The secret never changes
    here; rotate the key for a new one."""
    api_key = _key_for_change(request, pk)
    if api_key is None:
        messages.error(request, 'You do not have permission to change this API key.')
        return redirect('api:apikey_list')
    sources = key_lifecycle.key_sources(api_key)
    if request.method == 'POST':
        try:
            name = (request.POST.get('name') or '').strip()[:100]
            if not name:
                raise ValidationError('API key name is required.')
            expires_at = key_lifecycle.parse_expiry(request.POST.get('expiry'),
                                                    request.POST.get('expiry_date'), api_key.expires_at)
            rate = key_lifecycle.parse_rate(request.POST.get('rate_limit_per_minute'))
            new_sources = key_lifecycle.parse_sources(request.POST.get('allowed_sources'))
            cert = key_lifecycle.parse_cert(request.POST.get('client_cert_sha256'))
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
            return redirect('api:apikey_edit', pk=api_key.pk)
        if (new_sources != sources and key_lifecycle.source_change_cuts_off(api_key, new_sources)
                and request.POST.get('confirm') != '1'):
            return render(request, 'api/apikey_edit.html', {
                'api_key': api_key, 'sources_text': '\n'.join(new_sources), 'name': name,
                'rate': rate or '', 'expiry_choices': key_lifecycle.EXPIRY_CHOICES,
                'posted_expiry': request.POST.get('expiry', 'keep'),
                'posted_expiry_date': request.POST.get('expiry_date', ''), 'cert': cert,
                'cut_off': True, 'your_ip': _client_ip(request), 'your_cert': _client_cert(request)})
        changed = []
        if name != api_key.name:
            changed.append('name')
        if expires_at != api_key.expires_at:
            changed.append('expiry')
        if rate != api_key.rate_limit_per_minute:
            changed.append('rate limit')
        if cert != api_key.client_cert_sha256:
            changed.append('client certificate')
        api_key.name, api_key.expires_at, api_key.rate_limit_per_minute = name, expires_at, rate
        api_key.client_cert_sha256 = cert
        api_key.save(update_fields=['name', 'expires_at', 'rate_limit_per_minute', 'client_cert_sha256',
                                    'updated_at'])
        if changed:
            from audit.models import AuditLog
            AuditLog.log(user=request.user, action='update', organization=api_key.organization,
                         object_type='APIKey', object_id=api_key.pk, object_repr=str(api_key)[:200],
                         description=f'API key {api_key.key_prefix}… changed: {", ".join(changed)}',
                         extra_data={'expires_at': expires_at.isoformat() if expires_at else None,
                                     'rate_limit_per_minute': rate, 'client_cert_sha256': cert})
        key_lifecycle.set_sources(api_key, new_sources, request.user)
        messages.success(request, f'API key "{api_key.name}" saved.')
        return redirect('api:apikey_list')
    return render(request, 'api/apikey_edit.html', {
        'api_key': api_key, 'sources_text': '\n'.join(sources), 'name': api_key.name,
        'rate': api_key.rate_limit_per_minute or '', 'expiry_choices': key_lifecycle.EXPIRY_CHOICES,
        'posted_expiry': 'keep', 'your_ip': _client_ip(request), 'cert': api_key.client_cert_sha256,
        'your_cert': _client_cert(request)})


@login_required
def apikey_rotate(request, pk):
    """Issue a replacement key. Only the key's owner (or a superuser) may:
    the new secret acts as the owner, so nobody else should receive it."""
    api_key = _key_for_change(request, pk)
    if api_key is None or (api_key.user != request.user and not request.user.is_superuser):
        messages.error(request, 'Only the owner of this API key can rotate it.')
        return redirect('api:apikey_list')
    if not api_key.is_active or api_key.is_expired:
        messages.error(request, 'This key is inactive or expired; create a new key instead.')
        return redirect('api:apikey_list')
    if request.method == 'POST':
        grace = request.POST.get('grace', '24')
        if grace not in dict(key_lifecycle.GRACE_CHOICES):
            grace = '24'
        new_key, plaintext = key_lifecycle.rotate(api_key, request.user, int(grace))
        return render(request, 'api/apikey_created.html', {
            'api_key': new_key, 'plaintext_key': plaintext, 'rotated_from': api_key})
    return render(request, 'api/apikey_rotate.html', {
        'api_key': api_key, 'grace_choices': key_lifecycle.GRACE_CHOICES,
        'sources': key_lifecycle.key_sources(api_key)})
