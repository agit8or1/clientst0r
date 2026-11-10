"""
Settings → Security → Technician Access.

Security administrators (superusers) only. One page, sections for presets,
assignments, groups, customer defaults and restrictions, denies, the
effective-access preview, protected changes, theft detection and
protection settings. Every change shows its diff first (action=preview…),
then saves (action=save…); widening saves become protected changes.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Organization

from . import catalog, detection, protected, services
from .models import (AccessAssignment, AccessPreset, Containment, CustomerAccessPolicy, DetectionSettings,
                     ExplicitDeny, ProtectedChange, ProtectionSettings, TechnicianGroup, TheftAlert)
from .resolver import effective_access, is_technician


def _admin(user):
    return user.is_authenticated and user.is_active and user.is_superuser


def technicians():
    User = get_user_model()
    return [u for u in User.objects.filter(is_active=True).select_related('profile').order_by('username')
            if is_technician(u)]


def _user(pk):
    u = get_user_model().objects.filter(pk=pk, is_active=True).first() if str(pk).isdigit() else None
    if u is None or not is_technician(u):
        raise Http404()
    return u


def _expiry(value):
    if not value:
        return None
    dt = parse_datetime(value) or parse_datetime(value + ':00')
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def _caps_from_post(post, current):
    """The posted capability map. A capability the POST does not carry keeps
    its current state: a partial submission is not a request to switch
    everything it left out to Off. Each select always posts its value, so
    choosing Off still posts `off`."""
    current = catalog.clean_capabilities(current)
    return catalog.clean_capabilities({k: post.get(f'cap_{k}', current.get(k, catalog.OFF))
                                       for k in catalog.OPTIONAL})


def _require_rendered(post, sentinel, what):
    """Multi-selects and checkbox groups post nothing when emptied, so
    "nothing posted" only means "clear" when the form's hidden `sentinel`
    shows the control was rendered and submitted."""
    if sentinel not in post:
        raise ValueError(f'{what} were not part of the submission; nothing was changed.')


def _report_change(request, change, applied_text):
    if change is None:
        messages.success(request, applied_text)
    else:
        messages.warning(request, f'This widens access ({", ".join(change.widening)}). Protected change '
                                  f'#{change.pk} was created: confirm it with your password below, then a '
                                  'different administrator approves it.')


def _context(request, **extra):
    orgs = Organization.objects.filter(is_active=True).order_by('name')
    pending = ProtectedChange.objects.filter(status=ProtectedChange.PENDING).select_related(
        'requested_by', 'target_user')
    pending_rows = [{'change': c, 'refusal': protected.approval_refusal(c, request.user)} for c in pending]
    ctx = {
        'active_page': 'technician_access',
        'presets': AccessPreset.objects.all(),
        'assignments': AccessAssignment.objects.live().select_related('preset', 'user', 'group', 'organization'),
        'groups': TechnicianGroup.objects.prefetch_related('members'),
        'organizations': orgs,
        'policies': {p.organization_id: p for p in CustomerAccessPolicy.objects.select_related('default_preset')},
        'denies': ExplicitDeny.objects.select_related('user', 'organization'),
        'technicians': technicians(),
        'catalog_optional': [(k,) + v for k, v in catalog.OPTIONAL.items()],
        'catalog_locked': list(catalog.LOCKED.items()),
        'state_labels': catalog.STATE_LABELS,
        'pending': pending_rows,
        'recent_changes': ProtectedChange.objects.exclude(status=ProtectedChange.PENDING)[:15],
        'fresh_auth': protected.has_fresh_auth(request),
        'can_widen': protected.can_widen_at_all(request.user),
        'detection': DetectionSettings.load(),
        'thresholds': detection.thresholds(),
        'containment_modes': {lvl: detection.containment_mode(lvl) for lvl in ('0', '1', '2', '3')},
        'alerts': TheftAlert.objects.select_related('user')[:25],
        'containments': Containment.objects.filter(lifted_at__isnull=True).select_related('user', 'alert'),
        'protection': ProtectionSettings.load(),
        'approvers': protected.approvers(),
        'superusers': get_user_model().objects.filter(is_active=True, is_superuser=True).order_by('username'),
        'drift': {p.pk: services.reset_preview(p) for p in AccessPreset.objects.all()},
    }
    ctx.update(extra)
    return ctx


@login_required
@user_passes_test(_admin)
def index(request):
    services.seed_presets()
    if request.method == 'POST':
        result = _handle(request)
        if result is not None:
            return result
        return redirect(request.path + '#' + (request.POST.get('section') or 'presets'))
    extra = {}
    if request.GET.get('preview_user') and request.GET.get('preview_org'):
        u = _user(request.GET['preview_user'])
        org = get_object_or_404(Organization, pk=request.GET['preview_org'])
        extra['effective'] = {'user': u, 'organization': org, 'rows': effective_access(u, org)}
    return render(request, 'tech_access/index.html', _context(request, **extra))


def _handle(request):
    p = request.POST
    action = p.get('action', '')
    me = request.user
    try:
        if action == 'reauth':
            err = protected.reauthenticate(request, p.get('password', ''), p.get('otp', ''))
            messages.error(request, err) if err else messages.success(request, 'Confirmed. Valid for 5 minutes.')
        elif action in ('preview_assign', 'save_assign'):
            subject = (TechnicianGroup.objects.get(pk=p['group']) if p.get('group')
                       else _user(p.get('user')))
            org = get_object_or_404(Organization, pk=p.get('organization'))
            preset = get_object_or_404(AccessPreset, pk=p.get('preset')) if p.get('preset') \
                else services.default_preset_for(org)
            expires = _expiry(p.get('expires_at'))
            if action == 'preview_assign':
                plan = services.plan_assignment(subject, org, preset, expires)
                return render(request, 'tech_access/index.html', _context(
                    request, assign_plan=plan, assign_form=p))
            a, change, _ = services.assign(subject, org, preset, me, expires, p.get('note', ''), request)
            _report_change(request, change, f'Assigned {preset.name} at {org.name}.')
        elif action == 'revoke':
            services.revoke(get_object_or_404(AccessAssignment, pk=p.get('assignment')), me)
            messages.success(request, 'Assignment revoked.')
        elif action == 'clone':
            src = get_object_or_404(AccessPreset, pk=p.get('preset'))
            clone = services.clone_preset(src, p.get('name') or f'{src.name} (copy)', me)
            messages.success(request, f'Created {clone.name}. Edit it below.')
        elif action in ('preview_preset', 'save_preset'):
            preset = get_object_or_404(AccessPreset, pk=p.get('preset'))
            caps = _caps_from_post(p, preset.capabilities)
            if action == 'preview_preset':
                return render(request, 'tech_access/index.html', _context(
                    request, preset_plan=services.plan_preset_change(preset, caps), preset_edit=preset,
                    preset_caps=caps))
            applied, change, _ = services.change_preset(preset, caps, me, request)
            _report_change(request, change, f'{preset.name} updated.')
        elif action == 'reset_preset':
            preset = get_object_or_404(AccessPreset, pk=p.get('preset'))
            applied, change, _ = services.reset_preset(preset, me, request)
            _report_change(request, change, f'{preset.name} reset.')
        elif action == 'create_group':
            name = (p.get('name') or '').strip()
            if name:
                TechnicianGroup.objects.get_or_create(name=name[:100])
                messages.success(request, f'Group {name} created.')
        elif action == 'group_members':
            group = get_object_or_404(TechnicianGroup, pk=p.get('group'))
            _require_rendered(p, 'members_present', 'Group members')
            users = [_user(pk) for pk in p.getlist('members')]
            applied, change, _ = services.set_group_members(group, users, me, request)
            _report_change(request, change, f'Members of {group.name} updated.')
        elif action == 'customer_policy':
            org = get_object_or_404(Organization, pk=p.get('organization'))
            # Each part is applied only when the POST carries it: a missing
            # default preset is not "reset to L1", and a missing restriction
            # list is not "lift every restriction".
            if 'default_preset' in p:
                raw = p.get('default_preset')
                preset = AccessPreset.objects.filter(pk=raw).first() if str(raw).isdigit() else None
                if raw and preset is None:
                    raise ValueError('Unknown preset.')
                services.set_default_preset(org, preset, me)
            change = None
            if 'restricted_present' in p:
                change = services.set_restrictions(org, p.getlist('restricted'), me, request)
            _report_change(request, change, f'Settings for {org.name} saved.')
        elif action == 'add_deny':
            u = _user(p.get('user'))
            cap = p.get('capability')
            if cap != '*' and cap not in catalog.OPTIONAL:
                raise ValueError('Unknown capability.')
            org = Organization.objects.filter(pk=p.get('organization')).first() if p.get('organization') else None
            services.add_deny(u, cap, me, org, p.get('reason', ''), _expiry(p.get('expires_at')))
            messages.success(request, 'Deny added. It applies immediately.')
        elif action == 'lift_deny':
            change = services.remove_deny(get_object_or_404(ExplicitDeny, pk=p.get('deny')), me, request)
            _report_change(request, change, '')
        elif action == 'confirm_change':
            protected.confirm(get_object_or_404(ProtectedChange, pk=p.get('change')), request)
            messages.success(request, 'Confirmed. Another administrator can now approve it.')
        elif action == 'approve_change':
            protected.approve(get_object_or_404(ProtectedChange, pk=p.get('change')), request)
            messages.success(request, 'Approved and applied.')
        elif action in ('reject_change', 'cancel_change'):
            protected.reject(get_object_or_404(ProtectedChange, pk=p.get('change')), request,
                             cancel=action == 'cancel_change')
            messages.success(request, 'Done.')
        elif action == 'detection':
            # Anything the POST does not carry keeps its current setting: the
            # two checkboxes only read as "off" when `detection_flags` shows
            # they were rendered, and a missing containment mode is not
            # "contain".
            current = DetectionSettings.load()
            flags = 'detection_flags' in p
            values = {'enabled': (p.get('enabled') == 'on') if flags else current.enabled,
                      'notify_customers': (p.get('notify_customers') == 'on') if flags else current.notify_customers,
                      'recipients': p.get('recipients', current.recipients),
                      'thresholds': {r: {w: int(p.get(f't_{r}_{w}') or v) for w, v in ws.items()}
                                     for r, ws in detection.thresholds().items()},
                      'containment': {lvl: (p.get(f'c_{lvl}') if p.get(f'c_{lvl}') in ('alert', 'contain')
                                            else detection.containment_mode(lvl))
                                      for lvl in ('0', '1', '2', '3')}}
            change = services.propose_detection(values, me, request)
            _report_change(request, change, 'Theft detection settings saved.')
        elif action == 'lift_containment':
            c = get_object_or_404(Containment, pk=p.get('containment'), lifted_at__isnull=True)
            if c.user_id == me.pk:
                raise ValueError('Another administrator must lift your own containment.')
            if not protected.has_fresh_auth(request):
                raise ValueError('Re-enter your password first.')
            c.lifted_at, c.lifted_by = timezone.now(), me
            c.save(update_fields=['lifted_at', 'lifted_by'])
            services._audit(me, 'update', 'tech_access_containment', c.pk, f'Lifted containment of {c.user}')
            messages.success(request, f'Containment of {c.user.get_username()} lifted.')
        elif action == 'ack_alert':
            TheftAlert.objects.filter(pk=p.get('alert'), acknowledged_at__isnull=True).update(
                acknowledged_by=me, acknowledged_at=timezone.now())
        elif action == 'approvers':
            User = get_user_model()
            _require_rendered(p, 'approvers_present', 'Approvers')
            current = set(ProtectionSettings.load().approvers.values_list('pk', flat=True))
            want = set(User.objects.filter(pk__in=p.getlist('approvers'), is_superuser=True,
                                           is_active=True).values_list('pk', flat=True))
            change = services.propose_approvers(list(User.objects.filter(pk__in=want - current)),
                                                list(User.objects.filter(pk__in=current - want)), me, request)
            _report_change(request, change, 'Approvers updated.')
        elif action == 'recovery_contact':
            change = services.propose_recovery_contact((p.get('recovery_email') or '').strip(), me, request)
            _report_change(request, change, '')
        else:
            messages.error(request, 'Unknown action.')
    except (protected.ProtectedChangeError, ValueError) as e:
        messages.error(request, str(e))
    return None


SUPERUSER_KINDS = ('superuser_grant', 'superuser_policy')


@login_required
@user_passes_test(_admin)
def superuser_policy(request):
    """Admin → Security → Superuser Approval (v3.17.653): the optional policy
    that makes granting superuser take a second administrator, and the
    pending grants. Confirming and approving are the protected-change steps
    used everywhere else."""
    if request.method == 'POST':
        p, me = request.POST, request.user
        action = p.get('action', '')
        try:
            if action == 'reauth':
                err = protected.reauthenticate(request, p.get('password', ''), p.get('otp', ''))
                messages.error(request, err) if err else messages.success(request, 'Confirmed. Valid for 5 minutes.')
            elif action == 'enable':
                services.enable_superuser_policy(me, request)
                messages.success(request, 'Granting superuser now takes a second administrator\'s approval.')
            elif action == 'request_disable':
                change = services.propose_disable_superuser_policy(me, request)
                messages.warning(request, f'Protected change #{change.pk}: confirm it below, then a different '
                                          'administrator approves it. The policy stays on until then.')
            elif action in ('confirm_change', 'approve_change', 'reject_change', 'cancel_change'):
                change = get_object_or_404(ProtectedChange, pk=p.get('change'), kind__in=SUPERUSER_KINDS)
                if action == 'confirm_change':
                    protected.confirm(change, request)
                    messages.success(request, 'Confirmed. A different administrator can now approve it.')
                elif action == 'approve_change':
                    protected.approve(change, request)
                    messages.success(request, 'Approved and applied.')
                else:
                    protected.reject(change, request, cancel=action == 'cancel_change')
                    messages.success(request, 'Done.')
        except (ValueError, protected.ProtectedChangeError) as exc:
            messages.error(request, str(exc))
        return redirect('tech_access:superuser_policy')

    pending = (ProtectedChange.objects.filter(status=ProtectedChange.PENDING, kind__in=SUPERUSER_KINDS)
               .select_related('requested_by', 'target_user'))
    return render(request, 'tech_access/superuser_policy.html', {
        'policy_on': services.superuser_policy_on(),
        'eligible': services.eligible_admins().order_by('username'),
        'pending': [{'change': c, 'refusal': protected.approval_refusal(c, request.user)} for c in pending],
        'recent': ProtectedChange.objects.filter(kind__in=SUPERUSER_KINDS).exclude(
            status=ProtectedChange.PENDING).select_related('requested_by', 'reviewed_by', 'target_user')[:20],
        'fresh_auth': protected.has_fresh_auth(request),
        'is_approver': protected.is_approver(request.user),
    })


# --- "why": the chain behind one decision ------------------------------------

def _all_capabilities():
    return [(k, v[0]) for k, v in catalog.OPTIONAL.items()] + [(k, v[0]) for k, v in catalog.LOCKED.items()]


@login_required
@user_passes_test(_admin)
def why(request):
    """Why can this technician do this for this customer, who granted it,
    and when does it expire? Security administrators only; reads only rows
    at the chosen customer (see tech_access.explain)."""
    from .explain import explain
    result = None
    g = request.GET
    user_pk, org_pk, cap = g.get('user', ''), g.get('organization', ''), g.get('capability', '')
    if user_pk and org_pk and cap:
        if cap not in catalog.OPTIONAL and cap not in catalog.LOCKED:
            raise Http404()
        if not (user_pk.isdigit() and org_pk.isdigit()):
            raise Http404()
        tech = get_object_or_404(get_user_model(), pk=user_pk)
        org = get_object_or_404(Organization, pk=org_pk)
        result = explain(tech, org, cap)
    return render(request, 'tech_access/why.html', {
        'active_page': 'technician_access',
        'result': result,
        'technicians': technicians(),
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'capabilities': _all_capabilities(),
        'sel': {'user': user_pk, 'organization': org_pk, 'capability': cap},
    })


@login_required
@user_passes_test(_admin)
def assignment_detail(request, pk):
    """One assignment record: who, where, preset, granted by/at, expiry,
    revocation, the approving protected change and its audit history."""
    from .explain import _approval_for_assignment, _audit, _change_history
    a = get_object_or_404(AccessAssignment.objects.select_related(
        'preset', 'user', 'group', 'organization', 'granted_by', 'revoked_by'), pk=pk)
    approval = _approval_for_assignment(a)
    history = sorted({e.pk: e for e in _audit('tech_access_assignment', a.pk, limit=100)
                      + _change_history(approval)}.values(),
                     key=lambda e: (e.timestamp, e.pk), reverse=True)
    caps = a.preset.caps()
    return render(request, 'tech_access/assignment_detail.html', {
        'active_page': 'technician_access', 'a': a, 'status': a.status(), 'approval': approval,
        'history': history, 'caps': [(k, v[0], caps.get(k, catalog.OFF)) for k, v in catalog.OPTIONAL.items()],
    })


@login_required
@user_passes_test(_admin)
def change_detail(request, pk):
    """One protected change: requester, confirmation, reviewer, what it
    widened, its status and its audit trail."""
    from .explain import _change_history
    change = get_object_or_404(ProtectedChange.objects.select_related('requested_by', 'reviewed_by', 'target_user'),
                               pk=pk)
    return render(request, 'tech_access/change_detail.html', {
        'active_page': 'technician_access', 'change': change, 'history': _change_history(change),
        'assignments': AccessAssignment.objects.filter(approved_change=change).select_related(
            'organization', 'preset'),
    })
