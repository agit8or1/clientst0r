"""
Issuing agreement revisions, signing them, and who is outstanding.

    make_agreement(document, by, kind, mode, audience, ...)
    ensure_revision(agreement, by=None)   -> issue from live content (save/publish/scheduler only)
    issue_pending_revisions()             -> ensure_revision for every open agreement (scheduler)
    current_revision(agreement)           -> the revision a signer sees now (never issues)
    may_sign(agreement, user)             -> the signer-role rule
    sign(agreement, revision, user, organization, ...) -> AgreementSignature
    status(agreement)                     -> who signed which version, who is outstanding
    send_reminders(...)                   -> throttled reminder e-mails (scheduler)
    evidence_zip(signature)               -> bytes

A revision is issued only from **live** content — published, approved (not a
draft awaiting review) and not archived — so the document approval
workflow decides what can be signed. While an edit waits for approval the
last issued revision stays the one to sign.

Revisions are issued when the document is saved (post_save signal), when an
agreement is made or reopened (POST), and by the reminder task, which also
catches up any save whose issue failed. A page view (GET) never issues one.

Uploaded-file documents bind to the file's SHA-256 and keep a copy of the
exact bytes on the revision (up to FILE_MAX bytes).
"""
from __future__ import annotations

import io
import logging
import mimetypes
import os
import zipfile
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .agreement_models import (Agreement, AgreementReminder, AgreementRevision, AgreementSignature,
                               canonical_json, sha256)

logger = logging.getLogger('docs.agreements')

SIGNATURE_MAX = 200_000
FILE_MAX = 25 * 1024 * 1024
REMINDER_MAX_PER_REVISION = 5


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


def _read_file(document):
    """(bytes, meta) of an uploaded-file document, or (None, None) when it
    has no readable file. Refuses files over FILE_MAX."""
    f = getattr(document, 'file', None)
    if not f or not f.name:
        return None, None
    size = getattr(f, 'size', None)
    if size is not None and size > FILE_MAX:
        raise AgreementError(f'The file is larger than {FILE_MAX // (1024 * 1024)} MB; agreements keep a '
                             'copy of every issued file, so it cannot be one.')
    try:
        f.open('rb')
        try:
            f.seek(0)
            data = f.read(FILE_MAX + 1)
        finally:
            f.close()
    except (OSError, ValueError):
        logger.warning('agreement file for document %s is not readable', document.pk)
        return None, None
    if len(data) > FILE_MAX:
        raise AgreementError(f'The file is larger than {FILE_MAX // (1024 * 1024)} MB.')
    name = os.path.basename(f.name)
    mime = document.file_type or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    return data, {'name': name, 'type': mime[:100], 'size': len(data), 'sha256': sha256(data)}


def make_agreement(document, by, kind='msa', mode=Agreement.SIGNATURE, audience=Agreement.ONE, request=None,
                   *, signer_rule=None, allowed_signers=None, reminders_enabled=None,
                   reminder_interval_days=None):
    if document.organization_id is None or document.is_global:
        raise AgreementError('An agreement belongs to one customer; global KB articles cannot be agreements.')
    if document.content_type == 'file' and _read_file(document)[0] is None:
        raise AgreementError('This document has no uploaded file to sign.')
    if kind not in dict(Agreement.KINDS) or mode not in dict(Agreement.MODES) \
            or audience not in dict(Agreement.AUDIENCES):
        raise AgreementError('Unknown agreement type.')
    if signer_rule is not None and signer_rule not in dict(Agreement.SIGNER_RULES):
        raise AgreementError('Unknown signer rule.')
    named = None
    if allowed_signers is not None:
        eligible = {u.pk: u for u in _customer_members(document.organization_id)}
        named = [eligible[int(pk)] for pk in allowed_signers if str(pk).isdigit() and int(pk) in eligible]
    if signer_rule == Agreement.NAMED and not named:
        raise AgreementError('Name at least one person of this customer who may sign.')
    try:
        interval = int(reminder_interval_days) if reminder_interval_days not in (None, '') else None
    except (TypeError, ValueError):
        raise AgreementError('Reminder interval must be a number of days.')
    if interval is not None and not 1 <= interval <= 90:
        raise AgreementError('Reminder interval must be between 1 and 90 days.')
    agreement, created = Agreement.objects.get_or_create(document=document, defaults={
        'organization': document.organization, 'organization_name': document.organization.name,
        'title': document.title, 'kind': kind, 'mode': mode, 'audience': audience, 'created_by': by})
    agreement.kind, agreement.mode, agreement.audience, agreement.is_active = kind, mode, audience, True
    if signer_rule is not None:
        agreement.signer_rule = signer_rule
    if reminders_enabled is not None:
        agreement.reminders_enabled = bool(reminders_enabled)
    if interval is not None:
        agreement.reminder_interval_days = interval
    agreement.save()
    if named is not None:
        agreement.allowed_signers.set(named if agreement.signer_rule == Agreement.NAMED else [])
    _audit(by, 'create' if created else 'update', 'docs.Agreement', agreement.pk,
           f'{"Made" if created else "Updated"} agreement "{agreement.title}" '
           f'({agreement.get_kind_display()}, {agreement.mode}, {agreement.audience}, '
           f'signers: {agreement.signer_rule}'
           + (f' {", ".join(u.username for u in named)}' if named and agreement.signer_rule == Agreement.NAMED
              else '') + ')',
           document.organization, request)
    ensure_revision(agreement, by)
    return agreement


def _file_snapshot_html(document, meta, rendered) -> str:
    import html as _html
    esc = _html.escape
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<title>{esc(document.title)}</title>\n</head>\n<body>\n'
        f'<h1>{esc(document.title)}</h1>\n'
        f'<p>Organization: {esc(document.organization.name if document.organization_id else "")}</p>\n'
        '<table>\n'
        f'<tr><th>File</th><td>{esc(meta["name"])}</td></tr>\n'
        f'<tr><th>Type</th><td>{esc(meta["type"])}</td></tr>\n'
        f'<tr><th>Size</th><td>{meta["size"]} bytes</td></tr>\n'
        f'<tr><th>SHA-256</th><td>{meta["sha256"]}</td></tr>\n'
        '</table>\n'
        f'{rendered}\n'
        '</body>\n</html>\n'
    )


def ensure_revision(agreement, by=None):
    """Issue a new revision when the live content differs from the latest
    one. Returns the latest revision (None if nothing was ever issued).

    Called on save, publish and from the scheduler — never from a GET."""
    document = agreement.document
    latest = agreement.latest_revision
    if not is_live(document):
        return latest
    file_data = file_meta = None
    if document.content_type == 'file':
        file_data, file_meta = _read_file(document)
        if file_data is None:
            return latest
    content = canonical_json(AgreementRevision.content_of(document.title, document.content_type,
                                                          document.body, file_meta))
    digest = sha256(content)
    if latest is not None and latest.content_hash == digest:
        return latest
    # The customer signs what the customer sees: internal-only blocks are
    # left out of the rendered body, the snapshot and the PDF.
    rendered = document.render_for_client() if document.body else ''
    if file_meta is not None:
        snapshot = _file_snapshot_html(document, file_meta, rendered)
        pdf = None  # the stored file is the evidence
    else:
        from .services.document_export import customer_copy, export_html, export_pdf
        customer_copy(document)
        try:
            snapshot = export_html(document).decode('utf-8')
            try:
                pdf = export_pdf(document)
            except Exception:  # noqa: BLE001 — the HTML snapshot is the evidence; the PDF is a convenience
                logger.exception('agreement PDF snapshot failed')
                pdf = None
        finally:
            document._kb_customer_copy = False
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
            file_name=(file_meta or {}).get('name', ''), file_type=(file_meta or {}).get('type', ''),
            file_size=(file_meta or {}).get('size'), file_sha256=(file_meta or {}).get('sha256', ''),
            file_data=file_data, issued_at=_now(), issued_by=by or document.last_modified_by)
        if locked.title != document.title:
            locked.title = document.title
            locked.save(update_fields=['title'])
    _audit(by or document.last_modified_by, 'create', 'docs.AgreementRevision', rev.pk,
           f'Issued "{rev.title}" v{rev.version_number} for signature (sha256 {digest[:12]}…)',
           agreement.organization, extra={'agreement': agreement.pk, 'version': rev.version_number,
                                          'content_hash': digest, 'snapshot_hash': rev.snapshot_hash,
                                          'pdf_hash': rev.pdf_hash, 'file_sha256': rev.file_sha256})
    return rev


def issue_pending_revisions() -> int:
    """Scheduler path: issue a revision for every open agreement whose live
    content changed without one being issued (a failed save-time issue)."""
    issued = 0
    for agreement in Agreement.objects.filter(is_active=True, document__isnull=False).select_related('document'):
        before = agreement.latest_revision
        try:
            rev = ensure_revision(agreement)
        except Exception:  # noqa: BLE001 — one bad agreement must not stop the rest
            logger.exception('could not issue a revision for agreement %s', agreement.pk)
            continue
        if rev is not None and (before is None or rev.pk != before.pk):
            issued += 1
    return issued


def current_revision(agreement):
    """The revision a signer sees now: the latest issued one, if the
    agreement is open and its document still exists. Never issues one."""
    if not agreement.is_active or agreement.document_id is None:
        return None
    return agreement.latest_revision


def _customer_members(organization_id):
    """Active customer (non-staff) members of a customer."""
    from django.contrib.auth.models import User
    from psa.visibility import msp_staff_q
    if organization_id is None:
        return User.objects.none()
    return (User.objects.filter(is_active=True, memberships__organization_id=organization_id,
                                memberships__is_active=True)
            .exclude(msp_staff_q()).distinct().order_by('username'))


def eligible_signers(agreement):
    """Customer members the signer rule allows to sign or acknowledge."""
    qs = _customer_members(agreement.organization_id)
    if agreement.signer_rule == Agreement.ORG_ADMINS:
        qs = qs.filter(memberships__organization_id=agreement.organization_id, memberships__is_active=True,
                       memberships__is_org_admin=True)
    elif agreement.signer_rule == Agreement.NAMED:
        qs = qs.filter(pk__in=agreement.allowed_signers.values('pk'))
    return qs.distinct()


def may_sign(agreement, user) -> bool:
    if user is None or not user.is_authenticated:
        return False
    return eligible_signers(agreement).filter(pk=user.pk).exists()


def signer_rule_text(agreement) -> str:
    if agreement.signer_rule == Agreement.ORG_ADMINS:
        return f'an org admin of {agreement.organization_name}'
    if agreement.signer_rule == Agreement.NAMED:
        names = [u.get_full_name() or u.username for u in agreement.allowed_signers.order_by('username')]
        return ', '.join(names) or 'a named signer'
    return f'any portal user of {agreement.organization_name}'


def _signed_q(agreement, revision, user=None):
    qs = AgreementSignature.objects.filter(revision=revision, organization=agreement.organization)
    if agreement.audience == Agreement.EACH and user is not None:
        qs = qs.filter(user=user)
    return qs


def needs_signature(agreement, user) -> bool:
    """The current revision is unsigned for this user (or their customer)."""
    rev = current_revision(agreement)
    return rev is not None and not _signed_q(agreement, rev, user).exists()


def sign(agreement, revision_id, content_hash, user, organization, *, name, email, title='', signature_data='',
         accepted=False, request=None):
    """Record one signature/acknowledgment of the current revision. Refuses
    a stale revision (the document changed while the signer was reading), a
    customer mismatch, a signer the rule does not allow, or a second
    signature where one is enough."""
    if organization is None or agreement.organization_id != organization.pk:
        raise AgreementError('This agreement belongs to a different customer.')
    rev = current_revision(agreement)
    if rev is None:
        raise AgreementError('This agreement is not open for signing right now.')
    if not may_sign(agreement, user):
        raise AgreementError(f'Only {signer_rule_text(agreement)} may {agreement.verb} this for the customer.')
    if str(rev.pk) != str(revision_id) or rev.content_hash != (content_hash or ''):
        raise AgreementError(f'The document changed while you were reading it. Please review version '
                             f'{rev.version_number} and {agreement.verb} again.')
    if _signed_q(agreement, rev, user).exists():
        raise AgreementError(f'Version {rev.version_number} is already {agreement.verb_past}'
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
            raise AgreementError(f'Version {rev.version_number} was just {agreement.verb_past}.')
        sig = AgreementSignature.objects.create(
            revision=rev, organization=organization, organization_name=organization.name,
            organization_ref=organization.pk, user=user, user_ref=user.pk, username=user.get_username(),
            agreement_kind=agreement.kind, method=agreement.mode, signed_by_name=name, signed_by_email=email,
            signed_by_title=title, signature_data=signature_data, signed_at=_now(), ip_address=ip,
            user_agent=ua, content_hash=rev.content_hash, snapshot_hash=rev.snapshot_hash,
            pdf_hash=rev.pdf_hash)
    _audit(user, 'update', 'docs.AgreementSignature', sig.pk,
           f'{name} <{email}> {agreement.verb_past} "{rev.title}" v{rev.version_number}', organization, request,
           extra={'agreement': agreement.pk, 'revision': rev.pk, 'version': rev.version_number,
                  'content_hash': rev.content_hash, 'evidence_hash': sig.evidence_hash})
    return sig


def customer_signers(agreement):
    """Who is expected to sign under `each`: the customer members the signer
    rule allows."""
    return eligible_signers(agreement).order_by('username')


def status(agreement):
    """{'current': rev, 'revisions': [(rev, [signatures])], 'outstanding': [users] or [None],
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
            outstanding = [None]  # the customer: any one person the signer rule allows
    return {'current': rev, 'revisions': rows, 'outstanding': outstanding, 'current_signed': signed_now}


# --- reminders -----------------------------------------------------------------

def reminder_recipients(agreement, rev):
    """People to remind about `rev`: under `each`, every allowed signer who
    has not signed it; under `one` (until someone signs), the allowed
    signers — with the "any user" rule, the customer's org admins when it
    has any, so one signature does not mail the whole customer."""
    if _signed_q(agreement, rev).exists() and agreement.audience == Agreement.ONE:
        return []
    signers = list(customer_signers(agreement))
    if agreement.audience == Agreement.EACH:
        done = set(_signed_q(agreement, rev).values_list('user_id', flat=True))
        return [u for u in signers if u.pk not in done]
    if agreement.signer_rule == Agreement.ANY:
        admins = set(eligible_signers(agreement).filter(
            memberships__organization_id=agreement.organization_id, memberships__is_active=True,
            memberships__is_org_admin=True).values_list('pk', flat=True))
        if admins:
            return [u for u in signers if u.pk in admins]
    return signers


def _opted_out(user) -> bool:
    profile = getattr(user, 'profile', None)
    try:
        return profile is not None and not profile.email_notifications
    except Exception:  # noqa: BLE001
        return False


def _portal_enabled(organization_id) -> bool:
    from psa.models import ClientPSASettings
    return ClientPSASettings.objects.filter(organization_id=organization_id, portal_enabled=True).exists()


REMINDER_UNSUBSCRIBE_SALT = 'docs.agreements.reminder.unsubscribe'


def reminder_unsubscribe_token(agreement, user) -> str:
    """Signed, no-login token naming one person and one agreement."""
    from django.core import signing
    return signing.dumps({'a': agreement.pk, 'u': user.pk, 'e': (user.email or '').lower()},
                         salt=REMINDER_UNSUBSCRIBE_SALT, compress=True)


def reminder_opt_out_for_token(token):
    """(agreement, user) for a valid token, else None. The address must still
    be the user's, so a link forwarded after an e-mail change stops working."""
    from django.contrib.auth import get_user_model
    from django.core import signing
    try:
        data = signing.loads(token or '', salt=REMINDER_UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None
    agreement = Agreement.objects.filter(pk=data.get('a')).first()
    user = get_user_model().objects.filter(pk=data.get('u')).first()
    if agreement is None or user is None or (user.email or '').lower() != data.get('e'):
        return None
    return agreement, user


def reminder_unsubscribe_url(agreement, user, base='') -> str:
    from django.urls import reverse
    return base + reverse('portal:agreement_reminder_unsubscribe',
                          kwargs={'token': reminder_unsubscribe_token(agreement, user)})


def opt_out_of_reminders(agreement, user):
    from .agreement_models import AgreementReminderOptOut
    row, _ = AgreementReminderOptOut.objects.get_or_create(
        agreement=agreement, user=user, defaults={'email': user.email or ''})
    return row


def signed_earlier_revision(agreement, rev, user) -> bool:
    """Whether this person signed a previous revision of the agreement, or,
    for a one-signature-per-customer agreement, whether their customer did."""
    earlier = AgreementSignature.objects.filter(
        revision__agreement=agreement, revision__version_number__lt=rev.version_number)
    if earlier.filter(user=user).exists():
        return True
    return agreement.audience == Agreement.ONE and earlier.filter(
        organization=agreement.organization).exists()


def reminder_text(agreement, rev, user, *, link, unsubscribe, brand):
    """Body of one reminder e-mail. The opening sentence says "a new
    version" only to someone who signed an earlier one (or whose customer did,
    for a single-signature agreement); a version number above 1 alone does not
    mean this person has seen the agreement before."""
    for_org = f' for {agreement.organization_name}' if agreement.audience == Agreement.ONE else ''
    issued = f'version {rev.version_number}, issued {rev.issued_at:%Y-%m-%d}'
    if signed_earlier_revision(agreement, rev, user):
        opening = (f'There is a new version of "{rev.title}" ({issued}) that needs to be '
                   f'{agreement.verb_past}{for_org}.')
    else:
        opening = f'You are asked to {agreement.verb} "{rev.title}" ({issued}){for_org}.'
    body = (f'Hello {user.get_full_name() or user.username},\n\n'
            f'{opening}\n\nRead it and {agreement.verb} it in the customer portal:\n{link}\n\n'
            f'You get this because you may {agreement.verb} it for your organization.\n'
            f'Stop reminders about this agreement: {unsubscribe}\n'
            f'To stop all e-mail notifications, turn them off in your profile.\n\n— {brand}\n')
    return body


def send_reminders(*, now=None, dry_run=False, stdout=None) -> dict:
    """E-mail outstanding signers of every open agreement's current revision.

    Throttled per person and revision: at most one reminder every
    `reminder_interval_days`, and at most REMINDER_MAX_PER_REVISION in all.
    Skips agreements with reminders off, customers without the portal,
    people with e-mail notifications turned off or no address, and does
    nothing when SMTP is not configured."""
    from core import mailer
    from core.models import SystemSetting
    now = now or timezone.now()
    from django.core.mail import EmailMessage
    from .agreement_models import AgreementReminderOptOut
    counts = {'sent': 0, 'throttled': 0, 'opted_out': 0, 'unsubscribed': 0, 'no_email': 0, 'failed': 0,
              'agreements': 0}
    settings = SystemSetting.get_settings()
    connection = None if dry_run else mailer.get_smtp_connection(settings)
    if connection is None and not dry_run:
        counts['skipped'] = 'smtp not configured'
        return counts
    from_email = mailer.default_from_email(settings)
    # Customer-facing links: the portal host when one is set, else Site URL.
    from core.portal_surface import portal_site_url
    base = portal_site_url(settings)
    brand = mailer.brand_name(settings)
    qs = (Agreement.objects.filter(is_active=True, reminders_enabled=True, document__isnull=False)
          .select_related('organization'))
    for agreement in qs:
        rev = current_revision(agreement)
        if rev is None or not _portal_enabled(agreement.organization_id):
            continue
        counts['agreements'] += 1
        interval = timedelta(days=max(1, agreement.reminder_interval_days or 7))
        unsubscribed = set(AgreementReminderOptOut.objects.filter(
            agreement=agreement).values_list('user_id', flat=True))
        for user in reminder_recipients(agreement, rev):
            if not user.email:
                counts['no_email'] += 1
                continue
            if _opted_out(user):
                counts['opted_out'] += 1
                continue
            if user.pk in unsubscribed:
                counts['unsubscribed'] += 1
                continue
            sent = AgreementReminder.objects.filter(revision=rev, user=user)
            last = sent.order_by('-sent_at').first()
            if (last is not None and last.sent_at > now - interval) or sent.count() >= REMINDER_MAX_PER_REVISION:
                counts['throttled'] += 1
                continue
            first = last is None
            subject = (f'{"Please" if first else "Reminder: please"} {agreement.verb} '
                       f'"{rev.title}" version {rev.version_number}')
            link = f'{base}/portal/agreements/{agreement.pk}/' if base else f'/portal/agreements/{agreement.pk}/'
            unsubscribe = reminder_unsubscribe_url(agreement, user, base)
            body = reminder_text(agreement, rev, user, link=link, unsubscribe=unsubscribe, brand=brand)
            if dry_run:
                counts['sent'] += 1
                if stdout is not None:
                    stdout.write(f'would remind {user.email} about {rev}\n')
                continue
            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[user.email],
                               connection=connection,
                               headers={'List-Unsubscribe': f'<{unsubscribe}>',
                                        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'})
            try:
                ok = msg.send(fail_silently=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning('agreement reminder to %s failed: %s', user.email, exc)
                ok = 0
            if ok:
                AgreementReminder.objects.create(revision=rev, user=user, email=user.email, sent_at=now)
                counts['sent'] += 1
            else:
                counts['failed'] += 1
    return counts


# --- evidence ------------------------------------------------------------------

def revision_file_name(rev) -> str:
    from django.utils.text import get_valid_filename
    return get_valid_filename(rev.file_name or 'document') or 'document'


def evidence_zip(sig) -> bytes:
    """snapshot.html, document.pdf (when one was made), the signed file
    (uploaded-file agreements), content.json, evidence.json and SHA256SUMS.
    Each hash in evidence.json can be checked with `sha256sum` against the
    file of the same name."""
    rev = sig.revision
    files = {'content.json': rev.content_json(), 'snapshot.html': rev.snapshot_html.encode('utf-8'),
             'evidence.json': sig.evidence_json()}
    if rev.pdf:
        files['document.pdf'] = bytes(rev.pdf)
    file_entry = ''
    if rev.is_file and rev.file_data:
        file_entry = 'file/' + revision_file_name(rev)
        files[file_entry] = bytes(rev.file_data)
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
    if file_entry:
        sums += f'# {file_entry} sha256 = file_sha256 {rev.file_sha256} (also in content.json)\n'
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
