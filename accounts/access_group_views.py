"""
Access groups (Users & Access -> Roles -> Access groups).

A group of MSP staff that carries one internal role at a customer scope;
what that grants and how it is enforced is in accounts.access_groups. These
pages only change groups; every check is server side:

  * opening the pages and changing anything: `roles_manage` MSP-wide
    (access_groups.can_manage);
  * a group whose role is privileged needs that level too, and nobody but a
    superuser changes a group they belong to or a group whose role holds
    permissions they lack (access_groups.group_refusal / role_refusal);
  * members are MSP staff only (also enforced on every add by a signal);
  * membership goes through tech_access.services.set_group_members, so a
    member added to a group with technician access presets that widen their
    access waits for the usual protected change;
  * every change is in the audit trail with before / after.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import access_groups
from .models import RoleTemplate
from .role_audit import record, record_denied

User = get_user_model()


def _group_model():
    from tech_access.models import TechnicianGroup
    return TechnicianGroup


def _deny(request, message):
    record_denied(request, 'roles_manage')
    messages.error(request, message)
    return redirect('core:dashboard')


def _role_choices(current=None):
    """Internal roles a group may carry: install-wide, not customer-only,
    not archived (the current role is kept even when archived)."""
    qs = RoleTemplate.objects.filter(organization__isnull=True).exclude(audience='customer')
    qs = qs.filter(Q(is_archived=False) | Q(pk=getattr(current, 'pk', None)))
    from .role_order import grouped
    return grouped(qs)


def _staff_users():
    from psa.visibility import msp_staff_q
    return User.objects.filter(is_active=True).filter(msp_staff_q()).distinct().order_by('username')


def _customers():
    from core.models import Organization
    return Organization.objects.filter(is_active=True).order_by('name')


@login_required
def access_group_list(request):
    if not access_groups.can_manage(request.user):
        return _deny(request, 'Managing access groups needs the roles_manage permission across every customer.')
    groups = (_group_model().objects.select_related('role_template')
              .prefetch_related('customers')
              .annotate(n_members=Count('members', distinct=True)).order_by('name'))
    rows = []
    for g in groups:
        rows.append({'group': g, 'members': g.n_members, 'presets': g.assignments.live().count(),
                     'refusal': access_groups.group_refusal(request.user, g)})
    return render(request, 'accounts/roles/access_group_list.html', {
        'rows': rows, 'active_page': 'access_groups',
    })


@login_required
def access_group_edit(request, pk=None):
    if not access_groups.can_manage(request.user):
        return _deny(request, 'Managing access groups needs the roles_manage permission across every customer.')
    Group = _group_model()
    group = get_object_or_404(Group, pk=pk) if pk is not None else None
    refusal = access_groups.group_refusal(request.user, group) if group is not None else ''
    errors = []

    if request.method == 'POST':
        if refusal:
            record_denied(request, 'roles_manage')
            messages.error(request, refusal)
            return redirect('accounts:access_group_edit', pk=group.pk)
        p = request.POST
        name = (p.get('name') or '').strip()[:100]
        description = (p.get('description') or '').strip()
        role = None
        if p.get('role'):
            role = RoleTemplate.objects.filter(pk=p.get('role') if str(p.get('role')).isdigit() else 0).first()
            if role is None:
                errors.append('Unknown role.')
        all_customers = p.get('scope') != 'selected'
        customer_ids = [int(x) for x in p.getlist('customers') if str(x).isdigit()]
        customers = list(_customers().filter(pk__in=customer_ids))
        if 'members_present' not in p:
            errors.append('The member list was not part of the submission; nothing was changed.')
        member_ids = [int(x) for x in p.getlist('members') if str(x).isdigit()]
        members = list(User.objects.filter(pk__in=member_ids).select_related('profile'))
        if len(members) != len(set(member_ids)):
            errors.append('Unknown user in the member list.')
        if not name:
            errors.append('A name is required.')
        elif Group.objects.filter(name=name).exclude(pk=getattr(group, 'pk', None)).exists():
            errors.append(f'A group named "{name}" already exists.')
        reason = access_groups.role_refusal(request.user, role)
        if reason:
            errors.append(reason)
        current = set(group.members.values_list('pk', flat=True)) if group is not None else set()
        for u in members:
            if u.pk in current:
                continue  # already a member: kept as is
            why = access_groups.member_refusal(request.user, u)
            if why:
                errors.append(why)
        if errors:
            from .role_audit import record_delegation_denied
            record_delegation_denied(request, 'change access group', '; '.join(errors)[:300])
        else:
            from tech_access import services
            before = access_groups.snapshot(group) if group is not None else None
            with transaction.atomic():
                creating = group is None
                if creating:
                    group = Group(name=name)
                group.name = name
                group.description = description
                group.role_template = role
                group.all_customers = all_customers
                group.save()
                group.customers.set([] if all_customers else customers)
            try:
                with transaction.atomic():
                    applied, change, _plan = services.set_group_members(group, members, request.user, request)
            except ValidationError as exc:
                applied, change = False, None
                messages.error(request, ' '.join(exc.messages))
            after = access_groups.snapshot(group)
            record('access_group.created' if creating else 'access_group.updated',
                   target_type='access_group', target_id=group.pk, target_repr=group.name,
                   before=before, after=after, request=request)
            if change is not None:
                messages.warning(request, f'Adding members widens their technician access presets '
                                          f'({", ".join(change.widening)}): protected change #{change.pk} waits '
                                          'for a second administrator (Technician Access). The other changes '
                                          'are saved.')
            elif applied:
                messages.success(request, f'Access group "{group.name}" saved.')
            return redirect('accounts:access_group_edit', pk=group.pk)

    if request.method == 'POST' and errors:
        form = {'name': request.POST.get('name', ''), 'description': request.POST.get('description', ''),
                'role_id': int(request.POST['role']) if str(request.POST.get('role', '')).isdigit() else None,
                'all_customers': request.POST.get('scope') != 'selected',
                'customer_ids': {int(x) for x in request.POST.getlist('customers') if str(x).isdigit()},
                'member_ids': {int(x) for x in request.POST.getlist('members') if str(x).isdigit()}}
    elif group is not None:
        form = {'name': group.name, 'description': group.description, 'role_id': group.role_template_id,
                'all_customers': group.all_customers,
                'customer_ids': set(group.customers.values_list('pk', flat=True)),
                'member_ids': set(group.members.values_list('pk', flat=True))}
    else:
        form = {'name': '', 'description': '', 'role_id': None, 'all_customers': True,
                'customer_ids': set(), 'member_ids': set()}

    return render(request, 'accounts/roles/access_group_form.html', {
        'group': group, 'form': form, 'errors': errors, 'refusal': refusal,
        'role_groups': _role_choices(getattr(group, 'role_template', None)),
        'staff_users': _staff_users(), 'customers': _customers(),
        'assignments': group.assignments.live().select_related('preset', 'organization') if group else [],
        'active_page': 'access_groups',
    })


@login_required
@require_POST
def access_group_delete(request, pk):
    if not access_groups.can_manage(request.user):
        return _deny(request, 'Managing access groups needs the roles_manage permission across every customer.')
    group = get_object_or_404(_group_model(), pk=pk)
    refusal = access_groups.group_refusal(request.user, group)
    if refusal:
        record_denied(request, 'roles_manage')
        messages.error(request, refusal)
        return redirect('accounts:access_group_edit', pk=group.pk)
    before = access_groups.snapshot(group)
    name, gid = group.name, group.pk
    group.delete()
    record('access_group.deleted', target_type='access_group', target_id=gid, target_repr=name,
           before=before, request=request)
    messages.success(request, f'Access group "{name}" deleted. Its members no longer hold its role.')
    return redirect('accounts:access_group_list')
