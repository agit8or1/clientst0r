"""Staff pages for contract documents (MSP staff only; see permissions.py)."""
from __future__ import annotations

import io
import zipfile
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import forms, jobs, notify, services, signing
from . import permissions as perms
from .content import MERGE_FIELDS, ContentError, LINE_KINDS, SECTION_TYPES, normalize_sections
from .models import (BILLING_FREQUENCIES, KINDS, SIGNING_ORDERS, ContractAttachment, ContractClause,
                     ContractDocument, ContractEvent, ContractInvitation, ContractNotification, ContractSettings,
                     ContractSigner, ContractTemplate, ContractTemplateVersion, ContractVersion)
from .pdf import build_pdf, final_filename, issued_filename
from .sanitize import clean_html, plain_text
from .services import ContractError

D = ContractDocument


def staff_required(view):
    from functools import wraps

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        from psa.visibility import is_msp_staff
        if not is_msp_staff(request.user):
            raise PermissionDenied('Contract documents are available to MSP staff only.')
        return view(request, *args, **kwargs)
    return wrapper


def _contract(request, pk, perm=perms.VIEW):
    c = get_object_or_404(perms.scope(D.objects.select_related('organization', 'owner', 'account_manager',
                                                               'current_version'), request.user), pk=pk)
    if perm != perms.VIEW:
        perms.require(request.user, perm, c.organization_id)
    return c


def _err(request, exc):
    if isinstance(exc, ContentError):
        for e in exc.errors:
            messages.error(request, e)
    else:
        messages.error(request, str(exc))


def _current_org(request):
    return getattr(request, 'current_organization', None)


# --- dashboard -----------------------------------------------------------------

@staff_required
@require_GET
def dashboard(request):
    user = request.user
    if not perms.has_any(user, perms.VIEW):
        raise PermissionDenied("You don't have the 'contracts_view' permission.")
    qs = perms.scope(D.objects.select_related('organization', 'owner', 'current_version'), user)
    org = _current_org(request)
    f = {k: (request.GET.get(k) or '').strip() for k in ('q', 'client', 'owner', 'status', 'date_field',
                                                         'date_from', 'date_to')}
    if org is not None and not f['client'].isdigit():   # an explicit client filter wins
        from core.utils import descendant_org_ids
        qs = qs.filter(organization_id__in=descendant_org_ids(org))
    base = qs
    if f['q']:
        qs = qs.filter(Q(title__icontains=f['q']) | Q(reference__icontains=f['q'])
                       | Q(organization_name__icontains=f['q']) | Q(organization__name__icontains=f['q']))
    if f['client'].isdigit():
        qs = qs.filter(organization_id=int(f['client']))
    if f['owner'] == 'me':
        qs = qs.filter(owner=user)
    elif f['owner'].isdigit():
        qs = qs.filter(owner_id=int(f['owner']))
    if f['status'] in dict(D.STATUSES):
        qs = qs.filter(status=f['status'])
    elif f['status'] == 'open':
        qs = qs.filter(status__in=D.OPEN_FOR_SIGNING)
    date_field = {'created': 'created_at__date', 'effective': 'effective_date', 'expiration': 'expiration_date',
                  'sent': 'sent_at__date', 'signed': 'signed_at__date'}.get(f['date_field'], 'created_at__date')
    from datetime import date
    for key, op in (('date_from', 'gte'), ('date_to', 'lte')):
        try:
            if f[key]:
                qs = qs.filter(**{f'{date_field}__{op}': date.fromisoformat(f[key])})
        except ValueError:
            messages.warning(request, 'Dates must be YYYY-MM-DD.')
    live = qs.exclude(status__in=[D.VOIDED, D.SUPERSEDED, D.DECLINED, D.EXPIRED])
    sums = live.aggregate(one=Sum('one_time_total'), rec=Sum('recurring_total'))
    signed_sums = live.filter(status=D.SIGNED).aggregate(one=Sum('one_time_total'), rec=Sum('recurring_total'))
    page = Paginator(qs.order_by('-updated_at'), 50).get_page(request.GET.get('page'))
    now = timezone.now()
    today = timezone.localdate()
    follow_up = base.filter(status__in=D.OPEN_FOR_SIGNING, sent_at__lte=now - timedelta(days=3)).order_by('sent_at')[:8]
    recently_viewed = base.filter(last_viewed_at__isnull=False).order_by('-last_viewed_at')[:8]
    awaiting_approval = base.filter(status=D.PENDING_APPROVAL).order_by('updated_at')[:8]
    awaiting_counter = base.filter(status=D.PARTIALLY_SIGNED, invitations__role='internal',
                                   invitations__status=ContractInvitation.ACTIVE).distinct()[:8]
    upcoming = base.filter(status=D.SIGNED, expiration_date__gte=today,
                           expiration_date__lte=today + timedelta(days=90)).order_by('expiration_date')[:8]
    alerts = ContractNotification.objects.filter(user=user, read_at__isnull=True).select_related('contract')[:10]
    clients = _client_choices(request)
    return render(request, 'contracts/dashboard.html', {
        'page': page, 'f': f, 'statuses': D.STATUSES, 'sums': sums, 'signed_sums': signed_sums,
        'follow_up': follow_up, 'recently_viewed': recently_viewed, 'awaiting_approval': awaiting_approval,
        'awaiting_counter': awaiting_counter, 'upcoming': upcoming, 'alerts': alerts, 'clients': clients,
        'owners': _owner_choices(),
        'can_create': perms.has_any(user, perms.EDIT), 'has_any': base.exists(),
    })


def _client_choices(request):
    from core.models import Organization
    allowed = perms.allowed_orgs(request.user, perms.VIEW)
    qs = Organization.objects.filter(is_active=True)
    if allowed is not None:
        qs = qs.filter(pk__in=allowed)
    return qs.order_by('name')


def _owner_choices():
    from psa.visibility import msp_technicians
    return list(msp_technicians())


@staff_required
@require_POST
def notifications_read(request):
    ids = [int(x) for x in request.POST.getlist('id') if x.isdigit()] or None
    notify.mark_read(request.user, ids)
    return redirect(request.POST.get('next') if (request.POST.get('next') or '').startswith('/contracts/')
                    else 'contracts:dashboard')


# --- create --------------------------------------------------------------------

@staff_required
@require_http_methods(['GET', 'POST'])
def contract_new(request):
    user = request.user
    if not perms.has_any(user, perms.EDIT):
        raise PermissionDenied("You don't have the 'contracts_edit' permission.")
    clients = [o for o in _client_choices(request) if perms.has(user, perms.EDIT, o.pk)]
    org = _current_org(request)
    if request.method == 'POST':
        from core.models import Organization
        raw = request.POST.get('client', '')
        client = Organization.objects.filter(pk=int(raw), is_active=True).first() if raw.isdigit() else None
        if client is None or not perms.has(user, perms.EDIT, client.pk):
            messages.error(request, 'Choose a client you may create contracts for.')
            return redirect('contracts:new')
        start = request.POST.get('start', 'template')
        try:
            if start == 'clone':
                src = _contract(request, int(request.POST.get('source') or 0))
                if src.organization_id != client.pk:
                    perms.require(user, perms.VIEW, src.organization_id)
                c = services.clone_contract(src, user, request=request,
                                            title=plain_text(request.POST.get('title'), 255) or None)
                if c.organization_id != client.pk:
                    c.organization, c.organization_name = client, client.name
                    c.save(update_fields=['organization', 'organization_name'])
            else:
                tpl = None
                if start == 'template':
                    tid = request.POST.get('template', '')
                    tpl = perms.template_scope(ContractTemplate.objects.filter(is_active=True), user).filter(
                        pk=int(tid) if tid.isdigit() else 0).first()
                    if tpl is None or tpl.organization_id not in (None, client.pk):
                        messages.error(request, 'Choose a template for this client, or start blank.')
                        return redirect('contracts:new')
                c = services.create_contract(client, user, template=tpl, request=request,
                                             title=plain_text(request.POST.get('title'), 255))
        except (ContractError, Http404) as exc:
            _err(request, exc)
            return redirect('contracts:new')
        messages.success(request, f'Contract {c.reference} created. It saves automatically while you edit.')
        return redirect('contracts:edit', pk=c.pk)
    templates = perms.template_scope(ContractTemplate.objects.filter(is_active=True), user).select_related(
        'organization').order_by('organization_id', 'name')
    settings = ContractSettings.for_organization(org)
    recent = perms.scope(D.objects.all(), user).order_by('-updated_at')[:50]
    return render(request, 'contracts/new.html', {
        'clients': clients, 'selected_client': org.pk if org else None, 'templates': templates,
        'default_template': settings.default_template_id, 'recent': recent,
        'preselect_template': request.GET.get('template', ''), 'preselect_source': request.GET.get('source', ''),
    })


# --- detail --------------------------------------------------------------------

@staff_required
@require_GET
def contract_detail(request, pk):
    c = _contract(request, pk)
    flags = perms.flags_for(request.user, c)
    v = c.current_version
    versions = list(c.versions.order_by('-version_number').prefetch_related('approvals'))
    invitations = list(c.invitations.select_related('version', 'user').order_by('-version__version_number', 'order',
                                                                                 'pk'))
    sigs = {s.invitation_id: s for s in signing_models_signatures(c)}
    for inv in invitations:
        inv.sig = sigs.get(inv.pk)
    evs = c.events.select_related('actor', 'invitation').order_by('-at', '-pk')
    if not flags['view_audit']:
        evs = evs.exclude(kind__in=['code_failed'])
    issue_errors = services.issue_errors(c) if c.status == D.DRAFT else []
    settings = services.settings_for(c)
    can_countersign = [i for i in invitations if i.role == 'internal' and i.user_id == request.user.pk
                       and i.status == ContractInvitation.ACTIVE and i.version_id == c.current_version_id]
    return render(request, 'contracts/detail.html', {
        'c': c, 'v': v, 'flags': flags, 'versions': versions, 'invitations': invitations,
        'events': evs[:300], 'issue_errors': issue_errors, 'signing': services.signing_config(c, settings),
        'approval_ok': services.approval_valid(v) if v is not None else False, 'can_countersign': can_countersign,
        'jobs': c.jobs.exclude(status='done').order_by('-created_at')[:20],
        'attachments': c.attachments.filter(removed_at__isnull=True),
        'related_from': c.related_from.all()[:20], 'today': timezone.localdate(),
    })


def signing_models_signatures(c):
    from .models import ContractSignature
    return ContractSignature.objects.filter(version__contract=c).select_related('invitation')


# --- builder -------------------------------------------------------------------

def _builder_context(request, c, errors=None):
    clauses = perms.template_scope(ContractClause.objects.filter(is_active=True), request.user).filter(
        Q(organization__isnull=True) | Q(organization=c.organization)).order_by('category', 'title')
    staff = forms.staff_choices(c.organization)
    return {
        'c': c, 'sections': normalize_sections(c.sections), 'line_items': c.line_items or [],
        'signers': list(c.signers.all()), 'staff': staff, 'kinds': KINDS, 'frequencies': BILLING_FREQUENCIES,
        'orders': SIGNING_ORDERS, 'section_types': SECTION_TYPES, 'line_kinds': LINE_KINDS,
        'merge_fields': MERGE_FIELDS, 'clauses': clauses,
        'clause_data': {str(cl.pk): {'title': cl.title, 'body': cl.body} for cl in clauses},
        'settings': services.settings_for(c), 'errors': errors or [],
        'notify_ids': set(c.notify_users.values_list('pk', flat=True)),
        'attachments': c.attachments.filter(removed_at__isnull=True),
        'tri': [('', 'Use the setting'), ('yes', 'Yes'), ('no', 'No')],
        'blank_section': {'key': '', 'title': '', 'type': 'text', 'body': '', 'include': True},
        'issue_errors': services.issue_errors(c),
    }


@staff_required
@require_http_methods(['GET', 'POST'])
def contract_edit(request, pk):
    c = _contract(request, pk, perms.EDIT)
    if c.status != D.DRAFT:
        messages.info(request, 'Only a draft can be edited. Use Revise to start a new version.')
        return redirect('contracts:detail', pk=c.pk)
    if request.method == 'POST':
        data, errors = forms.parse_contract(request.POST, c)
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'contracts/builder.html', _builder_context(request, c, errors), status=400)
        try:
            services.save_draft(c, data, request.user, expected_revision=request.POST.get('draft_revision'),
                                request=request)
        except ContractError as exc:
            _err(request, exc)
            return render(request, 'contracts/builder.html', _builder_context(request, c), status=409)
        messages.success(request, 'Draft saved.')
        nxt = request.POST.get('next')
        if nxt == 'preview':
            return redirect('contracts:preview', pk=c.pk)
        if nxt == 'detail':
            return redirect('contracts:detail', pk=c.pk)
        return redirect('contracts:edit', pk=c.pk)
    return render(request, 'contracts/builder.html', _builder_context(request, c))


@staff_required
@require_POST
def contract_autosave(request, pk):
    c = _contract(request, pk, perms.EDIT)
    data, errors = forms.parse_contract(request.POST, c)
    if errors:
        return JsonResponse({'ok': False, 'errors': errors[:10]}, status=400)
    try:
        rev = services.save_draft(c, data, request.user, expected_revision=request.POST.get('draft_revision'),
                                  request=request)
    except ContractError as exc:
        return JsonResponse({'ok': False, 'errors': [str(exc)], 'conflict': True}, status=409)
    c.refresh_from_db()
    return JsonResponse({'ok': True, 'revision': rev, 'saved_at': timezone.localtime(c.draft_saved_at).strftime(
        '%H:%M:%S'), 'one_time_total': str(c.one_time_total), 'recurring_total': str(c.recurring_total)})


@staff_required
@require_GET
def contract_preview(request, pk):
    c = _contract(request, pk)
    if c.status == D.DRAFT:
        content, body, unresolved = services.preview(c)
        errors = services.issue_errors(c)
    else:
        v = c.current_version
        body, unresolved, errors = (v.rendered_html if v else ''), [], []
    from .content import DOC_CSS
    return render(request, 'contracts/preview.html', {'c': c, 'body': body, 'unresolved': unresolved,
                                                      'errors': errors, 'doc_css': DOC_CSS})


@staff_required
@require_GET
def contract_preview_pdf(request, pk):
    c = _contract(request, pk)
    content, _body, _unresolved = services.preview(c)
    pdf = build_pdf(content, draft=True)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{c.reference}-draft-preview.pdf"'
    resp['Cache-Control'] = 'private, no-store'
    return resp


# --- lifecycle actions -----------------------------------------------------------

@staff_required
@require_POST
def contract_submit(request, pk):
    c = _contract(request, pk, perms.EDIT)
    try:
        v = services.submit(c, request.user, request=request)
    except (ContractError, ContentError) as exc:
        _err(request, exc)
        return redirect('contracts:detail', pk=c.pk)
    c.refresh_from_db()
    if c.status == D.PENDING_APPROVAL:
        messages.success(request, f'Version {v.version_number} is frozen and waiting for internal approval.')
    else:
        messages.success(request, f'Version {v.version_number} is frozen and ready to send.')
    return redirect('contracts:detail', pk=c.pk)


@staff_required
@require_http_methods(['GET', 'POST'])
def contract_approve(request, pk):
    c = _contract(request, pk, perms.APPROVE)
    v = c.current_version
    if c.status != D.PENDING_APPROVAL or v is None:
        messages.info(request, 'This contract is not waiting for approval.')
        return redirect('contracts:detail', pk=c.pk)
    if request.method == 'POST':
        try:
            services.decide(c, request.user, approve=request.POST.get('decision') == 'approve',
                            content_hash=request.POST.get('content_hash', ''),
                            comment=plain_text(request.POST.get('comment'), 2000), request=request)
        except ContractError as exc:
            _err(request, exc)
            return redirect('contracts:approve', pk=c.pk)
        return redirect('contracts:detail', pk=c.pk)
    from .content import DOC_CSS
    return render(request, 'contracts/approve.html', {'c': c, 'v': v, 'doc_css': DOC_CSS})


@staff_required
@require_http_methods(['GET', 'POST'])
def contract_send(request, pk):
    c = _contract(request, pk, perms.SEND)
    if c.status != D.READY:
        messages.info(request, 'Only a contract that is ready to send can be sent.')
        return redirect('contracts:detail', pk=c.pk)
    if request.method == 'POST':
        try:
            invs = services.send(c, request.user, email=request.POST.get('delivery') != 'links', request=request)
        except ContractError as exc:
            _err(request, exc)
            return redirect('contracts:send', pk=c.pk)
        messages.success(request, f'Sent to {len(invs)} signer(s). E-mail status shows on each invitation '
                                  '("accepted by the mail server" is not proof of delivery).')
        return redirect('contracts:detail', pk=c.pk)
    from .content import ordered_signers
    return render(request, 'contracts/send.html', {
        'c': c, 'v': c.current_version, 'signers': ordered_signers(list(c.signers.all())),
        'signing': services.signing_config(c), 'approval_ok': services.approval_valid(c.current_version)})


@staff_required
@require_http_methods(['GET', 'POST'])
def contract_revise(request, pk):
    c = _contract(request, pk, perms.EDIT)
    if request.method == 'POST':
        try:
            services.revise(c, request.user, reason=plain_text(request.POST.get('reason'), 255), request=request)
        except ContractError as exc:
            _err(request, exc)
            return redirect('contracts:detail', pk=c.pk)
        messages.success(request, 'The contract is a draft again. Issuing it creates a new version.')
        return redirect('contracts:edit', pk=c.pk)
    open_invs = c.invitations.filter(version=c.current_version, status__in=ContractInvitation.OPEN).count() \
        if c.current_version else 0
    signed = c.current_version.signatures.count() if c.current_version else 0
    return render(request, 'contracts/confirm.html', {
        'c': c, 'action': 'revise', 'title': f'Revise {c.reference}',
        'open_invs': open_invs, 'signed': signed})


@staff_required
@require_http_methods(['GET', 'POST'])
def contract_void(request, pk):
    c = _contract(request, pk, perms.VOID)
    if request.method == 'POST':
        try:
            services.void(c, request.user, request.POST.get('reason', ''), request=request)
        except ContractError as exc:
            _err(request, exc)
            return redirect('contracts:void', pk=c.pk)
        messages.success(request, f'{c.reference} is voided. Its history and signatures are kept.')
        return redirect('contracts:detail', pk=c.pk)
    return render(request, 'contracts/confirm.html', {'c': c, 'action': 'void', 'title': f'Void {c.reference}'})


@staff_required
@require_POST
def contract_derive(request, pk, how):
    c = _contract(request, pk, perms.EDIT)
    try:
        if how == 'clone':
            n = services.clone_contract(c, request.user, request=request)
        elif how == 'amend':
            n = services.amend(c, request.user, request=request)
        elif how == 'renew':
            n = services.renew(c, request.user, request=request)
        elif how == 'replace':
            n = services.renew(c, request.user, request=request, replace=True)
        else:
            raise Http404
    except ContractError as exc:
        _err(request, exc)
        return redirect('contracts:detail', pk=c.pk)
    messages.success(request, f'{n.reference} created from {c.reference}.')
    return redirect('contracts:edit', pk=n.pk)


@staff_required
@require_POST
def contract_billing(request, pk):
    c = _contract(request, pk, perms.EDIT)
    try:
        bc = services.create_billing_contract(c, request.user, request=request)
    except ContractError as exc:
        _err(request, exc)
        return redirect('contracts:detail', pk=c.pk)
    messages.success(request, f'Draft billing contract created. Review it in PSA → Contracts (#{bc.pk}).')
    return redirect('contracts:detail', pk=c.pk)


@staff_required
@require_POST
def contract_delete(request, pk):
    c = _contract(request, pk, perms.EDIT)
    if c.status != D.DRAFT or c.versions.exists():
        messages.error(request, 'Only a draft that was never issued can be deleted; void the others.')
        return redirect('contracts:detail', pk=c.pk)
    ref = c.reference
    c.delete()
    messages.success(request, f'Draft {ref} deleted.')
    return redirect('contracts:dashboard')


# --- attachments -----------------------------------------------------------------

@staff_required
@require_POST
def attachment_upload(request, pk):
    c = _contract(request, pk, perms.EDIT)
    f = request.FILES.get('file')
    if not f:
        messages.error(request, 'Choose a file to attach.')
    else:
        try:
            services.add_attachment(c, f, request.user, request=request)
            messages.success(request, f'Attached {f.name}.')
        except ContractError as exc:
            _err(request, exc)
    return redirect('contracts:edit', pk=c.pk) if c.status == D.DRAFT else redirect('contracts:detail', pk=c.pk)


@staff_required
@require_POST
def attachment_remove(request, pk):
    a = get_object_or_404(ContractAttachment, pk=pk)
    c = _contract(request, a.contract_id, perms.EDIT)
    try:
        services.remove_attachment(a, request.user, request=request)
    except ContractError as exc:
        _err(request, exc)
    return redirect('contracts:edit', pk=c.pk)


def _download(data, name, ctype, inline=False):
    from django.utils.text import get_valid_filename
    resp = HttpResponse(bytes(data), content_type=ctype)
    resp['Content-Disposition'] = f'{"inline" if inline else "attachment"}; filename="{get_valid_filename(name)}"'
    resp['Cache-Control'] = 'private, no-store'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


@staff_required
@require_GET
def attachment_download(request, pk):
    a = get_object_or_404(ContractAttachment, pk=pk)
    _contract(request, a.contract_id)
    inline = a.content_type in ('application/pdf', 'image/png', 'image/jpeg')
    return _download(a.data, a.name, a.content_type if inline else 'application/octet-stream', inline=inline)


# --- versions ----------------------------------------------------------------------

def _version(request, pk):
    v = get_object_or_404(ContractVersion.objects.select_related('contract'), pk=pk)
    _contract(request, v.contract_id)
    return v


@staff_required
@require_GET
def version_pdf(request, pk, kind):
    v = _version(request, pk)
    if kind == 'signed':
        if not v.final_pdf:
            raise Http404('The signed PDF is not ready yet.')
        return _download(v.final_pdf, final_filename(v), 'application/pdf', inline=True)
    if not v.pdf:
        raise Http404('This version has no PDF.')
    return _download(v.pdf, issued_filename(v), 'application/pdf', inline=True)


@staff_required
@require_GET
def version_snapshot(request, pk):
    v = _version(request, pk)
    resp = HttpResponse(v.snapshot_html, content_type='text/html; charset=utf-8')
    resp['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    resp['Cache-Control'] = 'private, no-store'
    return resp


@staff_required
@require_GET
def version_evidence(request, pk):
    v = _version(request, pk)
    perms.require(request.user, perms.AUDIT, v.contract.organization_id)
    files = {'content.json': v.content_json(), 'snapshot.html': v.snapshot_html.encode('utf-8')}
    if v.pdf:
        files['issued.pdf'] = bytes(v.pdf)
    if v.final_pdf:
        files['signed.pdf'] = bytes(v.final_pdf)
    if v.certificate_json:
        files['certificate.json'] = v.certificate_json.encode('utf-8')
    for s in v.signatures.order_by('pk'):
        files[f'signatures/{s.pk}-evidence.json'] = s.evidence_json()
    for a in v.contract.attachments.all():
        if any(x.get('id') == a.pk for x in v.content.get('attachments', [])):
            files[f'exhibits/{a.pk}-{a.name}'] = bytes(a.data)
    from .models import sha256
    sums = ''.join(f'{sha256(d)}  {n}\n' for n, d in sorted(files.items()))
    sums += f'# content.json sha256 = content_hash {v.content_hash}\n# snapshot.html sha256 = {v.snapshot_hash}\n'
    files['SHA256SUMS'] = sums.encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    from . import events
    events.record(v.contract, 'downloaded', version=v, actor=request.user, request=request,
                  message='Evidence package downloaded')
    return _download(buf.getvalue(), f'{v.contract.reference}-v{v.version_number}-evidence.zip', 'application/zip')


# --- invitations -------------------------------------------------------------------

def _invitation(request, pk, perm=perms.SEND):
    inv = get_object_or_404(ContractInvitation.objects.select_related('contract', 'version'), pk=pk)
    _contract(request, inv.contract_id, perm)
    return inv


@staff_required
@require_POST
def invitation_resend(request, pk):
    inv = _invitation(request, pk)
    try:
        services.resend(inv, request.user, request=request)
        inv.refresh_from_db()
        messages.success(request, f'Invitation to {inv.email}: {inv.get_delivery_status_display().lower()}.')
    except ContractError as exc:
        _err(request, exc)
    return redirect('contracts:detail', pk=inv.contract_id)


@staff_required
@require_POST
def invitation_link(request, pk):
    inv = _invitation(request, pk)
    try:
        link = services.copy_link(inv, request.user, request=request)
    except ContractError as exc:
        _err(request, exc)
        return redirect('contracts:detail', pk=inv.contract_id)
    resp = render(request, 'contracts/link.html', {'inv': inv, 'c': inv.contract, 'link': link})
    resp['Cache-Control'] = 'no-store'
    return resp


@staff_required
@require_POST
def invitation_revoke(request, pk):
    inv = _invitation(request, pk)
    services.revoke(inv, request.user, reason=plain_text(request.POST.get('reason'), 255) or 'Revoked by staff',
                    request=request)
    messages.success(request, f'The links sent to {inv.email} no longer work.')
    return redirect('contracts:detail', pk=inv.contract_id)


@staff_required
@require_http_methods(['GET', 'POST'])
def invitation_replace(request, pk):
    inv = _invitation(request, pk)
    if request.method == 'POST':
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        name = plain_text(request.POST.get('name'), 200)
        email = (request.POST.get('email') or '').strip()
        try:
            validate_email(email)
            if not name:
                raise ValidationError('name')
            services.replace_invitation(inv, request.user, name=name, email=email,
                                        title=plain_text(request.POST.get('title'), 200), request=request)
        except ValidationError:
            messages.error(request, 'Enter a name and a valid e-mail address.')
            return redirect('contracts:invitation_replace', pk=inv.pk)
        except ContractError as exc:
            _err(request, exc)
            return redirect('contracts:detail', pk=inv.contract_id)
        messages.success(request, 'Invitation replaced. The old links no longer work.')
        return redirect('contracts:detail', pk=inv.contract_id)
    return render(request, 'contracts/replace_invitation.html', {'inv': inv, 'c': inv.contract})


@staff_required
@require_GET
def invitation_countersign(request, pk):
    """Open the signing page for the signed-in internal countersigner."""
    inv = _invitation(request, pk, perms.VIEW)
    if inv.role != 'internal' or inv.user_id != request.user.pk:
        raise PermissionDenied('Only the named countersigner can sign here.')
    signing.bind_session(request, inv, staff=True)
    return redirect('contract_sign:page', public_id=inv.public_id)


# --- templates ---------------------------------------------------------------------

@staff_required
@require_GET
def template_list(request):
    if not perms.has_any(request.user, perms.VIEW):
        raise PermissionDenied
    qs = perms.template_scope(ContractTemplate.objects.select_related('organization'), request.user)
    org = _current_org(request)
    if org is not None:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization=org))
    show = request.GET.get('show', 'active')
    if show != 'all':
        qs = qs.filter(is_active=True)
    return render(request, 'contracts/templates_list.html', {
        'templates': qs.order_by('organization_id', 'name'), 'show': show,
        'can_manage_global': perms.has_global(request.user, perms.TEMPLATES),
        'can_manage_any': perms.has_any(request.user, perms.TEMPLATES), 'org': org,
        'clients': [o for o in _client_choices(request) if perms.has(request.user, perms.TEMPLATES, o.pk)]})


def _template_form_ctx(request, tpl, data, errors=None, org=None):
    return {'tpl': tpl, 'data': data, 'sections': data.get('sections') or [], 'line_items': data.get('line_items') or [],
            'defaults': data.get('defaults') or {}, 'kinds': KINDS, 'frequencies': BILLING_FREQUENCIES,
            'section_types': SECTION_TYPES, 'line_kinds': LINE_KINDS, 'merge_fields': MERGE_FIELDS,
            'clauses': perms.template_scope(ContractClause.objects.filter(is_active=True), request.user),
            'clause_data': {str(cl.pk): {'title': cl.title, 'body': cl.body}
                            for cl in perms.template_scope(ContractClause.objects.filter(is_active=True), request.user)},
            'errors': errors or [], 'org': org, 'can_edit': tpl is None or perms.can_manage_template(request.user, tpl),
            'versions': tpl.versions.order_by('-version_number')[:30] if tpl else [],
            'blank_section': {'key': '', 'title': '', 'type': 'text', 'body': '', 'include': True},
            'can_global': perms.has_global(request.user, perms.TEMPLATES),
            'clients': [o for o in _client_choices(request) if perms.has(request.user, perms.TEMPLATES, o.pk)]}


@staff_required
@require_http_methods(['GET', 'POST'])
def template_edit(request, pk=None):
    from core.models import Organization
    tpl = None
    if pk is not None:
        tpl = get_object_or_404(perms.template_scope(ContractTemplate.objects.all(), request.user), pk=pk)
    if request.method == 'POST':
        if tpl is None:
            scope = request.POST.get('scope', '')
            org = Organization.objects.filter(pk=int(scope)).first() if scope.isdigit() else None
            if org is None and not perms.has_global(request.user, perms.TEMPLATES):
                raise PermissionDenied('Only staff who manage templates for every customer can add starters.')
            if org is not None:
                perms.require(request.user, perms.TEMPLATES, org.pk)
        else:
            if not perms.can_manage_template(request.user, tpl):
                raise PermissionDenied
            org = tpl.organization
        parsed, errors = forms.parse_template(request.POST)
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'contracts/template_form.html',
                          _template_form_ctx(request, tpl, parsed['data'], errors, org), status=400)
        from django.db import transaction
        with transaction.atomic():
            if tpl is None:
                tpl = ContractTemplate.objects.create(organization=org, name=parsed['name'], kind=parsed['kind'],
                                                      description=parsed['description'], created_by=request.user)
            else:
                tpl = ContractTemplate.objects.select_for_update().get(pk=tpl.pk)
                tpl.name, tpl.kind, tpl.description = parsed['name'], parsed['kind'], parsed['description']
                tpl.save()
            n = (tpl.versions.order_by('-version_number').values_list('version_number', flat=True).first() or 0) + 1
            ContractTemplateVersion.objects.create(template=tpl, version_number=n, data=parsed['data'],
                                                   created_by=request.user,
                                                   note=plain_text(request.POST.get('note'), 255))
        messages.success(request, f'Saved "{tpl.name}" as version {n}. Contracts already created keep their text.')
        return redirect('contracts:template_edit', pk=tpl.pk)
    org = tpl.organization if tpl else _current_org(request)
    data = tpl.latest_version.data if tpl and tpl.latest_version else {'sections': normalize_sections([
        {'title': 'Agreement', 'body': '<p></p>'}, {'title': 'Signatures', 'type': 'signatures', 'body': ''}])}
    return render(request, 'contracts/template_form.html', _template_form_ctx(request, tpl, data, org=org))


@staff_required
@require_GET
def template_version(request, pk, number):
    tpl = get_object_or_404(perms.template_scope(ContractTemplate.objects.all(), request.user), pk=pk)
    tv = get_object_or_404(tpl.versions, version_number=number)
    return render(request, 'contracts/template_version.html', {'tpl': tpl, 'tv': tv,
                                                               'sections': tv.data.get('sections') or []})


@staff_required
@require_POST
def template_clone(request, pk):
    from core.models import Organization
    tpl = get_object_or_404(perms.template_scope(ContractTemplate.objects.all(), request.user), pk=pk)
    raw = request.POST.get('organization', '')
    org = Organization.objects.filter(pk=int(raw)).first() if raw.isdigit() else None
    if org is None:
        messages.error(request, 'Choose the customer to copy the template to.')
        return redirect('contracts:template_list')
    perms.require(request.user, perms.TEMPLATES, org.pk)
    src = tpl.latest_version
    new = ContractTemplate.objects.create(organization=org, name=f'{tpl.name} — {org.name}'[:200], kind=tpl.kind,
                                          description=tpl.description, is_sample=tpl.is_sample, cloned_from=tpl,
                                          created_by=request.user)
    ContractTemplateVersion.objects.create(template=new, version_number=1, data=src.data if src else {},
                                           created_by=request.user, note=f'Copied from "{tpl.name}"')
    messages.success(request, f'Copied to {org.name} as a private template.')
    return redirect('contracts:template_edit', pk=new.pk)


@staff_required
@require_POST
def template_toggle(request, pk):
    tpl = get_object_or_404(perms.template_scope(ContractTemplate.objects.all(), request.user), pk=pk)
    if not perms.can_manage_template(request.user, tpl):
        raise PermissionDenied
    tpl.is_active = not tpl.is_active
    tpl.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'"{tpl.name}" is now {"active" if tpl.is_active else "inactive"}.')
    return redirect('contracts:template_list')


# --- clauses -----------------------------------------------------------------------

@staff_required
@require_GET
def clause_list(request):
    qs = perms.template_scope(ContractClause.objects.select_related('organization'), request.user)
    org = _current_org(request)
    if org is not None:
        qs = qs.filter(Q(organization__isnull=True) | Q(organization=org))
    return render(request, 'contracts/clauses_list.html', {
        'clauses': qs.order_by('-is_active', 'category', 'title'),
        'can_manage_any': perms.has_any(request.user, perms.TEMPLATES)})


@staff_required
@require_http_methods(['GET', 'POST'])
def clause_edit(request, pk=None):
    from core.models import Organization
    cl = None
    if pk is not None:
        cl = get_object_or_404(perms.template_scope(ContractClause.objects.all(), request.user), pk=pk)
        if not perms.can_manage_template(request.user, cl):
            raise PermissionDenied
    if request.method == 'POST':
        if cl is None:
            scope = request.POST.get('scope', '')
            org = Organization.objects.filter(pk=int(scope)).first() if scope.isdigit() else None
            if org is None and not perms.has_global(request.user, perms.TEMPLATES):
                raise PermissionDenied
            if org is not None:
                perms.require(request.user, perms.TEMPLATES, org.pk)
            cl = ContractClause(organization=org, created_by=request.user)
        cl.title = plain_text(request.POST.get('title'), 200)
        cl.category = plain_text(request.POST.get('category'), 100)
        cl.body = clean_html(request.POST.get('body', ''))
        cl.is_optional = request.POST.get('is_optional') == 'on'
        cl.is_active = request.POST.get('is_active', 'on') == 'on'
        if not cl.title or not cl.body:
            messages.error(request, 'Enter a title and the clause text.')
        else:
            cl.save()
            messages.success(request, f'Clause "{cl.title}" saved.')
            return redirect('contracts:clause_list')
    return render(request, 'contracts/clause_form.html', {
        'cl': cl, 'merge_fields': MERGE_FIELDS, 'can_global': perms.has_global(request.user, perms.TEMPLATES),
        'clients': [o for o in _client_choices(request) if perms.has(request.user, perms.TEMPLATES, o.pk)],
        'org': _current_org(request)})


# --- settings ----------------------------------------------------------------------

@staff_required
@require_http_methods(['GET', 'POST'])
def settings_view(request):
    from accounts.models import RoleTemplate
    from core.models import Organization
    raw = request.POST.get('org') if request.method == 'POST' else request.GET.get('org')
    raw = raw or ''
    org = Organization.objects.filter(pk=int(raw)).first() if raw.isdigit() else None
    if raw == '' and _current_org(request) is not None:   # no explicit choice: the client in context
        org = _current_org(request)
    if org is None:
        if not perms.has_global(request.user, perms.SETTINGS):
            raise PermissionDenied('Changing the deployment defaults needs contract settings for every customer.')
        row = ContractSettings.deployment_default()
    else:
        perms.require(request.user, perms.SETTINGS, org.pk)
        row = ContractSettings.objects.filter(organization=org).first()
    overriding = org is None or row is not None
    if request.method == 'POST':
        if org is not None and request.POST.get('action') == 'reset':
            ContractSettings.objects.filter(organization=org).delete()
            messages.success(request, f'{org.name} now uses the deployment defaults.')
            return redirect(f'{reverse("contracts:settings")}?org={org.pk}')
        if row is None:
            row = ContractSettings.override_for(org)
        errors = _save_settings(request, row)
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            messages.success(request, 'Contract settings saved.')
            return redirect(f'{reverse("contracts:settings")}?org={org.pk if org else "global"}')
    shown = row or ContractSettings.for_organization(org)
    staff = forms.staff_choices(org)
    templates = perms.template_scope(ContractTemplate.objects.filter(is_active=True), request.user)
    if org is not None:
        templates = templates.filter(Q(organization__isnull=True) | Q(organization=org))
    else:
        templates = templates.filter(organization__isnull=True)
    return render(request, 'contracts/settings.html', {
        's': shown, 'org': org, 'overriding': overriding, 'staff': staff,
        'roles': RoleTemplate.objects.filter(organization__isnull=True).order_by('name'),
        'templates': templates, 'orders': SIGNING_ORDERS,
        'notify_user_ids': set(shown.notify_users.values_list('pk', flat=True)),
        'notify_role_ids': set(shown.notify_roles.values_list('pk', flat=True)),
        'clause_choices': perms.template_scope(ContractClause.objects.filter(is_active=True), request.user).filter(
            Q(organization__isnull=True) | Q(organization=org)).order_by('category', 'title'),
        'default_clause_ids': set(shown.default_clauses.values_list('pk', flat=True)),
        'clients': [o for o in _client_choices(request) if perms.has(request.user, perms.SETTINGS, o.pk)],
        'can_global': perms.has_global(request.user, perms.SETTINGS)})


def _save_settings(request, row):
    import re
    from accounts.models import RoleTemplate
    p = request.POST
    errors = []
    for f in ('provider_name', 'provider_email', 'provider_phone', 'provider_website', 'invitation_subject',
              'reminder_subject', 'completed_subject', 'intent_text'):
        setattr(row, f, plain_text(p.get(f), row._meta.get_field(f).max_length))
    for f in ('provider_address', 'email_footer', 'consent_text', 'invitation_body', 'reminder_body',
              'completed_body'):
        setattr(row, f, plain_text(p.get(f), 10000))
    if row.provider_email:
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        try:
            validate_email(row.provider_email)
        except ValidationError:
            errors.append('Provider e-mail is not valid.')
    color = (p.get('brand_color') or '').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        errors.append('Brand colour must look like #1f4e79.')
    else:
        row.brand_color = color
    for f in ('notify_owner', 'notify_account_manager', 'notify_in_app', 'notify_email', 'notify_repeat_views',
              'reminders_enabled', 'require_email_verification', 'require_countersignature',
              'require_internal_approval', 'allow_self_approval'):
        setattr(row, f, p.get(f) == 'on')
    limits = {'repeat_view_cooldown_minutes': (5, 10080), 'reminder_first_after_days': (1, 60),
              'reminder_interval_days': (1, 60), 'reminder_max': (0, 20), 'invitation_expiry_days': (1, 365),
              'acceptance_deadline_days': (0, 365), 'renewal_alert_days': (0, 365),
              'expiration_alert_days': (0, 365), 'access_log_retention_days': (0, 3650)}
    for f, (lo, hi) in limits.items():
        v = forms._int(p, f, errors, row._meta.get_field(f).verbose_name.capitalize(), lo, hi)
        if v is not None:
            setattr(row, f, v)
    if p.get('signing_order') in dict(SIGNING_ORDERS):
        row.signing_order = p['signing_order']
    if not row.consent_text.strip():
        errors.append('The electronic-signature consent wording cannot be empty.')
    tid = p.get('default_template', '')
    row.default_template = perms.template_scope(ContractTemplate.objects.all(), request.user).filter(
        pk=int(tid)).first() if tid.isdigit() else None
    if errors:
        return errors
    row.updated_by = request.user
    row.save()
    staff = {u.pk: u for u in forms.staff_choices(row.organization)}
    row.notify_users.set([staff[int(x)] for x in p.getlist('notify_users') if x.isdigit() and int(x) in staff])
    row.default_clauses.set(perms.template_scope(ContractClause.objects.filter(
        pk__in=[int(x) for x in p.getlist('default_clauses') if x.isdigit()]), request.user).filter(
        Q(organization__isnull=True) | Q(organization=row.organization)))
    row.notify_roles.set(RoleTemplate.objects.filter(organization__isnull=True,
                                                     pk__in=[int(x) for x in p.getlist('notify_roles') if x.isdigit()]))
    return []
