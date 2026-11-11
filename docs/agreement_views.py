"""
Staff side of version-specific agreements (MSAs, SOWs, policy
acknowledgments): make a document an agreement, see who signed or
acknowledged which version and who is outstanding, and download the
evidence of any signature.

MSP staff only, and only for customers whose documents they may view
(`docs_view` at that customer). Making or closing an agreement needs
`docs_publish` there, the same as publishing the document.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from . import agreements
from .agreement_models import Agreement, AgreementRevision, AgreementSignature
from .permissions import can_publish


def _staff(user):
    from psa.visibility import is_msp_staff
    return is_msp_staff(user)


def _may_view_org(user, organization_id):
    from accounts.permission_utils import has_perm_for_org
    return organization_id is not None and _staff(user) and has_perm_for_org(user, organization_id, 'docs_view')


def _visible_agreements(user):
    from accounts.permission_utils import orgs_with_perm
    if not _staff(user):
        return Agreement.objects.none()
    qs = Agreement.objects.select_related('document', 'organization')
    allowed = orgs_with_perm(user, 'docs_view')
    return qs if allowed is None else qs.filter(organization_id__in=allowed)


@login_required
def agreement_list(request):
    if not _staff(request.user):
        raise Http404()
    rows = []
    for a in _visible_agreements(request.user).order_by('organization_name', 'title'):
        rows.append({'agreement': a, 'status': agreements.status(a)})
    return render(request, 'docs/agreements/list.html', {'rows': rows})


@login_required
def agreement_manage(request, pk):
    from .views import _get_accessible_document
    document = _get_accessible_document(request, pk)
    if not _staff(request.user) or not _may_view_org(request.user, document.organization_id):
        raise Http404()
    agreement = Agreement.objects.filter(document=document).first()
    if request.method == 'POST':
        if not can_publish(request.user, document):
            messages.error(request, 'Making or closing an agreement needs permission to publish this document.')
            return redirect('docs:agreement_manage', pk=document.pk)
        action = request.POST.get('action')
        try:
            if action == 'setup':
                agreement = agreements.make_agreement(
                    document, request.user, request.POST.get('kind', 'msa'),
                    request.POST.get('mode', Agreement.SIGNATURE), request.POST.get('audience', Agreement.ONE),
                    request=request, signer_rule=request.POST.get('signer_rule', Agreement.ANY),
                    allowed_signers=request.POST.getlist('allowed_signers'),
                    reminders_enabled=request.POST.get('reminders_enabled') == 'on',
                    reminder_interval_days=request.POST.get('reminder_interval_days') or None)
                messages.success(request, 'Saved. Customer portal users can now see and '
                                          f'{agreement.verb} the current version.')
            elif action in ('close', 'reopen') and agreement is not None:
                agreement.is_active = action == 'reopen'
                agreement.save(update_fields=['is_active'])
                if agreement.is_active:
                    agreements.ensure_revision(agreement, request.user)
                agreements._audit(request.user, 'update', 'docs.Agreement', agreement.pk,
                                  f'{"Reopened" if agreement.is_active else "Closed"} agreement "{agreement.title}"',
                                  agreement.organization, request)
                messages.success(request, 'Reopened for signing.' if agreement.is_active else
                                 'Closed. Existing signatures and evidence are kept.')
        except agreements.AgreementError as exc:
            messages.error(request, str(exc))
        return redirect('docs:agreement_manage', pk=document.pk)
    return render(request, 'docs/agreements/manage.html', {
        'document': document, 'agreement': agreement,
        'status': agreements.status(agreement) if agreement else None,
        'live': agreements.is_live(document),
        'can_publish_doc': can_publish(request.user, document),
        'kinds': Agreement.KINDS, 'modes': Agreement.MODES, 'audiences': Agreement.AUDIENCES,
        'signer_rules': Agreement.SIGNER_RULES,
        'members': agreements._customer_members(document.organization_id),
        'allowed_ids': set(agreement.allowed_signers.values_list('pk', flat=True)) if agreement else set(),
        'signer_text': agreements.signer_rule_text(agreement) if agreement else '',
    })


def _signature_for_staff(request, pk):
    sig = get_object_or_404(AgreementSignature.objects.select_related('revision__agreement'), pk=pk)
    if not _may_view_org(request.user, sig.organization_ref):
        raise Http404()
    return sig


def _revision_for_staff(request, pk):
    rev = get_object_or_404(AgreementRevision.objects.select_related('agreement'), pk=pk)
    if not _may_view_org(request.user, rev.agreement.organization_id):
        raise Http404()
    return rev


def evidence_response(sig):
    payload = agreements.evidence_zip(sig)
    response = HttpResponse(payload, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{agreements.evidence_filename(sig)}"'
    response['Cache-Control'] = 'private, no-store'
    return response


def snapshot_response(rev, fmt):
    if fmt == 'file':
        if not (rev.is_file and rev.file_data):
            raise Http404()
        from django.utils.http import content_disposition_header
        response = HttpResponse(bytes(rev.file_data), content_type='application/octet-stream')
        response['Content-Disposition'] = content_disposition_header(
            True, f'v{rev.version_number}-{agreements.revision_file_name(rev)}')
        response['X-Content-Type-Options'] = 'nosniff'
    elif fmt == 'pdf':
        if not rev.pdf:
            raise Http404()
        response = HttpResponse(bytes(rev.pdf), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="agreement-{rev.agreement_id}-v{rev.version_number}.pdf"'
    else:
        response = HttpResponse(rev.snapshot_html.encode('utf-8'), content_type='text/html; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="agreement-{rev.agreement_id}-v{rev.version_number}.html"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def signature_evidence(request, pk):
    sig = _signature_for_staff(request, pk)
    agreements._audit(request.user, 'export', 'docs.AgreementSignature', sig.pk,
                      f'Downloaded evidence for {sig}', sig.organization, request)
    return evidence_response(sig)


@login_required
def revision_view(request, pk):
    rev = _revision_for_staff(request, pk)
    return render(request, 'docs/agreements/revision.html', {
        'rev': rev, 'agreement': rev.agreement, 'checks': rev.verify(),
        'signatures': rev.signatures.order_by('signed_at'),
    })


@login_required
def revision_snapshot(request, pk, fmt):
    if fmt not in ('html', 'pdf', 'file'):
        raise Http404()
    return snapshot_response(_revision_for_staff(request, pk), fmt)
