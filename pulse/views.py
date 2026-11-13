"""Staff pages for pulse checks (MSP staff only; /pulse/ is also a staff-only
prefix in accounts.middleware.SectionPermissionMiddleware).

Staff limited to some clients (accounts.permission_utils.staff_client_org_ids)
see only those clients' responses, and may only edit or send checks whose
organizations are all within their reach — never "all clients" checks.
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from audit.models import AuditLog
from core.client_ip import get_client_ip
from core.models import Organization

from . import audience, results
from .forms import PulseCheckForm, parse_questions, question_rows
from .models import PulseCheck, PulseOptOut, PulseQuestion, PulseResponse, PulseSend
from .sending import send_check


def staff_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from psa.visibility import is_msp_staff
        if not is_msp_staff(request.user):
            raise PermissionDenied('Pulse checks are managed by MSP staff.')
        return view(request, *args, **kwargs)
    return wrapped


def _allowed(request):
    from core.tenancy import accessible_org_ids
    return accessible_org_ids(request)


def _check_org_ids(check):
    return set(check.organizations.values_list('pk', flat=True))


def can_manage(check, allowed):
    if allowed is None:
        return True
    return not check.all_organizations and _check_org_ids(check) <= set(allowed)


def can_view(check, allowed):
    if allowed is None:
        return True
    return not check.all_organizations and bool(_check_org_ids(check) & set(allowed))


def _visible_checks(allowed):
    qs = PulseCheck.objects.all()
    if allowed is not None:
        qs = qs.filter(all_organizations=False, organizations__in=allowed).distinct()
    return qs


def _scoped_responses(qs, allowed):
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


def _org_filter(request, qs, allowed):
    """Apply ?org=<id>; returns (qs, chosen org or None)."""
    org = None
    raw = request.GET.get('org')
    if raw:
        try:
            org = Organization.objects.get(pk=int(raw))
        except (ValueError, Organization.DoesNotExist):
            org = None
        if org is not None and allowed is not None and org.pk not in allowed:
            org = None
        if org is not None:
            qs = qs.filter(organization=org)
    return qs, org


def _audit(request, action, check, description, **extra):
    AuditLog.log(
        user=request.user, action=action, object_type='pulse.PulseCheck', object_id=check.pk,
        object_repr=check.name[:255], description=description,
        ip_address=get_client_ip(request), path=request.path,
        extra_data={'event': f'pulse_check_{action}', **extra},
    )


@staff_required
def check_list(request):
    allowed = _allowed(request)
    checks = (_visible_checks(allowed)
              .annotate(send_total=Count('sends', distinct=True), last_sent=Max('sends__created_at'))
              .order_by('-is_active', 'name'))
    rows = []
    for c in checks:
        resp = _scoped_responses(PulseResponse.objects.filter(send__pulse_check=c), allowed)
        total = resp.count()
        answered = resp.filter(responded_at__isnull=False).count()
        rows.append({'check': c, 'total': total, 'answered': answered,
                     'rate': round(100.0 * answered / total) if total else None,
                     'can_manage': can_manage(c, allowed)})
    return render(request, 'pulse/check_list.html', {
        'rows': rows, 'can_create': True,
        'opt_out_count': PulseOptOut.objects.count(),
    })


def _save_questions(check, rows):
    check.questions.all().delete()
    PulseQuestion.objects.bulk_create([
        PulseQuestion(pulse_check=check, order=i, kind=r['kind'], text=r['text'], required=r['required'])
        for i, r in enumerate(rows)
    ])


def _edit(request, check=None):
    allowed = _allowed(request)
    if check is not None and not can_manage(check, allowed):
        raise PermissionDenied('This pulse check includes clients outside your reach.')
    form = PulseCheckForm(request.POST or None, instance=check, allowed_org_ids=allowed)
    qrows = question_rows(check)
    if request.method == 'POST':
        rows, qerrors = parse_questions(request.POST)
        qrows = question_rows(posted=rows)
        if form.is_valid() and not qerrors:
            creating = check is None
            with transaction.atomic():
                obj = form.save(commit=False)
                if creating:
                    obj.created_by = request.user
                obj.audience_roles = list(form.cleaned_data.get('audience_roles') or [])
                obj.save()
                form.save_m2m()
                _save_questions(obj, rows)
            _audit(request, 'create' if creating else 'update', obj,
                   f'Pulse check "{obj.name}" {"created" if creating else "updated"}',
                   audience=obj.audience, schedule=obj.schedule,
                   all_organizations=obj.all_organizations,
                   organizations=sorted(_check_org_ids(obj)))
            messages.success(request, f'Pulse check "{obj.name}" saved.')
            return redirect('pulse:check_detail', pk=obj.pk)
        for e in qerrors:
            messages.error(request, e)
    return render(request, 'pulse/check_form.html', {
        'form': form, 'check': check, 'question_rows': qrows,
        'kind_choices': PulseQuestion.KIND_CHOICES,
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def check_create(request):
    return _edit(request)


@staff_required
@require_http_methods(['GET', 'POST'])
def check_edit(request, pk):
    return _edit(request, get_object_or_404(PulseCheck, pk=pk))


def _get_visible(request, pk):
    check = get_object_or_404(PulseCheck, pk=pk)
    allowed = _allowed(request)
    if not can_view(check, allowed):
        raise Http404('No pulse check here')
    return check, allowed


def _org_breakdown(responses):
    by_org = {}
    for r in responses:
        by_org.setdefault(r.organization_id, {'organization': r.organization, 'rows': []})
        by_org[r.organization_id]['rows'].append(r)
    out = []
    for item in by_org.values():
        s = results.summarize(item['rows'])
        out.append({'organization': item['organization'], 'summary': s})
    out.sort(key=lambda x: x['organization'].name)
    return out


@staff_required
def check_detail(request, pk):
    check, allowed = _get_visible(request, pk)
    qs = _scoped_responses(PulseResponse.objects.filter(send__pulse_check=check), allowed)
    qs, org = _org_filter(request, qs, allowed)
    responses = list(qs.select_related('send', 'organization', 'user', 'contact'))
    sends = []
    for s in check.sends.all():
        srows = [r for r in responses if r.send_id == s.pk]
        sends.append({'send': s, 'summary': results.summarize(srows)})
    org_ids = {r.organization_id for r in _scoped_responses(
        PulseResponse.objects.filter(send__pulse_check=check), allowed)}
    return render(request, 'pulse/check_detail.html', {
        'check': check, 'summary': results.summarize(responses), 'sends': sends,
        'by_org': _org_breakdown(responses) if org is None else [],
        'org': org, 'org_choices': Organization.objects.filter(pk__in=org_ids).order_by('name'),
        'can_manage': can_manage(check, allowed),
        'question_count': check.questions.count(),
    })


@staff_required
def send_detail(request, pk):
    send = get_object_or_404(PulseSend.objects.select_related('pulse_check'), pk=pk)
    check, allowed = _get_visible(request, send.pulse_check_id)
    qs = _scoped_responses(send.responses.all(), allowed)
    qs, org = _org_filter(request, qs, allowed)
    responses = list(qs.select_related('send', 'organization', 'user', 'contact'))
    org_ids = set(_scoped_responses(send.responses.all(), allowed).values_list('organization_id', flat=True))
    return render(request, 'pulse/send_detail.html', {
        'check': check, 'send': send, 'summary': results.summarize(responses),
        'responses': responses, 'org': org,
        'org_choices': Organization.objects.filter(pk__in=org_ids).order_by('name'),
        'by_org': _org_breakdown(responses) if org is None else [],
    })


@staff_required
@require_http_methods(['GET', 'POST'])
def check_send(request, pk):
    check, allowed = _get_visible(request, pk)
    if not can_manage(check, allowed):
        raise PermissionDenied('This pulse check includes clients outside your reach.')
    recipients, opted_out = audience.resolve(check)
    if request.method == 'POST':
        if not check.is_active:
            messages.error(request, 'Turn the pulse check on before sending it.')
            return redirect('pulse:check_detail', pk=check.pk)
        if not check.questions.exists():
            messages.error(request, 'Add at least one question first.')
            return redirect('pulse:check_edit', pk=check.pk)
        if not recipients:
            messages.error(request, 'Nobody to send to: the audience matches no one.')
            return redirect('pulse:check_send', pk=check.pk)
        send = send_check(check, by=request.user, request=request)
        if send.emailed_count < send.recipient_count:
            messages.warning(request, f'Sent to {send.recipient_count} people; {send.emailed_count} '
                                      f'e-mailed. Check Settings → Email if e-mail is not set up. '
                                      f'Portal users can still answer from the portal.')
        else:
            messages.success(request, f'Sent to {send.recipient_count} people.')
        return redirect('pulse:send_detail', pk=send.pk)
    orgs = {}
    for r in recipients:
        orgs.setdefault(r.organization.pk, {'organization': r.organization, 'people': []})
        orgs[r.organization.pk]['people'].append(r)
    return render(request, 'pulse/check_send.html', {
        'check': check, 'recipients': recipients, 'opted_out': opted_out,
        'by_org': sorted(orgs.values(), key=lambda x: x['organization'].name),
    })


@staff_required
@require_http_methods(['POST'])
def check_toggle(request, pk):
    check, allowed = _get_visible(request, pk)
    if not can_manage(check, allowed):
        raise PermissionDenied('This pulse check includes clients outside your reach.')
    check.is_active = not check.is_active
    check.save(update_fields=['is_active', 'updated_at'])
    _audit(request, 'update', check, f'Pulse check "{check.name}" turned {"on" if check.is_active else "off"}')
    return redirect('pulse:check_detail', pk=check.pk)


@staff_required
def opt_out_list(request):
    allowed = _allowed(request)
    rows = PulseOptOut.objects.all()
    if allowed is not None:
        # Only addresses of people at clients this staff member can reach.
        from accounts.models import Membership
        from assets.models import Contact
        emails = {e.lower() for e in Membership.objects.filter(
            organization_id__in=allowed).values_list('user__email', flat=True) if e}
        emails |= {e.lower() for e in Contact.objects.filter(
            organization_id__in=allowed).values_list('email', flat=True) if e}
        rows = rows.filter(email__in=emails)
    return render(request, 'pulse/opt_outs.html', {'rows': rows})

