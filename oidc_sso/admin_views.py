"""Administration -> Security -> Single sign-on (OIDC).

Permission: manage_sso_settings (critical; superusers always). Changes that
could widen access need a superuser:
  * changing the issuer / client id / MSP pin of a provider that already has
    linked accounts;
  * mapping a token role to a privileged role (any critical permission);
  * letting SSO manage the staff role of a linked account;
  * pre-linking an account to a superuser.
Every change is audit-logged (sso_config_change, sso_link, sso_unlink);
secret values are never logged or rendered back.
"""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from accounts.models import RoleTemplate
from core.models import Organization

from . import audit, discovery, keys
from .forms import PIN_FIELDS, ProviderForm
from .http import OPError
from .models import OIDCCustomerMapping, OIDCIdentity, OIDCProvider, OIDCRoleMapping
from .permissions import can_manage_sso


def _require_manager(request):
    if not can_manage_sso(request.user):
        from accounts.role_audit import record_denied
        record_denied(request, 'manage_sso_settings')
        raise PermissionDenied("You don't have the 'manage_sso_settings' permission.")


def _config_audit(request, provider, what, **extra):
    audit.log('sso_config_change', request=request, user=request.user, provider=provider,
              change=what, description=f'Single sign-on: {what}' + (f' ({provider.name})' if provider else ''),
              **extra)


@login_required
@require_http_methods(['GET', 'POST'])
def settings_index(request):
    _require_manager(request)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()[:100]
        slug = slugify(request.POST.get('slug') or name)[:50]
        if not name or not slug:
            messages.error(request, 'Enter a name.')
        elif OIDCProvider.objects.filter(slug=slug).exists():
            messages.error(request, 'That short name is already used.')
        else:
            provider = OIDCProvider(name=name, slug=slug, issuer='https://id.example.com/realms/agit8or',
                                    client_id=f'clientst0r-{slug}', updated_by=request.user)
            keys.generate_keypair(provider)
            provider.save()
            _config_audit(request, provider, 'provider created (disabled)')
            messages.success(request, 'Provider created, disabled. Fill in the details, test discovery, then enable.')
            return redirect('oidc_sso:provider_detail', pk=provider.pk)
    providers = OIDCProvider.objects.all()
    return render(request, 'oidc_sso/settings_index.html', {'providers': providers})


def _privileged(role):
    return bool(role is not None and role.is_privileged)


def _detail_context(request, provider, form):
    jwk = keys.public_jwk(provider)
    org_q = Organization.objects.filter(is_active=True).order_by('name')
    return {
        'provider': provider, 'form': form,
        'public_jwk': json.dumps(jwk, indent=2) if jwk else '',
        'redirect_uri': request.build_absolute_uri(reverse('oidc_sso:callback', args=[provider.slug])),
        'backchannel_uri': request.build_absolute_uri(reverse('oidc_sso:backchannel_logout', args=[provider.slug])),
        'jwks_uri': request.build_absolute_uri(reverse('oidc_sso:jwks', args=[provider.slug])),
        'post_logout_uri': request.build_absolute_uri(reverse('two_factor:login')),
        'role_mappings': provider.role_mappings.select_related('role_template'),
        'customer_mappings': provider.customer_mappings.select_related('organization'),
        'identities': provider.identities.select_related('user', 'linked_by'),
        'staff_roles': RoleTemplate.objects.filter(organization__isnull=True, is_archived=False)
                                           .exclude(audience='customer').order_by('name'),
        'customer_roles': RoleTemplate.objects.filter(is_archived=False).select_related('organization')
                                              .order_by('organization__name', 'name'),
        'organizations': org_q,
        'users': get_user_model().objects.filter(is_active=True).order_by('username'),
        'test_result': request.session.pop('oidc_sso_test_result', None),
        'is_superuser': request.user.is_superuser,
    }


@login_required
@require_http_methods(['GET', 'POST'])
def provider_detail(request, pk):
    _require_manager(request)
    provider = get_object_or_404(OIDCProvider, pk=pk)
    form = ProviderForm(instance=provider)
    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        handler = _ACTIONS.get(action)
        if handler is None:
            messages.error(request, 'Unknown action.')
            return redirect('oidc_sso:provider_detail', pk=provider.pk)
        result = handler(request, provider)
        if result is not None and not hasattr(result, 'status_code'):
            form = result  # invalid form: re-render with errors
        else:
            return result or redirect('oidc_sso:provider_detail', pk=provider.pk)
    return render(request, 'oidc_sso/provider_detail.html', _detail_context(request, provider, form))


def _save(request, provider):
    before = {f: getattr(provider, f) for f in ProviderForm.Meta.fields if f != 'client_secret'}
    had_secret = bool(provider.client_secret)
    form = ProviderForm(request.POST, instance=provider)
    if not form.is_valid():
        return form
    pin_changed = [f for f in PIN_FIELDS if form.cleaned_data.get(f) != before.get(f)]
    if pin_changed and provider.identities.exists() and not request.user.is_superuser:
        messages.error(request, 'Changing the issuer, client or MSP pin of a provider with linked accounts '
                                'needs a superuser.')
        return redirect('oidc_sso:provider_detail', pk=provider.pk)
    obj = form.save(commit=False)
    obj.updated_by = request.user
    obj.save()
    discovery.forget(obj)
    changed = sorted(f for f in before if getattr(obj, f) != before[f])
    if 'client_secret' in form.changed_data or (not had_secret and obj.client_secret):
        changed.append('client_secret (value not logged)')
    _config_audit(request, obj, 'provider settings saved', fields=changed,
                  enabled=obj.enabled, pin_changed=pin_changed)
    messages.success(request, 'Saved.')
    return None


def _test(request, provider):
    discovery.forget(provider)
    try:
        meta = discovery.get_metadata(provider, force=True)
        jwks = discovery.get_jwks(provider, force=True)
        result = {'ok': True, 'meta': meta, 'key_count': len(jwks.get('keys', []))}
    except OPError as exc:
        result = {'ok': False, 'error': str(exc)}
    request.session['oidc_sso_test_result'] = result
    _config_audit(request, provider, 'discovery tested', ok=result['ok'])
    return None


def _regenerate_key(request, provider):
    keys.generate_keypair(provider)
    provider.updated_by = request.user
    provider.save()
    _config_audit(request, provider, 'client key pair regenerated', key_id=provider.key_id)
    messages.warning(request, 'New key pair generated. Register the new public key at the OP, or sign-in '
                              'will fail.')
    return None


def _add_role_mapping(request, provider):
    target = request.POST.get('target')
    role_key = (request.POST.get('role_key') or '').strip()[:100]
    if target not in dict(OIDCRoleMapping.TARGET_CHOICES) or not role_key or ':' in role_key:
        messages.error(request, 'Enter a role key (without ":") and a target.')
        return None
    q = Q(is_archived=False)
    if target == OIDCRoleMapping.TARGET_STAFF:
        q &= Q(organization__isnull=True) & ~Q(audience='customer')
    role = RoleTemplate.objects.filter(q, pk=request.POST.get('role_template') or 0).first()
    if role is None:
        messages.error(request, 'Choose a role (staff mappings need a global, non-customer role).')
        return None
    if _privileged(role) and not request.user.is_superuser:
        messages.error(request, f'"{role.name}" is a privileged role: only a superuser can map it.')
        return None
    scope = request.POST.get('client_scope') or 'all'
    if scope not in dict(OIDCRoleMapping.SCOPE_CHOICES):
        scope = 'all'
    try:
        priority = max(0, min(10000, int(request.POST.get('priority') or 100)))
    except ValueError:
        priority = 100
    try:
        m = OIDCRoleMapping.objects.create(provider=provider, role_key=role_key, target=target,
                                           role_template=role, client_scope=scope, priority=priority)
    except IntegrityError:
        messages.error(request, 'That role key is already mapped for this target.')
        return None
    _config_audit(request, provider, 'role mapping added', role_key=role_key, target=target,
                  role=role.name, client_scope=scope, mapping_id=m.pk)
    return None


def _delete_role_mapping(request, provider):
    m = OIDCRoleMapping.objects.filter(provider=provider, pk=request.POST.get('mapping_id') or 0).first()
    if m is not None:
        _config_audit(request, provider, 'role mapping deleted', role_key=m.role_key, target=m.target,
                      role=m.role_template.name)
        m.delete()
        messages.success(request, 'Mapping deleted. Members lose it at their next sign-in.')
    return None


def _add_customer_mapping(request, provider):
    key = (request.POST.get('customer_key') or '').strip()[:100]
    org = Organization.objects.filter(is_active=True, pk=request.POST.get('organization') or 0).first()
    if not key or ':' in key or org is None:
        messages.error(request, 'Enter a customer key (without ":") and a customer.')
        return None
    try:
        OIDCCustomerMapping.objects.create(provider=provider, customer_key=key, organization=org)
    except IntegrityError:
        messages.error(request, 'That key or customer is already mapped.')
        return None
    _config_audit(request, provider, 'customer mapping added', customer_key=key, organization_id=org.pk)
    return None


def _delete_customer_mapping(request, provider):
    m = OIDCCustomerMapping.objects.filter(provider=provider, pk=request.POST.get('mapping_id') or 0).first()
    if m is not None:
        _config_audit(request, provider, 'customer mapping deleted', customer_key=m.customer_key,
                      organization_id=m.organization_id)
        m.delete()
    return None


def _prelink(request, provider):
    User = get_user_model()
    user = User.objects.filter(is_active=True, pk=request.POST.get('user') or 0).first()
    sub = (request.POST.get('sub') or '').strip()[:255]
    if user is None or not sub:
        messages.error(request, 'Choose a user and enter their subject (sub) from the OP.')
        return None
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Only a superuser can pre-link a superuser account.')
        return None
    try:
        OIDCIdentity.objects.create(provider=provider, issuer=provider.issuer_normalized, sub=sub, user=user,
                                    manages_staff_role=False, linked_by=request.user)
    except IntegrityError:
        messages.error(request, 'That subject is already linked, or the user already has a linked account.')
        return None
    audit.log('sso_link', request=request, user=request.user, provider=provider, how='admin_prelink',
              target_user=user.username, target_user_id=user.pk,
              description=f'{request.user.username} pre-linked {user.username} to {provider.name}')
    messages.success(request, f'{user.username} pre-linked. It takes effect at their first sign-in.')
    return None


def _unlink(request, provider):
    identity = OIDCIdentity.objects.filter(provider=provider, pk=request.POST.get('identity_id') or 0) \
        .select_related('user').first()
    if identity is not None:
        username = identity.user.username
        identity.delete()
        audit.log('sso_unlink', request=request, user=request.user, provider=provider, how='admin',
                  target_user=username, description=f'{request.user.username} unlinked {username} from {provider.name}')
        messages.success(request, f'{username} unlinked.')
    return None


def _toggle_managed(request, provider):
    if not request.user.is_superuser:
        messages.error(request, 'Only a superuser can hand an account\'s staff role to SSO.')
        return None
    identity = OIDCIdentity.objects.filter(provider=provider, pk=request.POST.get('identity_id') or 0).first()
    if identity is not None:
        identity.manages_staff_role = not identity.manages_staff_role
        identity.save(update_fields=['manages_staff_role'])
        _config_audit(request, provider, 'SSO-managed staff role ' + ('on' if identity.manages_staff_role else 'off'),
                      target_user_id=identity.user_id)
    return None


def _delete_provider(request, provider):
    if not request.user.is_superuser:
        messages.error(request, 'Only a superuser can delete a provider.')
        return None
    _config_audit(request, provider, 'provider deleted')
    discovery.forget(provider)
    provider.delete()
    messages.success(request, 'Provider deleted. Linked accounts sign in the usual way.')
    return redirect('oidc_sso:settings')


_ACTIONS = {
    'save': _save, 'test': _test, 'regenerate_key': _regenerate_key,
    'add_role_mapping': _add_role_mapping, 'delete_role_mapping': _delete_role_mapping,
    'add_customer_mapping': _add_customer_mapping, 'delete_customer_mapping': _delete_customer_mapping,
    'prelink': _prelink, 'unlink': _unlink, 'toggle_managed': _toggle_managed, 'delete': _delete_provider,
}
