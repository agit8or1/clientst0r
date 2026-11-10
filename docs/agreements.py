"""
Issuing agreement revisions, signing them, and who is outstanding.

    make_agreement(document, by, kind, mode, audience)
    ensure_revision(agreement, by=None)   -> current revision or None
    current_revision(agreement)           -> the revision a signer sees now
    sign(agreement, revision, user, organization, ...) -> AgreementSignature
    status(agreement)                     -> who signed which version, who is outstanding
    evidence_zip(signature)               -> bytes

A revision is issued only from **live** content — published, approved (not a
draft awaiting review) and not archived — so the document approval
workflow decides what can be signed. While an edit waits for approval the
last issued revision stays the one to sign.
"""
from __future__ import annotations

import io
import logging
import zipfile

from django.db import transaction
from django.utils import timezone

from .agreement_models import Agreement, AgreementRevision, AgreementSignature, canonical_json, sha256

logger = logging.getLogger('docs.agreements')

SIGNATURE_MAX = 200_000


class AgreementError(ValueError):
    pass


def _now():
    return timezone.now().replace(microsecond=0)


def _audit(user, verb, obj_type, obj_id, text, organization=None, request=None, extra=None):
    from audit.models import AuditLog
    ip = ua = ''
    if request is not None:
        from core.client_ip import get_client_ip
        ip, ua = get_client_ip(request), (request.META.get('HTTP_USER_AGENT') or '')[:400]
    AuditLog.log(user=user if user is not None and user.is_authenticated else None, action=verb,
                 organization=organization, object_type=obj_type, object_id=obj_id, object_repr=text[:255],
                 description=text, ip_address=ip or None, user_agent=ua, path=request.path if request else '',
                 extra_data=extra or {})


def is_live(document) -> bool:
    return bool(document is not None and document.is_published and not document.is_draft
                and not document.is_archived)


def make_agreement(document, by, kind='msa', mode=Agreement.SIGNATURE, audience=Agreement.ONE, request=None):
    if document.organization_id is None or document.is_global:
        raise AgreementError('An agreement belongs to one customer; global KB articles cannot be agreements.')
    if document.content_type == 'file':
        raise AgreementError('Uploaded files cannot be agreements yet. Create the agreement as an HTML or '
                             'Markdown document so each revision can be hashed and snapshotted.')
    if kind not in dict(Agreement.KINDS) or mode not in dict(Agreement.MODES) \
            or audience not in dict(Agreement.AUDIENCES):
        raise AgreementError('Unknown agreement type.')
    agreement, created = Agreement.objects.get_or_create(document=document, defaults={
        'organization': document.organization, 'organization_name': document.organization.name,
        'title': document.title, 'kind': kind, 'mode': mode, 'audience': audience, 'created_by': by})
    if not created:
        agreement.kind, agreement.mode, agreement.audience, agreement.is_active = kind, mode, audience, True
        agreement.save(update_fields=['kind', 'mode', 'audience', 'is_active'])
    _audit(by, 'create' if created else 'update', 'docs.Agreement', agreement.pk,
           f'{"Made" if created else "Updated"} agreement "{agreement.title}" '
           f'({agreement.get_kind_display()}, {agreement.mode}, {agreement.audience})',
           document.organization, request)
    ensure_revision(agreement, by)
    return agreement


def _content(document):
    return AgreementRevision.content_of(document.title, document.content_type, document.body)


def ensure_revision(agreement, by=None):
    """Issue a new revision when the live content differs from the latest
    one. Returns the latest revision (None if nothing was ever issued)."""
    document = agreement.document
    latest = agreement.latest_revision
    if not is_live(document):
        return latest
    content = canonical_json(_content(document))
    digest = sha256(content)
    if latest is not None and latest.content_hash == digest:
        return latest
    from .services.document_export import export_html, export_pdf
    rendered = document.render_content()
    snapshot = export_html(document).decode('utf-8')
    try:
        pdf = export_pdf(document)
    except Exception:  # noqa: BLE001 — the HTML snapshot is the evidence; the PDF is a convenience
        logger.exception('agreement PDF snapshot failed')
        pdf = None
    with transaction.atomic():
        locked = Agreement.objects.select_for_update().get(pk=agreement.pk)
        latest = locked.latest_revision
        if latest is not None and latest.content_hash == digest:
            return latest
        rev = AgreementRevision.objects.create(
            agreement=locked, version_number=(latest.version_number + 1) if latest else 1,
            title=document.title, body=document.body or '', content_type=document.content_type,
            content_hash=digest, rendered_html=rendered, snapshot_html=snapshot,
            snapshot_hash=sha256(snapshot.encode('utf-8')), pdf=pdf, pdf_hash=sha256(pdf) if pdf else '',
            issued_at=_now(), issued_by=by or document.last_modified_by)
        if locked.title != document.title:
            locked.title = document.title
            locked.save(update_fields=['title'])
    _audit(by or document.last_modified_by, 'create', 'docs.AgreementRevision', rev.pk,
           f'Issued "{rev.title}" v{rev.version_number} for signature (sha256 {digest[:12]}…)',
           agreement.organization, extra={'agreement': agreement.pk, 'version': rev.version_number,
                                          'content_hash': digest, 'snapshot_hash': rev.snapshot_hash,
                                          'pdf_hash': rev.pdf_hash})
    return rev


def current_revision(agreement):
    """The revision a signer sees now: the latest issued one, if the
    agreement is open and its document still exists."""
    if not agreement.is_active or agreement.document_id is None:
        return None
    return ensure_revision(agreement)


def _signed_q(agreement, revision, user=None):
    qs = AgreementSignature.objects.filter(revision=revision, organization=agreement.organization)
    if agreement.audience == Agreement.EACH and user is not None:
        qs = qs.filter(user=user)
    return qs


def needs_signature(agreement, user) -> bool:
    rev = current_revision(agreement)
    return rev is not None and not _signed_q(agreement, rev, user).exists()


def sign(agreement, revision_id, content_hash, user, organization, *, name, email, title='', signature_data='',
         accepted=False, request=None):
    """Record one signature/acknowledgment of the current revision. Refuses
    a stale revision (the document changed while the signer was reading), a
    customer mismatch, or a second signature where one is enough."""
    if organization is None or agreement.organization_id != organization.pk:
        raise AgreementError('This agreement belongs to a different customer.')
    rev = current_revision(agreement)
    if rev is None:
        raise AgreementError('This agreement is not open for signing right now.')
    if str(rev.pk) != str(revision_id) or rev.content_hash != (content_hash or ''):
        raise AgreementError(f'The document changed while you were reading it. Please review version '
                             f'{rev.version_number} and {agreement.verb} again.')
    if _signed_q(agreement, rev, user).exists():
        raise AgreementError(f'Version {rev.version_number} is already {agreement.verb}d'
                             + (' for your organization.' if agreement.audience == Agreement.ONE else ' by you.'))
    name, email, title = (name or '').strip()[:200], (email or '').strip()[:254], (title or '').strip()[:200]
    if not name or not email or not accepted:
        raise AgreementError('Enter your name and e-mail and confirm that you accept.')
    signature_data = (signature_data or '').strip()
    if agreement.mode == Agreement.SIGNATURE:
        if not signature_data.startswith('data:image/png;base64,'):
            raise AgreementError('Please draw your signature.')
        if len(signature_data) > SIGNATURE_MAX:
            raise AgreementError('Signature image is too large.')
    else:
        signature_data = ''
    ip, ua = None, ''
    if request is not None:
        from core.client_ip import get_client_ip
        ip, ua = get_client_ip(request), (request.META.get('HTTP_USER_AGENT') or '')[:400]
    with transaction.atomic():
        Agreement.objects.select_for_update().filter(pk=agreement.pk).first()  # one signer at a time
        if _signed_q(agreement, rev, user).exists():
            raise AgreementError(f'Version {rev.version_number} was just {agreement.verb}d.')
        sig = AgreementSignature.objects.create(
            revision=rev, organization=organization, organization_name=organization.name,
            organization_ref=organization.pk, user=user, user_ref=user.pk, username=user.get_username(),
            agreement_kind=agreement.kind, method=agreement.mode, signed_by_name=name, signed_by_email=email,
            signed_by_title=title, signature_data=signature_data, signed_at=_now(), ip_address=ip,
            user_agent=ua, content_hash=rev.content_hash, snapshot_hash=rev.snapshot_hash,
            pdf_hash=rev.pdf_hash)
    _audit(user, 'update', 'docs.AgreementSignature', sig.pk,
           f'{name} <{email}> {agreement.verb}d "{rev.title}" v{rev.version_number}', organization, request,
           extra={'agreement': agreement.pk, 'revision': rev.pk, 'version': rev.version_number,
                  'content_hash': rev.content_hash, 'evidence_hash': sig.evidence_hash})
    return sig


def customer_signers(agreement):
    """Who is expected to sign under `each`: active customer (non-staff)
    members of the agreement's customer."""
    from django.contrib.auth.models import User
    from psa.visibility import msp_staff_q
    if agreement.organization_id is None:
        return User.objects.none()
    return (User.objects.filter(is_active=True, memberships__organization_id=agreement.organization_id,
                                memberships__is_active=True)
            .exclude(msp_staff_q()).distinct().order_by('username'))


def status(agreement):
    """{'current': rev, 'revisions': [(rev, [signatures])], 'outstanding': [users] or ['customer'],
    'current_signed': bool}."""
    rev = current_revision(agreement) or agreement.latest_revision
    revisions = list(agreement.revisions.order_by('-version_number').prefetch_related('signatures'))
    rows = [(r, list(r.signatures.order_by('signed_at'))) for r in revisions]
    outstanding, signed_now = [], False
    if rev is not None:
        sigs = list(AgreementSignature.objects.filter(revision=rev, organization_id=agreement.organization_id))
        signed_now = bool(sigs)
        if agreement.audience == Agreement.EACH:
            done = {s.user_id for s in sigs}
            outstanding = [u for u in customer_signers(agreement) if u.pk not in done]
            signed_now = not outstanding
        elif not sigs:
            outstanding = [None]  # the customer, any one authorised person
    return {'current': rev, 'revisions': rows, 'outstanding': outstanding, 'current_signed': signed_now}


def evidence_zip(sig) -> bytes:
    """snapshot.html, document.pdf (when one was made), content.json,
    evidence.json and SHA256SUMS. Each hash in evidence.json can be checked
    with `sha256sum` against the file of the same name."""
    rev = sig.revision
    files = {'content.json': rev.content_json(), 'snapshot.html': rev.snapshot_html.encode('utf-8'),
             'evidence.json': sig.evidence_json()}
    if rev.pdf:
        files['document.pdf'] = bytes(rev.pdf)
    if sig.signature_data.startswith('data:image/png;base64,'):
        import base64
        try:
            files['signature.png'] = base64.b64decode(sig.signature_data.split(',', 1)[1])
        except Exception:  # noqa: BLE001
            pass
    sums = ''.join(f'{sha256(data)}  {name}\n' for name, data in sorted(files.items()))
    sums += f'# evidence.json sha256 = evidence_hash {sig.evidence_hash}\n'
    sums += f'# content.json sha256 = content_hash {sig.content_hash}\n'
    sums += f'# snapshot.html sha256 = snapshot_hash {sig.snapshot_hash}\n'
    if sig.pdf_hash:
        sums += f'# document.pdf sha256 = pdf_hash {sig.pdf_hash}\n'
    files['SHA256SUMS'] = sums.encode('utf-8')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def evidence_filename(sig) -> str:
    from django.utils.text import slugify
    return (f'{slugify(sig.revision.title)[:60] or "agreement"}-v{sig.revision.version_number}-'
            f'evidence-{sig.pk}.zip')
