"""
Role management views for RBAC
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from core.middleware import get_request_organization
from .models import RoleTemplate, Membership


@login_required
def role_list(request):
    """List all role templates (system and organization custom)."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Check if user has permission to view roles
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_admin():
        messages.error(request, 'You do not have permission to manage roles.')
        return redirect('core:dashboard')

    # Get system templates
    system_templates = RoleTemplate.objects.filter(is_system_template=True)

    # Get organization custom templates
    custom_templates = RoleTemplate.objects.filter(organization=org, is_system_template=False)

    return render(request, 'accounts/roles/role_list.html', {
        'current_organization': org,
        'system_templates': system_templates,
        'custom_templates': custom_templates,
    })


@login_required
def role_create(request):
    """Create a custom role template."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_admin():
        messages.error(request, 'You do not have permission to create roles.')
        return redirect('accounts:role_list')

    if request.method == 'POST':
        # Create role template
        role = RoleTemplate()
        role.name = request.POST.get('name')
        role.description = request.POST.get('description', '')
        role.organization = org
        role.is_system_template = False

        # Vault permissions
        role.vault_view = request.POST.get('vault_view') == 'on'
        role.vault_create = request.POST.get('vault_create') == 'on'
        role.vault_edit = request.POST.get('vault_edit') == 'on'
        role.vault_delete = request.POST.get('vault_delete') == 'on'
        role.vault_export = request.POST.get('vault_export') == 'on'
        role.vault_view_password = request.POST.get('vault_view_password') == 'on'

        # Assets permissions
        role.assets_view = request.POST.get('assets_view') == 'on'
        role.assets_create = request.POST.get('assets_create') == 'on'
        role.assets_edit = request.POST.get('assets_edit') == 'on'
        role.assets_delete = request.POST.get('assets_delete') == 'on'

        # Documents permissions
        role.docs_view = request.POST.get('docs_view') == 'on'
        role.docs_create = request.POST.get('docs_create') == 'on'
        role.docs_edit = request.POST.get('docs_edit') == 'on'
        role.docs_delete = request.POST.get('docs_delete') == 'on'
        role.docs_publish = request.POST.get('docs_publish') == 'on'

        # Files permissions
        role.files_view = request.POST.get('files_view') == 'on'
        role.files_upload = request.POST.get('files_upload') == 'on'
        role.files_delete = request.POST.get('files_delete') == 'on'

        # Monitoring permissions
        role.monitoring_view = request.POST.get('monitoring_view') == 'on'
        role.monitoring_create = request.POST.get('monitoring_create') == 'on'
        role.monitoring_edit = request.POST.get('monitoring_edit') == 'on'
        role.monitoring_delete = request.POST.get('monitoring_delete') == 'on'
        role.monitoring_trigger = request.POST.get('monitoring_trigger') == 'on'

        # Integrations permissions
        role.integrations_view = request.POST.get('integrations_view') == 'on'
        role.integrations_configure = request.POST.get('integrations_configure') == 'on'
        role.integrations_sync = request.POST.get('integrations_sync') == 'on'

        # Audit permissions
        role.audit_view = request.POST.get('audit_view') == 'on'
        role.audit_export = request.POST.get('audit_export') == 'on'

        # Organization permissions
        role.org_view_members = request.POST.get('org_view_members') == 'on'
        role.org_invite_members = request.POST.get('org_invite_members') == 'on'
        role.org_manage_members = request.POST.get('org_manage_members') == 'on'
        role.org_manage_settings = request.POST.get('org_manage_settings') == 'on'

        # API permissions
        role.api_access = request.POST.get('api_access') == 'on'
        role.api_keys_manage = request.POST.get('api_keys_manage') == 'on'

        role.save()

        messages.success(request, f'Role "{role.name}" created successfully.')
        return redirect('accounts:role_list')

    # Get a system template to copy from (optional)
    copy_from_id = request.GET.get('copy_from')
    copy_from = None
    if copy_from_id:
        copy_from = get_object_or_404(RoleTemplate, id=copy_from_id)

    return render(request, 'accounts/roles/role_form.html', {
        'current_organization': org,
        'copy_from': copy_from,
        'is_edit': False,
    })


@login_required
def role_edit(request, pk):
    """Edit a custom role template."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    role = get_object_or_404(RoleTemplate, pk=pk, organization=org)

    # Cannot edit system templates
    if role.is_system_template:
        messages.error(request, 'Cannot edit system role templates.')
        return redirect('accounts:role_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_admin():
        messages.error(request, 'You do not have permission to edit roles.')
        return redirect('accounts:role_list')

    if request.method == 'POST':
        role.name = request.POST.get('name')
        role.description = request.POST.get('description', '')

        # Update all permissions (same as create)
        role.vault_view = request.POST.get('vault_view') == 'on'
        role.vault_create = request.POST.get('vault_create') == 'on'
        role.vault_edit = request.POST.get('vault_edit') == 'on'
        role.vault_delete = request.POST.get('vault_delete') == 'on'
        role.vault_export = request.POST.get('vault_export') == 'on'
        role.vault_view_password = request.POST.get('vault_view_password') == 'on'
        role.assets_view = request.POST.get('assets_view') == 'on'
        role.assets_create = request.POST.get('assets_create') == 'on'
        role.assets_edit = request.POST.get('assets_edit') == 'on'
        role.assets_delete = request.POST.get('assets_delete') == 'on'
        role.docs_view = request.POST.get('docs_view') == 'on'
        role.docs_create = request.POST.get('docs_create') == 'on'
        role.docs_edit = request.POST.get('docs_edit') == 'on'
        role.docs_delete = request.POST.get('docs_delete') == 'on'
        role.docs_publish = request.POST.get('docs_publish') == 'on'
        role.files_view = request.POST.get('files_view') == 'on'
        role.files_upload = request.POST.get('files_upload') == 'on'
        role.files_delete = request.POST.get('files_delete') == 'on'
        role.monitoring_view = request.POST.get('monitoring_view') == 'on'
        role.monitoring_create = request.POST.get('monitoring_create') == 'on'
        role.monitoring_edit = request.POST.get('monitoring_edit') == 'on'
        role.monitoring_delete = request.POST.get('monitoring_delete') == 'on'
        role.monitoring_trigger = request.POST.get('monitoring_trigger') == 'on'
        role.integrations_view = request.POST.get('integrations_view') == 'on'
        role.integrations_configure = request.POST.get('integrations_configure') == 'on'
        role.integrations_sync = request.POST.get('integrations_sync') == 'on'
        role.audit_view = request.POST.get('audit_view') == 'on'
        role.audit_export = request.POST.get('audit_export') == 'on'
        role.org_view_members = request.POST.get('org_view_members') == 'on'
        role.org_invite_members = request.POST.get('org_invite_members') == 'on'
        role.org_manage_members = request.POST.get('org_manage_members') == 'on'
        role.org_manage_settings = request.POST.get('org_manage_settings') == 'on'
        role.api_access = request.POST.get('api_access') == 'on'
        role.api_keys_manage = request.POST.get('api_keys_manage') == 'on'

        role.save()

        messages.success(request, f'Role "{role.name}" updated successfully.')
        return redirect('accounts:role_list')

    return render(request, 'accounts/roles/role_form.html', {
        'current_organization': org,
        'role': role,
        'is_edit': True,
    })


@login_required
def role_delete(request, pk):
    """Delete a custom role template."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    role = get_object_or_404(RoleTemplate, pk=pk, organization=org)

    # Cannot delete system templates
    if role.is_system_template:
        messages.error(request, 'Cannot delete system role templates.')
        return redirect('accounts:role_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_admin():
        messages.error(request, 'You do not have permission to delete roles.')
        return redirect('accounts:role_list')

    if request.method == 'POST':
        # Check if any users are using this role
        users_count = Membership.objects.filter(role_template=role).count()
        if users_count > 0:
            messages.error(request, f'Cannot delete role "{role.name}" - it is assigned to {users_count} user(s). Reassign users first.')
            return redirect('accounts:role_list')

        role_name = role.name
        role.delete()
        messages.success(request, f'Role "{role_name}" deleted successfully.')
        return redirect('accounts:role_list')

    return render(request, 'accounts/roles/role_delete_confirm.html', {
        'current_organization': org,
        'role': role,
    })


@login_required
def member_role_assign(request, user_id):
    """Assign a role template to a user."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    # Check permissions
    membership = request.user.memberships.filter(organization=org, is_active=True).first()
    if not membership or not membership.can_manage_users():
        messages.error(request, 'You do not have permission to assign roles.')
        return redirect('accounts:member_list')

    user = get_object_or_404(User, pk=user_id)
    user_membership = get_object_or_404(Membership, user=user, organization=org)

    if request.method == 'POST':
        role_template_id = request.POST.get('role_template_id')
        if role_template_id:
            role_template = get_object_or_404(RoleTemplate, pk=role_template_id)
            user_membership.role_template = role_template
            user_membership.save()
            messages.success(request, f'Assigned role "{role_template.name}" to {user.username}.')
        else:
            user_membership.role_template = None
            user_membership.save()
            messages.success(request, f'Cleared custom role for {user.username}. Using default role.')
        return redirect('accounts:member_list')

    # Get all available role templates
    system_templates = RoleTemplate.objects.filter(is_system_template=True)
    custom_templates = RoleTemplate.objects.filter(organization=org, is_system_template=False)

    return render(request, 'accounts/roles/member_role_assign.html', {
        'current_organization': org,
        'user': user,
        'user_membership': user_membership,
        'system_templates': system_templates,
        'custom_templates': custom_templates,
    })
