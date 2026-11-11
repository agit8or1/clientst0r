"""
Settings → Security → RMM Permissions.

  index        overrides (allow / deny / require approval), their reviews,
               and links to the per-technician and per-customer views.
  technician   effective RMM permissions and approval requirements for one
               technician at one customer, each with the chain that decided
               it ("why").
  customer     every technician scoped to one customer × every action.
  approvals    pending second-person approvals: approve / reject.

Reading needs “Manage RMM policy and roles” or “Review the audit log”;
changing overrides needs the first. Approvals are open to technicians: the
approve call itself checks the approver qualifies. Every write that widens
access, and every approval, takes a fresh password confirmation.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Organization

from . import approvals as approvals_svc
from . import catalog, overrides
from .decision import can, effective, is_technician, tier_of
from .models import RMMApproval, RMMPermissionOverride


def _reader(user):
    return can(user, None, 'policy.manage').allowed or can(user, None, 'audit.review').allowed


def _gate(request):
    if not (request.user.is_authenticated and _reader(request.user)):
        raise PermissionDenied('RMM permissions need “Manage RMM policy and roles” or “Review the audit log”.')


def _technicians():
    User = get_user_model()
    return [u for u in User.objects.filter(is_active=True).select_related('profile').order_by('username')
            if is_technician(u)]


def _scoped_technicians(org):
    from tech_access.models import AccessAssignment
    ids = set()
    for a in AccessAssignment.objects.live().filter(organization=org).select_related('group'):
        if a.user_id:
            ids.add(a.user_id)
        else:
            ids |= set(a.group.members.values_list('pk', flat=True))
    User = get_user_model()
    return [u for u in User.objects.filter(pk__in=ids, is_active=True).order_by('username') if is_technician(u)]


def _reauth(request):
    from tech_access.protected import has_fresh_auth, reauthenticate
    pw = request.POST.get('password', '')
    if pw:
        err = reauthenticate(request, pw, request.POST.get('otp', ''))
        if err:
            messages.error(request, err)
            return False
    return has_fresh_auth(request)


@login_required
def index(request):
    _gate(request)
    manage = can(request.user, None, 'policy.manage').allowed
    if request.method == 'POST':
        if not manage:
            raise PermissionDenied()
        _handle(request)
        return redirect('rmm_permissions:index')
    qs = RMMPermissionOverride.objects.select_related('organization', 'user', 'role_template', 'created_by',
                                                      'reviewed_by', 'lift_requested_by')
    from accounts.models import RoleTemplate
    return render(request, 'rmm_permissions/index.html', {
        'active_page': 'rmm_permissions',
        'manage': manage,
        'live': qs.filter(status=RMMPermissionOverride.ACTIVE),
        'pending': qs.filter(status=RMMPermissionOverride.PENDING),
        'ended': qs.exclude(status__in=[RMMPermissionOverride.ACTIVE, RMMPermissionOverride.PENDING])[:50],
        'actions': list(catalog.ACTIONS.items()),
        'effects': RMMPermissionOverride.EFFECTS,
        'levels': [(k, catalog.APPROVAL_LABELS[k]) for k in catalog.APPROVAL_LEVELS],
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'technicians': _technicians(),
        'roles': RoleTemplate.objects.filter(organization__isnull=True).order_by('name'),
        'tiered_roles': RoleTemplate.objects.exclude(rmm_tier='').order_by('name'),
        'open_approvals': RMMApproval.objects.filter(status=RMMApproval.PENDING,
                                                     expires_at__gt=timezone.now()).count(),
    })


def _pick(model, pk, **filters):
    if not pk:
        return None
    if not str(pk).isdigit():
        raise Http404()
    return get_object_or_404(model, pk=pk, **filters)


def _handle(request):
    from accounts.models import RoleTemplate
    p = request.POST
    op = p.get('op', '')
    o = _pick(RMMPermissionOverride, p.get('override')) if op != 'create' else None
    try:
        if op == 'create':
            exp = parse_datetime(p.get('expires_at', '') or '') or parse_datetime((p.get('expires_at') or '') + ':00')
            if exp is not None and timezone.is_naive(exp):
                exp = timezone.make_aware(exp)
            created = overrides.create(
                request.user, action=p.get('action', ''), effect=p.get('effect', ''),
                organization=_pick(Organization, p.get('organization')),
                user=_pick(get_user_model(), p.get('user')),
                role_template=_pick(RoleTemplate, p.get('role_template'), organization__isnull=True),
                approval_level=p.get('approval_level', ''), reason=p.get('reason', ''), expires_at=exp,
                request=request)
            messages.success(request, f'Override #{created.pk} saved' + (
                ' and waiting for a second administrator.' if created.status == created.PENDING else '.'))
        elif op in ('approve', 'reject', 'confirm_lift', 'keep'):
            if not _reauth(request):
                messages.error(request, 'Confirm your password to review.')
                return
            if op in ('approve', 'reject'):
                ok, msg = overrides.review(o, request, approve=(op == 'approve'))
            else:
                ok, msg = overrides.review_lift(o, request, approve=(op == 'confirm_lift'))
            (messages.success if ok else messages.error)(request, msg)
        elif op == 'revoke':
            ok, msg = overrides.revoke(o, request.user, request)
            (messages.success if ok else messages.error)(request, msg)
        else:
            messages.error(request, 'Unknown request.')
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, ' '.join(getattr(e, 'messages', [str(e)])))


@login_required
def technician(request, user_id):
    _gate(request)
    tech = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if not is_technician(tech):
        raise Http404()
    from tech_access.models import AccessAssignment
    org_ids = (AccessAssignment.objects.live().filter(Q(user=tech) | Q(group__members=tech))
               .values_list('organization_id', flat=True))
    customers = Organization.objects.filter(pk__in=list(org_ids)).order_by('name')
    org_pk = request.GET.get('organization') or (customers[0].pk if customers else '')
    org = _pick(Organization, org_pk) if org_pk else None
    rows = []
    if org is not None:
        for d in effective(tech, org):
            spec = catalog.ACTIONS.get(d.action)
            rows.append({'d': d, 'label': spec.label if spec else d.action,
                         'group': spec.group if spec else 'Locked', 'locked': spec is None,
                         'tech_capability': spec.tech_capability if spec else None})
    return render(request, 'rmm_permissions/technician.html', {
        'active_page': 'rmm_permissions', 'tech': tech, 'tier': tier_of(tech),
        'tier_label': catalog.TIER_LABELS.get(tier_of(tech), 'none'), 'customers': customers,
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'org': org, 'rows': rows,
    })


@login_required
def customer(request, org_id):
    _gate(request)
    org = get_object_or_404(Organization, pk=org_id)
    techs = _scoped_technicians(org)
    keys = list(catalog.ACTIONS)
    matrix = [{'tech': t, 'tier': catalog.TIER_LABELS.get(tier_of(t), '—'),
               'cells': [can(t, org, k) for k in keys]} for t in techs]
    return render(request, 'rmm_permissions/customer.html', {
        'active_page': 'rmm_permissions', 'org': org, 'matrix': matrix,
        'columns': [(k, catalog.ACTIONS[k].label) for k in keys],
        'overrides': RMMPermissionOverride.objects.filter(Q(organization=org) | Q(organization__isnull=True))
        .filter(status__in=[RMMPermissionOverride.ACTIVE, RMMPermissionOverride.PENDING])
        .select_related('user', 'role_template'),
    })


@login_required
def approvals(request):
    if not is_technician(request.user):
        raise PermissionDenied()
    if request.method == 'POST':
        a = _pick(RMMApproval, request.POST.get('approval'))
        if a is None:
            raise Http404()
        op = request.POST.get('op', '')
        if op == 'cancel' and a.requester_id == request.user.pk:
            ok, msg = approvals_svc.reject(a, request)
        elif op in ('approve', 'reject'):
            if not _reauth(request):
                messages.error(request, 'Confirm your password to approve or reject.')
                return redirect('rmm_permissions:approvals')
            fn = approvals_svc.approve if op == 'approve' else approvals_svc.reject
            ok, msg = fn(a, request, request.POST.get('note', ''))
        else:
            ok, msg = False, 'Unknown request.'
        (messages.success if ok else messages.error)(request, msg)
        return redirect('rmm_permissions:approvals')
    rows = []
    for a in approvals_svc.open_for(request.user):
        why = '' if a.requester_id == request.user.pk else approvals_svc.refusal(a, request.user)
        rows.append({'a': a, 'mine': a.requester_id == request.user.pk, 'can_decide': not why, 'why': why,
                     'label': catalog.ACTIONS.get(a.action).label if a.action in catalog.ACTIONS else a.action,
                     'level': catalog.APPROVAL_LABELS.get(a.approval_level, a.approval_level)})
    return render(request, 'rmm_permissions/approvals.html', {'active_page': 'rmm_permissions', 'rows': rows})
