"""Settings -> Directory Services -> Group mappings (superuser only, like the
LDAP settings page). See accounts.ldap_mapping for what a mapping does."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from audit.models import AuditLog
from core.models import Organization

from .ldap_mapping import deactivate_for_mapping
from .models import LDAPGroupMapping, RoleTemplate, normalize_group_dn


def _is_superuser(user):
    return user.is_superuser


def _audit(request, action, mapping, description):
    AuditLog.log(
        user=request.user, action=action, organization=mapping.organization,
        object_type='ldap_group_mapping', object_id=mapping.pk,
        object_repr=str(mapping)[:255], description=description,
        ip_address=request.META.get('REMOTE_ADDR'), path=request.path,
        extra_data={'group_dn': mapping.group_dn,
                    'role_template': mapping.role_template.name},
    )


def _allowed_role(org, role_id):
    """A system / global role, or one of `org`'s own custom roles."""
    if not role_id:
        return None
    return RoleTemplate.objects.filter(
        Q(organization__isnull=True) | Q(organization=org), pk=role_id).first()


@login_required
@user_passes_test(_is_superuser)
def mapping_list(request):
    if request.method == 'POST':
        action = request.POST.get('action', 'add')
        if action == 'update':
            mapping = get_object_or_404(LDAPGroupMapping, pk=request.POST.get('pk'))
            role = _allowed_role(mapping.organization, request.POST.get('role_template'))
            if role is None:
                messages.error(request, 'Choose a system role or one of that customer\'s own roles.')
            else:
                old = mapping.role_template.name
                mapping.role_template = role
                mapping.is_active = request.POST.get('is_active') == 'on'
                mapping.save()
                _audit(request, 'update', mapping,
                       f'LDAP group mapping {mapping.group_dn} -> {mapping.organization.name}: '
                       f'role {old} -> {role.name}, {"active" if mapping.is_active else "paused"}')
                messages.success(request, 'Mapping updated. Members pick up the change at their next sign-in.')
            return redirect('accounts:ldap_group_mappings')

        group_dn = (request.POST.get('group_dn') or '').strip()
        org = Organization.objects.filter(pk=request.POST.get('organization') or None,
                                          is_active=True).first()
        role = _allowed_role(org, request.POST.get('role_template')) if org else None
        errors = []
        if not group_dn or '=' not in group_dn:
            errors.append('Enter the group\'s distinguished name, e.g. CN=Acme Users,OU=Groups,DC=example,DC=com.')
        elif len(group_dn) > 500:
            errors.append('Group DN is too long (500 characters at most).')
        if org is None:
            errors.append('Choose a customer.')
        elif role is None:
            errors.append('Choose a system role or one of that customer\'s own roles.')
        if not errors and LDAPGroupMapping.objects.filter(
                organization=org, group_dn_normalized=normalize_group_dn(group_dn)).exists():
            errors.append('That group is already mapped to this customer.')
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            mapping = LDAPGroupMapping.objects.create(
                group_dn=group_dn, organization=org, role_template=role, created_by=request.user)
            _audit(request, 'create', mapping,
                   f'LDAP group mapping added: {group_dn} -> {org.name} as {role.name}')
            messages.success(request, 'Mapping added. Members get the membership at their next sign-in.')
        return redirect('accounts:ldap_group_mappings')

    mappings = LDAPGroupMapping.objects.select_related('organization', 'role_template').order_by(
        'organization__name', 'group_dn')
    return render(request, 'accounts/ldap_group_mappings.html', {
        'mappings': mappings,
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'roles': RoleTemplate.objects.select_related('organization').order_by(
            '-is_system_template', 'organization__name', 'name'),
        'current_tab': 'directory',
    })


@login_required
@user_passes_test(_is_superuser)
@require_POST
def mapping_delete(request, pk):
    mapping = get_object_or_404(LDAPGroupMapping, pk=pk)
    count = deactivate_for_mapping(mapping, request.user)
    _audit(request, 'delete', mapping,
           f'LDAP group mapping removed: {mapping.group_dn} -> {mapping.organization.name} '
           f'({count} membership(s) deactivated)')
    mapping.delete()
    messages.success(request, f'Mapping removed; {count} membership(s) it created were deactivated.')
    return redirect('accounts:ldap_group_mappings')
