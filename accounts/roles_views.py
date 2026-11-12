"""
Role management (Access Management -> Roles).

Pages (all server-side checked; menus only mirror these checks):

  role_list         built-in and custom roles, badges (built-in / customized /
                    archived / privileged / audience), users per role, unused
                    roles and unassigned permissions
  role_detail       permissions by module, users affected
  role_create/edit  permissions grouped by module with search; Preview shows
                    exactly what changes and who is affected before saving
  role_clone        copy any visible role into a custom role of this org
  role_archive      archive / restore (archived roles can't be newly assigned)
  role_delete       only unused custom roles
  role_compare      two roles side by side
  access_explain    "why does X have access": the role and scope responsible
  permission_catalog the registry, technician-access and RMM catalogs and
                    the built-in role matrix
  review_list       assignments flagged by the roles migration (superuser)
  portal_access     customer portal access of this organization
  member_role_assign primary role, additional roles and record scope

Who may do what:
  * a custom role of an organization is managed by holders of `roles_manage`
    there (superusers everywhere); built-in roles are edited by superusers
    only, which marks them customized (the seeder then leaves them alone);
  * a role editor may only put into a role permissions they hold themselves
    at that organization, never edits a role they hold themselves, and a
    customer-side editor may only use customer-assignable permissions;
  * assignments go through accounts.delegation.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.middleware import get_request_organization

from . import permission_registry as registry
from .models import Membership, RoleReviewItem, RoleTemplate, UserProfile
from .permission_utils import effective_permissions, explain_access, user_has_org_perm


# --- access helpers ------------------------------------------------------------------

def _org_or_redirect(request):
    org = get_request_organization(request)
    if org is None:
        messages.error(request, 'No organization selected.')
    return org


def _can_manage_roles(user, org):
    return bool(user.is_superuser or (org is not None and user_has_org_perm(user, org, 'roles_manage')))


def _can_view_roles(user, org):
    return bool(_can_manage_roles(user, org) or (org is not None and (
        user_has_org_perm(user, org, 'org_manage_members') or user_has_org_perm(user, org, 'org_invite_members'))))


def _visible_roles(org):
    return RoleTemplate.objects.filter(Q(organization__isnull=True) | Q(organization=org))


def _deny(request, perm, org, message='You do not have permission to manage roles.'):
    from .role_audit import record_denied
    record_denied(request, perm, organization=org)
    messages.error(request, message)
    return redirect('core:dashboard')


def _role_users(role):
    """Who a role affects: memberships (primary or additional) and staff global roles."""
    primary = list(Membership.objects.filter(role_template=role).select_related('user', 'organization'))
    additional = list(Membership.objects.filter(additional_roles=role).select_related('user', 'organization'))
    staff = list(UserProfile.objects.filter(global_role_template=role).select_related('user'))
    return primary, additional, staff


def _usage_counts():
    counts = {}
    for row in Membership.objects.filter(role_template__isnull=False).values('role_template').annotate(n=Count('id')):
        counts[row['role_template']] = counts.get(row['role_template'], 0) + row['n']
    for row in Membership.additional_roles.through.objects.values('roletemplate').annotate(n=Count('id')):
        counts[row['roletemplate']] = counts.get(row['roletemplate'], 0) + row['n']
    for row in UserProfile.objects.filter(global_role_template__isnull=False).values(
            'global_role_template').annotate(n=Count('id')):
        counts[row['global_role_template']] = counts.get(row['global_role_template'], 0) + row['n']
    return counts


def _module_groups(values=None, editable_keys=None):
    """[(module_key, label, desc, [(perm, checked, editable)])] for templates."""
    out = []
    for mkey, label, desc, perms in registry.by_module():
        rows = []
        for p in perms:
            checked = bool(values.get(p.key)) if values is not None else False
            editable = editable_keys is None or p.key in editable_keys or checked
            rows.append((p, checked, editable))
        out.append((mkey, label, desc, rows))
    return out


def _editable_keys(user, org, customer_only=False):
    """Permissions `user` may put into a role at `org`."""
    if user.is_superuser:
        keys = set(registry.ALL_KEYS)
    else:
        eff = effective_permissions(user, org)
        keys = {k for k, v in eff.items() if v}
    keys -= set(registry.TRANSFER_ONLY_KEYS) if not user.is_superuser else set()
    if customer_only:
        keys &= set(registry.CUSTOMER_ASSIGNABLE_KEYS)
    return keys


def _posted_values(request):
    return {k: request.POST.get(k) == 'on' for k in registry.ALL_KEYS}


def _validate_role_values(request, org, role, values, audience):
    """Errors for a role save by request.user. `role` is None on create."""
    user = request.user
    errors = []
    from .delegation import is_customer_actor
    customer = is_customer_actor(user) or audience == 'customer'
    allowed = _editable_keys(user, org, customer_only=customer)
    before = registry.granted_keys(role) if role is not None else frozenset()
    added = {k for k, v in values.items() if v} - set(before)
    beyond = sorted(added - allowed)
    if beyond:
        errors.append('You can only add permissions you hold yourself here'
                      + (' and that customer roles may hold' if customer else '') + ': '
                      + ', '.join(beyond[:8]) + ('...' if len(beyond) > 8 else ''))
    if values.get('org_owner') and not before.__contains__('org_owner') and not user.is_superuser:
        errors.append('Ownership is not a permission to hand out; use Transfer ownership.')
    if not user.is_superuser:
        if role is not None and role.org_owner:
            errors.append('Owner roles are protected: only a superuser changes them.')
        after_keys = {k for k, v in values.items() if v}
        if ((set(before) | after_keys) & registry.PRIVILEGED_KEYS
                and not user_has_org_perm(user, org, 'org_manage_privileged')):
            errors.append("Roles with administration permissions need 'org_manage_privileged' to change.")
    if role is not None and not user.is_superuser:
        mine = Membership.objects.filter(user=user, is_active=True).filter(
            Q(role_template=role) | Q(additional_roles=role)).exists()
        profile = getattr(user, 'profile', None)
        if mine or (profile is not None and profile.global_role_template_id == role.pk):
            errors.append('You can not change a role you hold yourself.')
    return errors


# --- list / detail ----------------------------------------------------------------------

@login_required
def role_list(request):
    """List all role templates (built-in and this organization's custom ones)."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'roles_manage', org)

    show_archived = request.GET.get('archived') == '1'
    roles = _visible_roles(org).select_related('organization')
    if not show_archived:
        roles = roles.filter(is_archived=False)
    usage = _usage_counts()
    rows = []
    granted_anywhere = set()
    for r in roles.order_by('organization_id', 'name'):
        n = usage.get(r.pk, 0)
        if n:
            granted_anywhere |= set(registry.granted_keys(r))
        rows.append({'role': r, 'users': n, 'customized': r.is_customized, 'privileged': r.is_privileged})
    # Legacy simple roles in use count as granting their flags too.
    for simple in Membership.objects.filter(role_template__isnull=True, is_active=True).values_list(
            'role', flat=True).distinct():
        granted_anywhere |= set(registry.granted_keys(Membership(role=simple)._primary_permissions()))
    unassigned = [p for p in registry.PERMISSIONS if p.key not in granted_anywhere]

    return render(request, 'accounts/roles/role_list.html', {
        'current_organization': org,
        'builtin_rows': [r for r in rows if r['role'].organization_id is None],
        'custom_rows': [r for r in rows if r['role'].organization_id is not None],
        'unused_rows': [r for r in rows if r['users'] == 0],
        'unassigned_permissions': unassigned,
        'can_manage': _can_manage_roles(request.user, org),
        'show_archived': show_archived,
        'open_reviews': RoleReviewItem.objects.filter(status='open').count() if request.user.is_superuser else 0,
    })


@login_required
def role_detail(request, pk):
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    role = get_object_or_404(_visible_roles(org), pk=pk)
    primary, additional, staff = _role_users(role)
    if not request.user.is_superuser:
        # An organization's administrator sees the members of their own organization only.
        primary = [m for m in primary if m.organization_id == org.pk]
        additional = [m for m in additional if m.organization_id == org.pk]
        staff = []
    return render(request, 'accounts/roles/role_detail.html', {
        'current_organization': org, 'role': role,
        'groups': _module_groups(registry.flags_of(role)),
        'granted_count': len(registry.granted_keys(role)),
        'primary': primary, 'additional': additional, 'staff': staff,
        'can_manage': _can_manage_roles(request.user, org) and (
            role.organization_id == org.pk or request.user.is_superuser),
        'non_customer': registry.non_customer_keys(role) if role.audience == 'customer' else [],
    })


# --- create / edit with preview ------------------------------------------------------------

def _render_form(request, org, role, values, *, copy_from=None, preview=None, errors=None, name='',
                 description='', audience='any'):
    from .delegation import is_customer_actor
    customer = is_customer_actor(request.user) or audience == 'customer'
    editable = _editable_keys(request.user, org, customer_only=customer)
    return render(request, 'accounts/roles/role_form.html', {
        'current_organization': org, 'role': role, 'copy_from': copy_from, 'is_edit': role is not None,
        'groups': _module_groups(values, editable), 'preview': preview, 'errors': errors or [],
        'name': name, 'description': description, 'audience': audience,
        'audience_choices': RoleTemplate.AUDIENCE_CHOICES,
    })


def _preview(role, values, org, user):
    before = registry.granted_keys(role) if role is not None else frozenset()
    after = frozenset(k for k, v in values.items() if v)
    added = [registry.get(k) for k in sorted(after - before)]
    removed = [registry.get(k) for k in sorted(before - after)]
    affected = []
    if role is not None:
        primary, additional, staff = _role_users(role)
        for m in primary + additional:
            if user.is_superuser or m.organization_id == org.pk:
                affected.append(f'{m.user.username} @ {m.organization.name}')
        if user.is_superuser:
            affected += [f'{p.user.username} (global role)' for p in staff]
    return {'added': added, 'removed': removed, 'affected': affected,
            'privileged_added': [p for p in added if p.privileged],
            'sensitive_added': [p for p in added if p.key in registry.SENSITIVE_KEYS and not p.privileged],
            'unchanged': not added and not removed}


@login_required
def role_create(request):
    """Create a custom role template of the selected organization."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_manage_roles(request.user, org):
        return _deny(request, 'roles_manage', org, 'You do not have permission to create roles.')

    if request.method == 'POST':
        values = _posted_values(request)
        name = (request.POST.get('name') or '').strip()
        description = request.POST.get('description', '')
        audience = request.POST.get('audience') or 'any'
        if audience not in dict(RoleTemplate.AUDIENCE_CHOICES):
            audience = 'any'
        errors = _validate_role_values(request, org, None, values, audience)
        if not name:
            errors.append('A name is required.')
        elif RoleTemplate.objects.filter(name=name, organization=org).exists():
            errors.append('A role with this name already exists here.')
        if errors or request.POST.get('action') != 'save':
            if errors:
                from .role_audit import record_delegation_denied
                record_delegation_denied(request, 'create role', '; '.join(errors), organization=org)
            return _render_form(request, org, None, values, errors=errors, name=name, description=description,
                                audience=audience, preview=None if errors else _preview(None, values, org,
                                                                                         request.user))
        role = RoleTemplate(name=name, description=description, organization=org, is_system_template=False,
                            audience=audience)
        cloned = request.POST.get('cloned_from')
        if cloned and cloned.isdigit():
            role.cloned_from = _visible_roles(org).filter(pk=cloned).first()
        for k, v in values.items():
            setattr(role, k, v)
        role.save()
        messages.success(request, f'Role "{role.name}" created successfully.')
        return redirect('accounts:role_detail', pk=role.pk)

    copy_from = None
    values = None
    copy_from_id = request.GET.get('copy_from')
    if copy_from_id:
        copy_from = get_object_or_404(_visible_roles(org), id=copy_from_id)
        values = registry.flags_of(copy_from)
    return _render_form(request, org, None, values or {}, copy_from=copy_from,
                        name=f'{copy_from.name} (Copy)' if copy_from else '',
                        description=copy_from.description if copy_from else '',
                        audience=copy_from.audience if copy_from else 'any')


@login_required
def role_edit(request, pk):
    """Edit a role. Custom roles: roles_manage at their organization.
    Built-in roles: superusers only (the role becomes customized)."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    role = get_object_or_404(_visible_roles(org), pk=pk)
    if role.organization_id is None and not request.user.is_superuser:
        messages.error(request, 'Built-in roles are changed by a superuser only. Clone it to customize.')
        return redirect('accounts:role_detail', pk=role.pk)
    if not _can_manage_roles(request.user, org):
        return _deny(request, 'roles_manage', org, 'You do not have permission to edit roles.')

    if request.method == 'POST':
        values = _posted_values(request)
        name = (request.POST.get('name') or '').strip() or role.name
        description = request.POST.get('description', '')
        audience = request.POST.get('audience') or role.audience
        if audience not in dict(RoleTemplate.AUDIENCE_CHOICES):
            audience = role.audience
        errors = _validate_role_values(request, org, role, values, audience)
        if name != role.name and RoleTemplate.objects.filter(name=name, organization=role.organization).exclude(
                pk=role.pk).exists():
            errors.append('A role with this name already exists here.')
        if registry.has_platform_tier(role) and not request.user.is_superuser:
            errors.append('Roles with an RMM tier are changed by a superuser only.')
        if errors or request.POST.get('action') != 'save':
            if errors:
                from .role_audit import record_delegation_denied
                record_delegation_denied(request, 'edit role', '; '.join(errors), organization=org, target=role)
            return _render_form(request, org, role, values, errors=errors, name=name, description=description,
                                audience=audience,
                                preview=None if errors else _preview(role, values, org, request.user))
        role.name = name
        role.description = description
        role.audience = audience
        for k, v in values.items():
            setattr(role, k, v)
        role.save()
        messages.success(request, f'Role "{role.name}" updated successfully.')
        return redirect('accounts:role_detail', pk=role.pk)

    return _render_form(request, org, role, registry.flags_of(role), name=role.name,
                        description=role.description, audience=role.audience)


@login_required
@require_POST
def role_clone(request, pk):
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_manage_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    source = get_object_or_404(_visible_roles(org), pk=pk)
    values = registry.flags_of(source)
    errors = _validate_role_values(request, org, None, values, source.audience)
    if errors:
        from .role_audit import record_delegation_denied
        record_delegation_denied(request, 'clone role', '; '.join(errors), organization=org, target=source)
        messages.error(request, errors[0])
        return redirect('accounts:role_detail', pk=source.pk)
    base = f'{source.name} (Copy)'
    name, n = base, 2
    while RoleTemplate.objects.filter(name=name, organization=org).exists():
        name, n = f'{base} {n}', n + 1
    clone = RoleTemplate(name=name, description=source.description, organization=org, is_system_template=False,
                         audience=source.audience, cloned_from=source)
    for k, v in values.items():
        setattr(clone, k, v)
    clone.save()
    from .role_audit import record
    record('role.cloned', target_type='role_template', target_id=clone.pk, target_repr=clone.name,
           organization=org, request=request, extra={'from': source.name})
    messages.success(request, f'Created "{clone.name}". Adjust it and save.')
    return redirect('accounts:role_edit', pk=clone.pk)


@login_required
@require_POST
def role_archive(request, pk):
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    role = get_object_or_404(_visible_roles(org), pk=pk)
    if role.organization_id is None and not request.user.is_superuser:
        messages.error(request, 'Built-in roles are archived by a superuser only.')
        return redirect('accounts:role_detail', pk=role.pk)
    if not _can_manage_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    role.is_archived = not role.is_archived
    role.archived_at = timezone.now() if role.is_archived else None
    role.save()
    messages.success(request, f'Role "{role.name}" {"archived" if role.is_archived else "restored"}. '
                              + ('Existing assignments keep working; it can not be newly assigned.'
                                 if role.is_archived else ''))
    return redirect('accounts:role_detail', pk=role.pk)


@login_required
def role_delete(request, pk):
    """Delete an unused custom role template."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')

    role = get_object_or_404(RoleTemplate, pk=pk, organization=org)

    if role.is_system_template:
        messages.error(request, 'Cannot delete system role templates.')
        return redirect('accounts:role_list')

    if not _can_manage_roles(request.user, org):
        return _deny(request, 'roles_manage', org, 'You do not have permission to delete roles.')

    if request.method == 'POST':
        primary, additional, staff = _role_users(role)
        users_count = len(primary) + len(additional) + len(staff)
        if users_count > 0 or role.ldap_group_mappings.exists():
            messages.error(request, f'Cannot delete role "{role.name}" - it is assigned to {users_count} user(s) '
                                    'or used by a directory mapping. Reassign them first, or archive it.')
            return redirect('accounts:role_list')

        role_name = role.name
        role.delete()
        messages.success(request, f'Role "{role_name}" deleted successfully.')
        return redirect('accounts:role_list')

    return render(request, 'accounts/roles/role_delete_confirm.html', {
        'current_organization': org,
        'role': role,
    })


# --- compare / explain / catalog ----------------------------------------------------------------

@login_required
def role_compare(request):
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    roles = list(_visible_roles(org).order_by('name'))
    a = b = None
    rows = []
    try:
        a = next((r for r in roles if str(r.pk) == request.GET.get('a')), None)
        b = next((r for r in roles if str(r.pk) == request.GET.get('b')), None)
    except Exception:
        a = b = None
    if a and b:
        only_diff = request.GET.get('diff') == '1'
        for mkey, label, _desc, perms in registry.by_module():
            for p in perms:
                va, vb = bool(getattr(a, p.key, False)), bool(getattr(b, p.key, False))
                if only_diff and va == vb:
                    continue
                rows.append({'perm': p, 'a': va, 'b': vb, 'module': label})
    return render(request, 'accounts/roles/role_compare.html', {
        'current_organization': org, 'roles': roles, 'a': a, 'b': b, 'rows': rows,
        'only_diff': request.GET.get('diff') == '1',
    })


@login_required
def access_explain(request):
    """Why does a member (not) hold a permission here: role and scope."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    from core.utils import descendant_org_ids
    members = (User.objects.filter(memberships__organization_id__in=descendant_org_ids(org) | {org.pk})
               .distinct().order_by('username'))
    if request.user.is_superuser:
        members = (members | User.objects.filter(profile__user_type='staff')).distinct().order_by('username')
    target = None
    result = None
    perm_key = request.GET.get('perm', '')
    uid = request.GET.get('user', '')
    if uid.isdigit():
        target = members.filter(pk=int(uid)).first()
    if target is not None and registry.is_known(perm_key):
        result = explain_access(target, org, perm_key)
    effective = None
    if target is not None and not perm_key:
        eff = effective_permissions(target, org)
        effective = [(mlabel, [(p, eff[p.key]) for p in perms]) for _k, mlabel, _d, perms in registry.by_module()]
    return render(request, 'accounts/roles/access_explain.html', {
        'current_organization': org, 'members': members, 'target': target, 'perm_key': perm_key,
        'perm': registry.get(perm_key), 'result': result, 'effective': effective,
        'permissions': registry.PERMISSIONS,
    })


@login_required
def permission_catalog(request):
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'roles_manage', org)
    builtins = list(RoleTemplate.objects.filter(organization__isnull=True).exclude(seed_key='')
                    .order_by('audience', 'name'))
    matrix = []
    for mkey, label, desc, perms in registry.by_module():
        matrix.append((label, [(p, [bool(getattr(r, p.key, False)) for r in builtins]) for p in perms]))
    return render(request, 'accounts/roles/permission_catalog.html', {
        'current_organization': org, 'groups': registry.by_module(), 'external': registry.external_catalog(),
        'builtins': builtins, 'matrix': matrix, 'actions': registry.ACTIONS,
    })


# --- review list ---------------------------------------------------------------------------

@login_required
def review_list(request):
    if not request.user.is_superuser:
        raise PermissionDenied('Superusers only.')
    if request.method == 'POST':
        item = get_object_or_404(RoleReviewItem, pk=request.POST.get('item') or 0)
        new_status = request.POST.get('status')
        if new_status in (RoleReviewItem.RESOLVED, RoleReviewItem.DISMISSED, RoleReviewItem.OPEN):
            item.status = new_status
            item.resolved_by = request.user if new_status != RoleReviewItem.OPEN else None
            item.resolved_at = timezone.now() if new_status != RoleReviewItem.OPEN else None
            item.save()
            from .role_audit import record
            record('review.updated', target_type='role_review_item', target_id=item.pk,
                   target_repr=item.get_reason_display(), organization=item.organization_id, request=request,
                   after={'status': new_status})
        return redirect('accounts:role_review')
    status = request.GET.get('status', 'open')
    items = RoleReviewItem.objects.select_related('user', 'organization', 'membership', 'role_template')
    if status in ('open', 'resolved', 'dismissed'):
        items = items.filter(status=status)
    return render(request, 'accounts/roles/review_list.html', {'items': items[:500], 'status': status,
                                                               'counts': {s: RoleReviewItem.objects.filter(
                                                                   status=s).count()
                                                                   for s in ('open', 'resolved', 'dismissed')}})


# --- customer portal access ----------------------------------------------------------------------

@login_required
def portal_access(request):
    """Customer portal access of the selected organization."""
    org = _org_or_redirect(request)
    if not org:
        return redirect('accounts:organization_list')
    if not _can_view_roles(request.user, org):
        return _deny(request, 'org_manage_members', org)
    from psa.visibility import is_msp_staff
    from .scope import portal_sees_org_tickets
    rows = []
    for m in (Membership.objects.filter(organization=org).select_related('user', 'role_template')
              .prefetch_related('additional_roles').order_by('user__username')):
        if is_msp_staff(m.user):
            continue
        perms = m.get_permissions()
        rows.append({'m': m, 'org_tickets': portal_sees_org_tickets(m),
                     'billing': bool(getattr(perms, 'portal_billing_contact', False)),
                     'review': bool(getattr(perms, 'portal_contract_review', False)),
                     'sign': bool(getattr(perms, 'portal_contract_sign', False)),
                     'approve': bool(getattr(perms, 'portal_approve_requests', False)),
                     'internal': registry.non_customer_keys(perms)})
    portal_enabled = None
    try:
        from psa.models import ClientPSASettings
        row = ClientPSASettings.objects.filter(organization=org).first()
        portal_enabled = bool(row and row.portal_enabled)
    except Exception:
        pass
    customer_roles = RoleTemplate.objects.filter(Q(organization__isnull=True) | Q(organization=org),
                                                 audience='customer', is_archived=False).order_by('name')
    return render(request, 'accounts/roles/portal_access.html', {
        'current_organization': org, 'rows': rows, 'portal_enabled': portal_enabled,
        'customer_roles': customer_roles,
        'can_manage': user_has_org_perm(request.user, org, 'org_manage_members'),
    })


# --- assignment --------------------------------------------------------------------------------

@login_required
def member_role_assign(request, user_id):
    """Assign a member's primary role, additional roles and record scope.

    Every combination is checked by accounts.delegation: org_manage_members
    here, privileged roles need org_manage_privileged, the subset rule, no
    self-assignment, ownership only via transfer, last owner kept."""
    org = get_request_organization(request)
    if not org:
        messages.error(request, 'No organization selected.')
        return redirect('accounts:organization_list')

    if not user_has_org_perm(request.user, org, 'org_manage_members'):
        from .role_audit import record_denied
        record_denied(request, 'org_manage_members', organization=org)
        messages.error(request, 'You do not have permission to assign roles.')
        return redirect('accounts:member_list')

    user = get_object_or_404(User, pk=user_id)
    user_membership = get_object_or_404(Membership, user=user, organization=org)
    from .delegation import assignable_roles, can_assign_role, check_owner_change
    available = assignable_roles(request.user, org)
    available_ids = {r.pk for r in available}

    if request.method == 'POST':
        role_template_id = request.POST.get('role_template_id')
        role_template = None
        if role_template_id:
            # Only system-wide templates or this customer's own custom ones.
            role_template = get_object_or_404(
                RoleTemplate.objects.filter(Q(organization=org) | Q(organization__isnull=True)),
                pk=role_template_id,
            )
        extra_ids = [int(x) for x in request.POST.getlist('additional_role_ids') if x.isdigit()]
        extras = list(RoleTemplate.objects.filter(Q(organization=org) | Q(organization__isnull=True),
                                                  pk__in=extra_ids))
        record_scope = request.POST.get('record_scope') or user_membership.record_scope
        if record_scope not in dict(Membership.RECORD_SCOPE_CHOICES):
            record_scope = user_membership.record_scope
        verdict = can_assign_role(request.user, org, role_template, simple_role=user_membership.role,
                                  target_user=user, target_membership=user_membership, additional_roles=extras)
        if verdict:
            verdict = check_owner_change(user_membership, new_template=role_template, template_given=True)
        if not verdict:
            from .role_audit import record_delegation_denied
            record_delegation_denied(request, 'assign role', verdict.reason, organization=org,
                                     target=user_membership)
            messages.error(request, verdict.reason)
            return redirect('accounts:member_role_assign', user_id=user.pk)
        user_membership.role_template = role_template
        user_membership.record_scope = record_scope
        user_membership.save()
        user_membership.additional_roles.set(extras)
        if role_template:
            messages.success(request, f'Assigned role "{role_template.name}" to {user.username}.')
        else:
            messages.success(request, f'Cleared custom role for {user.username}. Using default role.')
        return redirect('accounts:member_list')

    system_templates = [r for r in available if r.organization_id is None]
    custom_templates = [r for r in available if r.organization_id is not None]
    return render(request, 'accounts/roles/member_role_assign.html', {
        'current_organization': org,
        'user': user,
        'user_membership': user_membership,
        'system_templates': system_templates,
        'custom_templates': custom_templates,
        'assignable_ids': available_ids,
        'current_extra_ids': set(user_membership.additional_roles.values_list('pk', flat=True)),
        'scope_choices': Membership.RECORD_SCOPE_CHOICES,
    })
