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
from django.views.decorators.csrf import csrf_exempt

from docs import agreements
from docs.agreement_models import Agreement, AgreementSignature

from .views import PORTAL_AGREEMENTS_VIEW_ORG, portal_perm, portal_required


def _signatures(request, qs):
    """Signatures this portal user may see: everyone's at their customer when
    the role allows (the default), otherwise only their own. Evidence holds
    the signer's drawn signature, e-mail, IP address and browser."""
    if portal_perm(request, PORTAL_AGREEMENTS_VIEW_ORG):
        return qs
    return qs.filter(user=request.user)


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
    mine = (_signatures(request, AgreementSignature.objects.filter(organization=org))
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
    signatures = _signatures(request, AgreementSignature.objects.filter(
        revision__agreement=agreement, organization=org)).select_related('revision').order_by('-signed_at')
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
    sig = get_object_or_404(_signatures(request, AgreementSignature.objects.select_related('revision__agreement')),
                            pk=pk, organization=org)
    from docs.agreement_views import evidence_response
    agreements._audit(request.user, 'export', 'docs.AgreementSignature', sig.pk,
                      f'Portal download of evidence for {sig}', org, request)
    return evidence_response(sig)


@csrf_exempt
def agreement_reminder_unsubscribe(request, token):
    """Public, signed link from a reminder e-mail: stop reminders about one
    agreement for one person. GET asks (mail scanners fetch links); POST
    records it, including the RFC 8058 one-click POST mail clients send. The
    signed token is the authority, so no login and no CSRF token are needed
    for this one action. The agreement itself still waits in the portal."""
    from audit.models import AuditLog
    found = agreements.reminder_opt_out_for_token(token)
    if found is None:
        return render(request, 'portal/agreement_reminder_unsubscribe.html', {'invalid': True}, status=404)
    agreement, user = found
    done = agreement.reminder_opt_outs.filter(user=user).exists()
    if request.method == 'POST' and not done:
        agreements.opt_out_of_reminders(agreement, user)
        AuditLog.log(
            user=None, action='update', organization=agreement.organization,
            object_type='docs.Agreement', object_id=agreement.pk, object_repr=user.email,
            description=f'{user.email} stopped reminder e-mails for agreement "{agreement.title}" by link',
            path=request.path, extra_data={'event': 'agreement_reminder_unsubscribe'},
        )
        done = True
    return render(request, 'portal/agreement_reminder_unsubscribe.html',
                  {'agreement': agreement, 'email': user.email, 'done': done})
