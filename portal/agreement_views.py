"""
Customer portal: agreements (MSAs, SOWs, policy acknowledgments) for the
portal user's own customer — read the exact current version, sign or
acknowledge it, and download the evidence of any signature made for that
customer. Another customer's agreements and evidence are 404.
"""
from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from docs import agreements
from docs.agreement_models import Agreement, AgreementSignature

from .views import portal_required


def _own(request, pk):
    org = request.portal_membership.organization
    agreement = get_object_or_404(Agreement.objects.select_related('document'), pk=pk, organization=org,
                                  document__isnull=False)
    return agreement


@portal_required
def agreement_list(request):
    org = request.portal_membership.organization
    rows = []
    for a in Agreement.objects.filter(organization=org, is_active=True, document__isnull=False).order_by('title'):
        rev = agreements.current_revision(a)
        if rev is None:
            continue
        rows.append({'agreement': a, 'revision': rev, 'needs': agreements.needs_signature(a, request.user)})
    mine = (AgreementSignature.objects.filter(organization=org)
            .select_related('revision__agreement').order_by('-signed_at')[:100])
    return render(request, 'portal/agreements_list.html', {'rows': rows, 'signatures': mine,
                                                           'organization': org})


@portal_required
def agreement_detail(request, pk):
    org = request.portal_membership.organization
    agreement = _own(request, pk)
    rev = agreements.current_revision(agreement)
    if rev is None:
        raise Http404('This agreement is not open for signing.')
    if request.method == 'POST':
        try:
            agreements.sign(agreement, request.POST.get('revision'), request.POST.get('content_hash'),
                            request.user, org, name=request.POST.get('signed_by_name'),
                            email=request.POST.get('signed_by_email'), title=request.POST.get('signed_by_title'),
                            signature_data=request.POST.get('signature_data'),
                            accepted=request.POST.get('accept') == 'on', request=request)
        except agreements.AgreementError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Thank you. Version {rev.version_number} is {agreement.verb_past}.')
        return redirect('portal:agreement_detail', pk=agreement.pk)
    signatures = AgreementSignature.objects.filter(revision__agreement=agreement, organization=org) \
        .select_related('revision').order_by('-signed_at')
    return render(request, 'portal/agreement_detail.html', {
        'agreement': agreement, 'rev': rev, 'needs': agreements.needs_signature(agreement, request.user),
        'may_sign': agreements.may_sign(agreement, request.user),
        'signer_text': agreements.signer_rule_text(agreement),
        'signatures': signatures, 'organization': org,
    })


@portal_required
def agreement_file(request, pk):
    """The exact file of one revision of an uploaded-file agreement of the
    portal user's own customer."""
    from docs.agreement_models import AgreementRevision
    from docs.agreement_views import snapshot_response
    org = request.portal_membership.organization
    rev = get_object_or_404(AgreementRevision.objects.select_related('agreement'), pk=pk,
                            agreement__organization=org)
    return snapshot_response(rev, 'file')


@portal_required
def agreement_evidence(request, pk):
    org = request.portal_membership.organization
    sig = get_object_or_404(AgreementSignature.objects.select_related('revision__agreement'), pk=pk,
                            organization=org)
    from docs.agreement_views import evidence_response
    agreements._audit(request.user, 'export', 'docs.AgreementSignature', sig.pk,
                      f'Portal download of evidence for {sig}', org, request)
    return evidence_response(sig)
