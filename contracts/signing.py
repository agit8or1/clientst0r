"""The signer's side: links, sessions, e-mail codes, signing, declining and
finalization.

Links. A link carries a 256-bit random token (`secrets.token_urlsafe(32)`);
only its HMAC is stored. Opening `/sign/<token>/` records "link requested",
binds the token to the browser session and redirects to
`/sign/i/<public id>/`, so the token is in exactly one request line and
never in a Referer (every signing page sends Referrer-Policy: no-referrer and
loads no third-party asset). The public id alone opens nothing: the session
must hold a live token of that invitation. A GET never signs, declines,
verifies or uses up an invitation.

Verification. Optional (per customer or contract): a 6-digit code e-mailed to
the invited address, valid 10 minutes, 5 attempts, at most one e-mail a
minute and 5 an hour. Codes are stored as HMACs and never logged. The level
used is recorded on the signature: link only, e-mail code, or staff account.
A forwarded unverified link proves nothing about who signed.

Finalization. The signature transaction records the signature and the
contract's signed state; the final PDF, the audit certificate and the signed
copies are made by a background job keyed on the version, which can be
retried any number of times without duplicating anything.
"""
from __future__ import annotations

import base64
import hmac
import io
import logging
import secrets
from datetime import timedelta

from django.core import signing as dsigning
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import events, jobs, notify
from .models import (ContractAccessToken, ContractDocument, ContractInvitation, ContractSettings,
                     ContractSignature, ContractVersion, canonical_json, sha256)

logger = logging.getLogger('contracts')
D = ContractDocument
SESSION_KEY = 'contracts_sign'
VIEW_NONCE_SALT = 'contracts.view-nonce'
CODE_TTL = timedelta(minutes=10)
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_SECONDS = 60
CODE_MAX_PER_HOUR = 5
SIGNATURE_MAX = 300_000


class SigningError(ValueError):
    pass


# --- tokens and sessions -------------------------------------------------------

def mint_token(inv, channel, by=None):
    raw = secrets.token_urlsafe(32)
    token = ContractAccessToken.objects.create(invitation=inv, token_hash=ContractAccessToken.hash(raw),
                                               channel=channel, created_by=by)
    return raw, token


def token_lookup(raw):
    if not raw or len(raw) > 100:
        return None
    return (ContractAccessToken.objects.select_related('invitation__contract', 'invitation__version')
            .filter(token_hash=ContractAccessToken.hash(raw), revoked_at__isnull=True).first())


def bind_session(request, inv, *, token=None, staff=False):
    data = request.session.get(SESSION_KEY) or {}
    entry = data.get(str(inv.public_id)) or {}
    entry.update({'inv': inv.pk, 'tok': token.pk if token else entry.get('tok'),
                  'staff': bool(staff) or entry.get('staff', False)})
    data[str(inv.public_id)] = entry
    # keep the session small: at most 10 contracts per browser
    if len(data) > 10:
        for k in list(data)[:-10]:
            data.pop(k, None)
    request.session[SESSION_KEY] = data
    request.session.modified = True


def session_entry(request, inv):
    return (request.session.get(SESSION_KEY) or {}).get(str(inv.public_id))


def session_allows(request, inv) -> bool:
    entry = session_entry(request, inv)
    if not entry or entry.get('inv') != inv.pk:
        return False
    if entry.get('staff'):
        user = getattr(request, 'user', None)
        return bool(user is not None and user.is_authenticated and inv.user_id == user.pk)
    return ContractAccessToken.objects.filter(pk=entry.get('tok'), invitation=inv, revoked_at__isnull=True).exists()


def verification_level(request, inv) -> str:
    entry = session_entry(request, inv) or {}
    if entry.get('staff'):
        return ContractSignature.STAFF_ACCOUNT
    if entry.get('verified'):
        return ContractSignature.EMAIL_CODE
    return ContractSignature.LINK


def view_nonce(inv) -> str:
    return dsigning.dumps({'i': inv.pk, 'n': secrets.token_hex(8)}, salt=VIEW_NONCE_SALT)


def check_view_nonce(inv, value):
    try:
        data = dsigning.loads(value or '', salt=VIEW_NONCE_SALT, max_age=6 * 3600)
    except dsigning.BadSignature:
        return None
    return data.get('n') if data.get('i') == inv.pk else None


def page_state(inv, now=None) -> str:
    """'open', 'waiting', 'signed', 'declined', 'expired', 'revoked',
    'superseded', 'closed' (contract no longer open)."""
    now = now or timezone.now()
    c = inv.contract
    if inv.status == ContractInvitation.SIGNED:
        return 'signed'
    if inv.status == ContractInvitation.DECLINED:
        return 'declined'
    if inv.status == ContractInvitation.SUPERSEDED or c.current_version_id != inv.version_id:
        return 'superseded'
    if inv.status == ContractInvitation.REVOKED:
        return 'revoked'
    if inv.status == ContractInvitation.EXPIRED or inv.is_expired(now):
        return 'expired'
    if c.status not in D.OPEN_FOR_SIGNING:
        return 'closed'
    if inv.status == ContractInvitation.WAITING:
        return 'waiting'
    return 'open'


# --- e-mail codes --------------------------------------------------------------

def _code_hash(inv, code):
    from vault.secret_fields import hash_token
    return hash_token(code, f'contracts.code.{inv.pk}')


def request_code(request, inv, now=None):
    now = now or timezone.now()
    if inv.code_sent_at and (now - inv.code_sent_at).total_seconds() < CODE_RESEND_SECONDS:
        raise SigningError('A code was sent less than a minute ago. Check your inbox, or wait a minute.')
    window_start, count = inv.code_window_start, inv.code_window_count
    if not window_start or now - window_start > timedelta(hours=1):
        window_start, count = now, 0
    if count >= CODE_MAX_PER_HOUR:
        raise SigningError('Too many codes were requested. Try again in an hour.')
    code = f'{secrets.randbelow(1_000_000):06d}'
    from . import mail
    try:
        mail.send_code(inv, code)
    except Exception as exc:  # noqa: BLE001
        logger.warning('verification code e-mail for invitation %s failed: %s', inv.pk, exc.__class__.__name__)
        raise SigningError('The code could not be e-mailed right now. Try again in a few minutes.')
    ContractInvitation.objects.filter(pk=inv.pk).update(
        code_hash=_code_hash(inv, code), code_expires_at=now + CODE_TTL, code_attempts=0, code_sent_at=now,
        code_window_start=window_start, code_window_count=count + 1)
    events.record(inv.contract, 'code_sent', version=inv.version, invitation=inv, actor_label='Signer',
                  request=request, message=f'Verification code e-mailed to {inv.email}')


def check_code(request, inv, code, now=None) -> bool:
    now = now or timezone.now()
    with transaction.atomic():
        inv = ContractInvitation.objects.select_for_update().get(pk=inv.pk)
        if not inv.code_hash or not inv.code_expires_at or inv.code_expires_at < now:
            raise SigningError('The code has expired or was never sent. Ask for a new one.')
        if inv.code_attempts >= CODE_MAX_ATTEMPTS:
            raise SigningError('Too many wrong codes. Ask for a new one.')
        ok = hmac.compare_digest(_code_hash(inv, (code or '').strip()), inv.code_hash)
        if not ok:
            inv.code_attempts += 1
            inv.save(update_fields=['code_attempts'])
        else:
            inv.code_hash = ''
            inv.code_expires_at = None
            inv.verified_at = inv.verified_at or now
            inv.save(update_fields=['code_hash', 'code_expires_at', 'verified_at'])
    events.record(inv.contract, 'code_verified' if ok else 'code_failed', version=inv.version, invitation=inv,
                  actor_label='Signer', request=request,
                  message='E-mail code accepted' if ok else f'Wrong code (attempt {inv.code_attempts})')
    if ok:
        entry = session_entry(request, inv) or {}
        entry['verified'] = True
        data = request.session.get(SESSION_KEY) or {}
        data[str(inv.public_id)] = entry
        request.session[SESSION_KEY] = data
        request.session.modified = True
    return ok


# --- signing -------------------------------------------------------------------

def clean_signature_image(data_uri: str) -> str:
    """Decode, check and re-encode a drawn signature as a small PNG."""
    if not data_uri.startswith('data:image/png;base64,') or len(data_uri) > SIGNATURE_MAX:
        raise SigningError('Draw your signature again (the image was not accepted).')
    try:
        raw = base64.b64decode(data_uri.split(',', 1)[1], validate=True)
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        if img.format != 'PNG' or img.width > 2000 or img.height > 800 or img.width < 20 or img.height < 10:
            raise ValueError('size')
        img = img.convert('LA')
        if img.getextrema()[0][0] > 200:  # no ink at all
            raise ValueError('blank')
        out = io.BytesIO()
        img.save(out, format='PNG', optimize=True)
    except SigningError:
        raise
    except Exception:  # noqa: BLE001
        raise SigningError('Draw your signature again (the image was not accepted).')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def sign(request, inv, post, now=None):
    """Record one signature from the signing page's POST."""
    from . import services
    now = now or timezone.now()
    printed = (post.get('printed_name') or '').strip()[:200]
    title = (post.get('title') or '').strip()[:200]
    method = post.get('method') if post.get('method') in ('typed', 'drawn') else ''
    typed = (post.get('typed_signature') or '').strip()[:200]
    if not printed:
        raise SigningError('Enter your printed name.')
    if post.get('consent') != 'yes':
        raise SigningError('Agree to sign electronically, or decline and ask for another way to sign.')
    if post.get('intent') != 'yes':
        raise SigningError('Confirm that you intend to sign this agreement.')
    image = ''
    if method == 'typed':
        if not typed:
            raise SigningError('Type your signature.')
    elif method == 'drawn':
        image = clean_signature_image((post.get('signature_data') or '').strip())
    else:
        raise SigningError('Choose to type or draw your signature.')
    level = verification_level(request, inv)
    from .events import request_meta
    ip, ua = request_meta(request)
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=inv.contract_id)
        inv = ContractInvitation.objects.select_for_update().select_related('version').get(pk=inv.pk)
        v = inv.version
        state = page_state(inv, now)
        if state == 'signed':
            raise SigningError('You have already signed this version.')
        if state != 'open':
            raise SigningError({'waiting': 'It is not your turn to sign yet.',
                                'expired': 'This signing link has expired.',
                                'revoked': 'This signing link was withdrawn.',
                                'superseded': 'A newer version replaced this one; use the newest link.',
                                'declined': 'You declined this contract.'}.get(state, 'This contract is closed.'))
        if str(post.get('version_id')) != str(v.pk) or post.get('content_hash') != v.content_hash:
            raise SigningError('The contract changed while you were reading it. Review it again before signing.')
        if v.require_verification and level == ContractSignature.LINK:
            raise SigningError('Verify your e-mail address with the code we send you before signing.')
        events.record(contract, 'consent', version=v, invitation=inv, actor_label=printed, request=request,
                      message='Agreed to sign electronically', data={'consent_hash': sha256(v.consent_text.encode())})
        try:
            with transaction.atomic():
                sig = ContractSignature.objects.create(
                    invitation=inv, version=v, role=inv.role, invited_name=inv.name, invited_email=inv.email,
                    printed_name=printed, title=title, method=method, typed_signature=typed if method == 'typed' else '',
                    signature_image=image, signing_date=timezone.localdate(now), intent_text=v.intent_text,
                    consent_text=v.consent_text, verification_level=level, signed_at=now.replace(microsecond=0),
                    ip_address=ip, user_agent=ua, content_hash=v.content_hash, snapshot_hash=v.snapshot_hash,
                    pdf_hash=v.pdf_hash)
        except IntegrityError:
            raise SigningError('You have already signed this version.')
        inv.status = ContractInvitation.SIGNED
        inv.signed_at = now
        inv.save(update_fields=['status', 'signed_at'])
        jobs.cancel_for(invitation=inv, kinds=['invitation_email', 'reminder_email'], reason='signed')
        events.record(contract, 'signed', version=v, invitation=inv, actor_label=printed, request=request,
                      message=f'{printed} signed version {v.version_number} ({sig.get_method_display().lower()}, '
                              f'{sig.get_verification_level_display().lower()})',
                      data={'evidence_hash': sig.evidence_hash, 'content_hash': v.content_hash})
        queued = _after_signature(contract, v)
    jobs.run_now(queued)
    return sig


def _after_signature(contract, v):
    from . import services
    invs = list(v.invitations.exclude(status__in=[ContractInvitation.REVOKED, ContractInvitation.SUPERSEDED,
                                                  ContractInvitation.EXPIRED]))
    slots = {}
    for i in invs:
        slots.setdefault(i.signer_ref, []).append(i)
    complete = len(slots) == len(v.signer_specs) and all(
        any(i.status == ContractInvitation.SIGNED for i in slot) for slot in slots.values())
    queued = []
    if complete:
        now = timezone.now()
        services.transition(contract, D.SIGNED, signed_at=now)
        v.status = ContractVersion.SIGNED
        v.completed_at = now
        v.finalization_status = 'pending'
        v.save(update_fields=['status', 'completed_at', 'finalization_status'])
        jobs.cancel_for(contract=contract, kinds=['invitation_email', 'reminder_email'], reason='all signed')
        events.record(contract, 'completed', version=v, actor_label='System',
                      message=f'Every signature on version {v.version_number} is recorded')
        job, _ = jobs.enqueue('finalize', f'finalize:{v.pk}', contract=contract, version=v, max_attempts=10)
        queued.append(job)
    else:
        services.transition(contract, D.PARTIALLY_SIGNED, only_from=(D.SENT, D.VIEWED))
        queued += services.activate_next(v)
        signed = [i for i in invs if i.status == ContractInvitation.SIGNED]
        notify.notify(contract, 'partial', f'{signed[-1].name if signed else "A signer"} signed {contract.reference} '
                      f'"{contract.title}" ({len(signed)} of {len(v.signer_specs)} signatures).',
                      f'partial:{v.pk}:{len(signed)}')
    from .models import ContractJob
    queued += list(ContractJob.objects.filter(contract=contract, kind='staff_email', status=ContractJob.PENDING)[:20])
    return queued


def decline(request, inv, reason='', now=None):
    from . import services
    now = now or timezone.now()
    reason = (reason or '').strip()[:2000]
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=inv.contract_id)
        inv = ContractInvitation.objects.select_for_update().select_related('version').get(pk=inv.pk)
        if page_state(inv, now) != 'open':
            raise SigningError('This contract cannot be declined from this link now.')
        inv.status = ContractInvitation.DECLINED
        inv.declined_at = now
        inv.decline_reason = reason
        inv.save(update_fields=['status', 'declined_at', 'decline_reason'])
        v = inv.version
        services.transition(contract, D.DECLINED, declined_at=now)
        v.status = ContractVersion.DECLINED
        v.save(update_fields=['status'])
        for other in v.invitations.filter(status__in=ContractInvitation.OPEN):
            services.revoke(other, None, reason='Another signer declined', record=False)
        jobs.cancel_for(contract=contract, kinds=['invitation_email', 'reminder_email'], reason='declined')
        events.record(contract, 'declined', version=v, invitation=inv, actor_label=inv.name, request=request,
                      message=f'{inv.name} declined' + (f': {reason[:300]}' if reason else ' (no reason given)'))
    notify.notify(contract, 'declined', f'{contract.reference} "{contract.title}" was declined from the link sent to '
                  f'{inv.name}' + (f': {reason[:200]}' if reason else '.'), f'declined:{v.pk}')
    from .models import ContractJob
    jobs.run_now(list(ContractJob.objects.filter(contract=contract, kind='staff_email', status=ContractJob.PENDING)))


def reminders_apply(inv) -> bool:
    c = inv.contract
    settings = ContractSettings.for_organization(c.organization)
    enabled = settings.reminders_enabled if c.reminders_enabled is None else c.reminders_enabled
    return bool(enabled and inv.status == ContractInvitation.ACTIVE and not inv.is_expired()
                and c.status in D.OPEN_FOR_SIGNING and c.current_version_id == inv.version_id
                and inv.reminders_sent < settings.reminder_max)


# --- finalization --------------------------------------------------------------

def certificate(v) -> dict:
    sigs = list(v.signatures.order_by('signed_at', 'pk'))
    evs = list(v.events.filter(kind__in=['issued', 'approved', 'sent', 'invitation_activated', 'email_accepted',
                                          'human_view', 'verified_view', 'code_verified', 'consent', 'signed',
                                          'completed']).order_by('at', 'pk'))
    return {
        'schema': 'clientst0r.contract-certificate.v1',
        'contract': v.content['contract'], 'client': v.content['client'], 'provider': v.content['provider']['name'],
        'version': {'id': v.pk, 'number': v.version_number, 'issued_at': v.issued_at.isoformat(),
                    'content_hash': v.content_hash, 'snapshot_hash': v.snapshot_hash, 'issued_pdf_hash': v.pdf_hash},
        'approvals': [{'decision': a.decision, 'by': a.decided_by_name, 'at': a.decided_at.isoformat(),
                       'content_hash': a.content_hash} for a in v.approvals.order_by('decided_at')],
        'signatures': [{'role': s.role, 'printed_name': s.printed_name, 'title': s.title,
                        'invited_email': s.invited_email, 'method': s.method,
                        'verification_level': s.verification_level, 'signed_at': s.signed_at.isoformat(),
                        'ip_address': s.ip_address or '', 'user_agent': s.user_agent,
                        'evidence_hash': s.evidence_hash} for s in sigs],
        'events': [{'at': e.at.isoformat(), 'kind': e.kind, 'message': e.message} for e in evs],
        'completed_at': v.completed_at.isoformat() if v.completed_at else '',
        'consent_text': v.consent_text,
        'note': ('Signatures are typed or drawn electronic signatures with the evidence above. SHA-256 hashes '
                 'make later changes to the document detectable; they are not certificate-based digital '
                 'signatures and do not by themselves prove identity.'),
    }


def finalize_version(v):
    """Make and store the final signed PDF and audit certificate, then send
    copies and tell staff. Safe to run again: each step checks its own
    result first (write-once fields, idempotency keys)."""
    from .pdf import build_pdf
    with transaction.atomic():
        v = ContractVersion.objects.select_for_update().select_related('contract').get(pk=v.pk)
        if v.status != ContractVersion.SIGNED or not v.completed_at:
            raise jobs.Skip('version is not complete')
        failure = pdf = None
        if v.finalization_status != 'done':
            cert = certificate(v)
            cert_json = canonical_json(cert).decode('utf-8')
            try:
                pdf = build_pdf(v.content, version_number=v.version_number, signatures=list(v.signatures.all()),
                                certificate=cert, issued_hash=v.content_hash)
            except Exception as exc:
                failure = exc
                pdf = None
        if v.finalization_status != 'done' and pdf is not None:
            v.final_pdf, v.final_pdf_hash = pdf, sha256(pdf)
            v.certificate_json, v.certificate_hash = cert_json, sha256(cert_json.encode('utf-8'))
            v.finalization_status, v.finalization_error, v.finalized_at = 'done', '', timezone.now()
            v.save(update_fields=['final_pdf', 'final_pdf_hash', 'certificate_json', 'certificate_hash',
                                  'finalization_status', 'finalization_error', 'finalized_at'])
            events.record(v.contract, 'finalized', version=v, actor_label='System',
                          message=f'Final signed PDF stored (SHA-256 {v.final_pdf_hash[:12]}…)',
                          data={'final_pdf_hash': v.final_pdf_hash, 'certificate_hash': v.certificate_hash})
    if failure is not None:  # recorded outside the transaction, then retried by the job
        ContractVersion.objects.filter(pk=v.pk).update(finalization_status='failed',
                                                       finalization_error=str(failure)[:500])
        raise failure
    contract = v.contract
    queued = []
    for inv in v.invitations.filter(status=ContractInvitation.SIGNED):
        job, _ = jobs.enqueue('completed_copy', f'copy:{inv.pk}', contract=contract, version=v, invitation=inv)
        queued.append(job)
    rel = contract.related_contract
    if rel is not None and contract.relation == 'replaces':
        from . import services
        if services.transition(rel, D.SUPERSEDED, only_from=(D.SIGNED,)):
            events.record(rel, 'superseded', actor_label='System',
                          message=f'Replaced by {contract.reference}, signed {timezone.localdate():%Y-%m-%d}')
    notify.notify(contract, 'signed', f'{contract.reference} "{contract.title}" for {contract.client_name} is fully '
                  'signed. The signed PDF is stored on the contract.', f'signed:{v.pk}')
    from .models import ContractJob
    queued += list(ContractJob.objects.filter(contract=contract, kind='staff_email', status=ContractJob.PENDING)[:20])
    jobs.run_now([j for j in queued if j.status == ContractJob.PENDING])
