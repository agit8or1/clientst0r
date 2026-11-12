"""Contract lifecycle for staff: create, edit, approve, send, revise, void.

Status machine (enforced here, server-side; `transition()` refuses anything
not listed):

    draft ─┬─> pending_approval ──> ready_to_send ──> sent ──> viewed
           └─> ready_to_send                          │  │       │
    sent / viewed ──> partially_signed ──> signed ──> superseded (by a replacement)
    sent / viewed / partially_signed ──> declined | expired
    pending_approval / ready_to_send / sent / viewed / partially_signed /
        declined / expired ──> draft          (revise: a new version follows)
    anything but voided / superseded ──> voided   (needs a reason)

Viewing and delivery never move a contract backwards: only `sent` becomes
`viewed`, so a later view cannot "downgrade" a signed contract. The signature
state is computed from the signatures of the current version.

Issuing freezes the draft into a `ContractVersion` (content JSON + SHA-256,
HTML snapshot, PDF). Approval binds to the version's content hash; editing
afterwards issues a new version, which needs approval again. Revising a sent
contract supersedes its version and revokes every outstanding link; the
signatures already given stay on the old version as evidence.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import events, jobs, notify
from . import permissions as perms
from .content import ContentError, build_content, normalize_line_items, normalize_sections, render_body, \
    snapshot_html, totals, validate_for_issue
from .models import (ContractApproval, ContractAttachment, ContractDocument, ContractInvitation, ContractSettings,
                     ContractSigner, ContractTemplate, ContractVersion, canonical_json, sha256)

logger = logging.getLogger('contracts')
D = ContractDocument

TRANSITIONS = {
    D.DRAFT: {D.PENDING_APPROVAL, D.READY, D.VOIDED},
    D.PENDING_APPROVAL: {D.READY, D.DRAFT, D.VOIDED},
    D.READY: {D.SENT, D.DRAFT, D.VOIDED},
    D.SENT: {D.VIEWED, D.PARTIALLY_SIGNED, D.SIGNED, D.DECLINED, D.EXPIRED, D.VOIDED, D.DRAFT},
    D.VIEWED: {D.PARTIALLY_SIGNED, D.SIGNED, D.DECLINED, D.EXPIRED, D.VOIDED, D.DRAFT},
    D.PARTIALLY_SIGNED: {D.SIGNED, D.DECLINED, D.EXPIRED, D.VOIDED, D.DRAFT},
    D.SIGNED: {D.VOIDED, D.SUPERSEDED},
    D.DECLINED: {D.DRAFT, D.VOIDED},
    D.EXPIRED: {D.DRAFT, D.VOIDED},
    D.VOIDED: set(),
    D.SUPERSEDED: set(),
}


class ContractError(ValueError):
    pass


class InvalidTransition(ContractError):
    pass


def can_transition(current, new) -> bool:
    return new in TRANSITIONS.get(current, set())


def transition(contract, new, *, only_from=None, **extra) -> bool:
    """Move `contract` to `new` atomically (conditional UPDATE). Raises
    InvalidTransition unless allowed; with `only_from`, silently does nothing
    when the stored status is not one of those."""
    current = ContractDocument.objects.filter(pk=contract.pk).values_list('status', flat=True).first()
    if only_from is not None and current not in only_from:
        return False
    if not can_transition(current, new):
        raise InvalidTransition(f'A {dict(D.STATUSES).get(current, current)} contract cannot become '
                                f'{dict(D.STATUSES)[new]}.')
    fields = {'status': new, 'updated_at': timezone.now(), **extra}
    changed = ContractDocument.objects.filter(pk=contract.pk, status=current).update(**fields)
    if not changed:
        raise InvalidTransition('The contract changed at the same time; reload and try again.')
    for k, v in fields.items():
        setattr(contract, k, v)
    return True


# --- settings ------------------------------------------------------------------

def settings_for(contract):
    return ContractSettings.for_organization(contract.organization)


def signing_config(contract, settings=None) -> dict:
    s = settings or settings_for(contract)

    def pick(own, default):
        return default if own is None else own
    return {
        'order': contract.signing_order or s.signing_order,
        'verification': bool(pick(contract.require_email_verification, s.require_email_verification)),
        'countersignature': bool(pick(contract.require_countersignature, s.require_countersignature)),
        'approval': bool(pick(contract.require_internal_approval, s.require_internal_approval)),
    }


# --- create / clone ------------------------------------------------------------

def _next_reference():
    year = timezone.localdate().year
    prefix = f'CT-{year}-'
    last = (ContractDocument.objects.filter(reference__startswith=prefix).order_by('-reference')
            .values_list('reference', flat=True).first())
    try:
        n = int(last.rsplit('-', 1)[-1]) if last else 0
    except ValueError:
        n = 0
    return f'{prefix}{n + 1:05d}'


def _save_new(contract):
    for _ in range(5):
        if not contract.reference:
            contract.reference = _next_reference()
        try:
            with transaction.atomic():
                contract.save()
            return contract
        except IntegrityError:
            contract.reference = ''
    raise ContractError('Could not allocate a contract number; try again.')


def _apply_template_data(contract, data):
    contract.sections = normalize_sections(data.get('sections') or [])
    contract.line_items = normalize_line_items(data.get('line_items') or [])
    d = data.get('defaults') or {}
    for f in ('payment_terms', 'renewal_terms', 'currency'):
        if d.get(f):
            setattr(contract, f, str(d[f])[:255])
    if d.get('billing_frequency') in dict(contract._meta.get_field('billing_frequency').choices):
        contract.billing_frequency = d['billing_frequency']
    for f in ('duration_months', 'notice_period_days'):
        if str(d.get(f) or '').isdigit():
            setattr(contract, f, int(d[f]))
    if 'auto_renew' in d:
        contract.auto_renew = bool(d['auto_renew'])
    _fill_expiration(contract)


def _fill_expiration(contract):
    if contract.expiration_date is None and contract.effective_date and contract.duration_months:
        from dateutil.relativedelta import relativedelta
        contract.expiration_date = (contract.effective_date + relativedelta(months=contract.duration_months)
                                    - timedelta(days=1))


def _default_deadline(settings):
    if settings.acceptance_deadline_days:
        return timezone.localdate() + timedelta(days=settings.acceptance_deadline_days)
    return None


def create_contract(organization, by, *, template=None, title='', kind=None, request=None):
    if template is not None and template.organization_id not in (None, organization.pk):
        raise ContractError('That template belongs to another customer.')
    settings = ContractSettings.for_organization(organization)
    tv = template.latest_version if template is not None else None
    contract = ContractDocument(
        organization=organization, organization_name=organization.name,
        title=(title or (template.name if template else 'New contract'))[:255],
        kind=kind or (template.kind if template else 'other'), owner=by, created_by=by,
        template_version=tv, effective_date=timezone.localdate(),
        acceptance_deadline=_default_deadline(settings))
    if tv is not None:
        _apply_template_data(contract, tv.data)
    else:
        contract.sections = normalize_sections([
            {'title': 'Agreement', 'type': 'text', 'body': '<p></p>'},
            {'title': 'Signatures', 'type': 'signatures', 'body': ''}])
    _add_default_clauses(contract, settings)
    _recompute_totals(contract)
    _save_new(contract)
    if organization.primary_contact_email:
        ContractSigner.objects.create(contract=contract, role=ContractSigner.CLIENT,
                                      name=organization.primary_contact_name or organization.name,
                                      email=organization.primary_contact_email,
                                      title=organization.primary_contact_title or '', order=1)
    events.record(contract, 'created', actor=by, request=request,
                  message=f'From template "{template.name}" v{tv.version_number}' if tv else 'Blank contract')
    return contract


def _add_default_clauses(contract, settings):
    """Settings → default clauses: added (once) before the signature section."""
    have = {(s.get('title') or '').strip().lower() for s in contract.sections}
    extra = [{'title': cl.title, 'type': 'text', 'body': cl.body, 'include': True, 'optional': cl.is_optional}
             for cl in settings.default_clauses.filter(is_active=True).order_by('category', 'title')
             if cl.title.strip().lower() not in have]
    if not extra:
        return
    sections = list(contract.sections)
    at = next((i for i, s in enumerate(sections) if s.get('type') == 'signatures'), len(sections))
    contract.sections = normalize_sections(sections[:at] + extra + sections[at:])


def clone_contract(src, by, *, relation='cloned_from', kind=None, title=None, request=None, template=None):
    """A new draft copying the source's current draft content and signers
    (never its versions, invitations or signatures)."""
    if src.organization is None:
        raise ContractError('The source contract has no customer any more.')
    settings = ContractSettings.for_organization(src.organization)
    c = ContractDocument(
        organization=src.organization, organization_name=src.organization_name, title=title or f'{src.title} (copy)',
        kind=kind or src.kind, owner=by, account_manager=src.account_manager, created_by=by,
        related_contract=src, relation=relation, sections=normalize_sections(src.sections),
        line_items=normalize_line_items(src.line_items), currency=src.currency, tax_rate=src.tax_rate,
        payment_terms=src.payment_terms, billing_frequency=src.billing_frequency,
        effective_date=timezone.localdate(), duration_months=src.duration_months,
        renewal_terms=src.renewal_terms, auto_renew=src.auto_renew, notice_period_days=src.notice_period_days,
        acceptance_deadline=_default_deadline(settings), require_email_verification=src.require_email_verification,
        require_countersignature=src.require_countersignature, signing_order=src.signing_order,
        require_internal_approval=src.require_internal_approval)
    if template is not None and template.latest_version is not None:
        _apply_template_data(c, template.latest_version.data)
        c.template_version = template.latest_version
    _recompute_totals(c)
    _save_new(c)
    for s in src.signers.all():
        ContractSigner.objects.create(contract=c, role=s.role, name=s.name, email=s.email, title=s.title,
                                      order=s.order, user=s.user)
    events.record(c, 'created', actor=by, request=request,
                  message=f'{dict(D.RELATIONS).get(relation, "From")} {src.reference}')
    return c


def amend(src, by, request=None):
    if src.status != D.SIGNED:
        raise ContractError('Only a signed contract can be amended; edit or revise this one instead.')
    tpl = ContractTemplate.objects.filter(kind='amendment', is_active=True).filter(
        organization__in=[None, src.organization_id]).order_by('organization_id').last()
    c = clone_contract(src, by, relation='amends', kind='amendment', title=f'Amendment to {src.title}',
                       request=request, template=tpl)
    if tpl is None:
        c.sections = normalize_sections([
            {'title': 'Amendment', 'type': 'text',
             'body': f'<p>This amendment changes contract {src.reference} ("{src.title}"). '
                     'Except as changed below, that contract stays in effect.</p><p>[[Describe the changes]]</p>'},
            {'title': 'Signatures', 'type': 'signatures', 'body': ''}])
        c.save(update_fields=['sections'])
    return c


def renew(src, by, request=None, replace=False):
    tpl = ContractTemplate.objects.filter(kind='renewal', is_active=True).filter(
        organization__in=[None, src.organization_id]).order_by('organization_id').last()
    c = clone_contract(src, by, relation='replaces' if replace else 'renews',
                       kind=src.kind if replace else 'renewal',
                       title=f'{"Replacement of" if replace else "Renewal of"} {src.title}', request=request,
                       template=None if replace else tpl)
    if src.expiration_date and not replace:
        c.effective_date = src.expiration_date + timedelta(days=1)
        c.save(update_fields=['effective_date'])
    return c


# --- drafts ----------------------------------------------------------------------

def _recompute_totals(contract):
    t = totals(normalize_line_items(contract.line_items), contract.tax_rate)
    contract.one_time_total = t['one_time']['total']
    contract.recurring_total = t['recurring']['total']


DRAFT_FIELDS = ('title', 'kind', 'currency', 'tax_rate', 'payment_terms', 'billing_frequency', 'effective_date',
                'duration_months', 'expiration_date', 'renewal_terms', 'auto_renew', 'notice_period_days',
                'acceptance_deadline', 'require_email_verification', 'require_countersignature', 'signing_order',
                'require_internal_approval', 'invitation_expiry_days', 'reminders_enabled')


def save_draft(contract, data, by, *, expected_revision=None, request=None):
    """Save the builder's parsed data. Returns the new revision number.
    Raises ContractError when the contract is not a draft or the editor's
    copy is stale (someone saved in between)."""
    with transaction.atomic():
        locked = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        if locked.status != D.DRAFT:
            raise ContractError('Only a draft can be edited. Revise the contract to start a new version.')
        if expected_revision is not None and int(expected_revision) != locked.draft_revision:
            raise ContractError('This draft was saved somewhere else since you opened it. Reload to see the '
                                'latest version (your text is still in the editor).')
        for f in DRAFT_FIELDS:
            if f in data:
                setattr(locked, f, data[f])
        if 'owner' in data:
            locked.owner = data['owner']
        if 'account_manager' in data:
            locked.account_manager = data['account_manager']
        if 'sections' in data:
            locked.sections = normalize_sections(data['sections'])
        if 'line_items' in data:
            locked.line_items = normalize_line_items(data['line_items'])
        _recompute_totals(locked)
        locked.draft_revision += 1
        locked.draft_saved_at = timezone.now()
        locked.draft_saved_by = by
        locked.save()
        if 'signers' in data:
            locked.signers.all().delete()
            for i, s in enumerate(data['signers'], start=1):
                ContractSigner.objects.create(contract=locked, role=s['role'], name=s['name'], email=s['email'],
                                              title=s.get('title', ''), order=s.get('order') or i,
                                              user=s.get('user'))
        if 'notify_users' in data:
            locked.notify_users.set(data['notify_users'])
    last = contract.events.filter(kind='draft_edited').order_by('-at').first()
    if last is None or last.at < timezone.now() - timedelta(minutes=15) or last.actor_id != getattr(by, 'pk', None):
        events.record(locked, 'draft_edited', actor=by, request=request)
    contract.refresh_from_db()
    return contract.draft_revision


def add_attachment(contract, upload, by, request=None):
    if contract.status != D.DRAFT:
        raise ContractError('Attachments can be changed on a draft only.')
    allowed = ('application/pdf', 'image/png', 'image/jpeg', 'text/plain', 'text/csv',
               'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
               'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    ctype = (getattr(upload, 'content_type', '') or '').split(';')[0].strip().lower()
    if ctype not in allowed:
        raise ContractError('Attach PDF, Word, Excel, PNG, JPEG, text or CSV files.')
    data = upload.read(ContractAttachment.MAX_BYTES + 1)
    if len(data) > ContractAttachment.MAX_BYTES:
        raise ContractError('Attachments are limited to 10 MB.')
    import os
    from django.utils.text import get_valid_filename
    name = get_valid_filename(os.path.basename(upload.name or 'attachment'))[:200] or 'attachment'
    a = ContractAttachment.objects.create(contract=contract, name=name, content_type=ctype, size=len(data),
                                          sha256=sha256(data), data=data, uploaded_by=by)
    events.record(contract, 'attachment_added', actor=by, request=request, message=f'{name} ({len(data)} bytes)')
    return a


def remove_attachment(attachment, by, request=None):
    contract = attachment.contract
    if contract.status != D.DRAFT:
        raise ContractError('Attachments can be changed on a draft only.')
    cited = any(any(a.get('id') == attachment.pk for a in (v.content or {}).get('attachments', []))
                for v in contract.versions.all())
    if cited:
        attachment.removed_at = timezone.now()
        attachment.save(update_fields=['removed_at'])
    else:
        attachment.delete()
    events.record(contract, 'attachment_removed', actor=by, request=request, message=attachment.name)


# --- issuing / approval ----------------------------------------------------------

def preview(contract):
    """(content, body_html, unresolved) of the draft as it would be issued."""
    settings = settings_for(contract)
    content, unresolved = build_content(contract, settings, signing_config(contract, settings), preview=True)
    return content, render_body(content), unresolved


def issue_errors(contract):
    settings = settings_for(contract)
    signing = signing_config(contract, settings)
    _content, unresolved = build_content(contract, settings, signing)
    return validate_for_issue(contract, unresolved, signing)


def _issue(contract, by, *, requires_approval):
    """Freeze the draft into a version (or reuse the current one when its
    content is unchanged and it is still unsent). Caller holds the lock."""
    from .pdf import build_pdf
    settings = settings_for(contract)
    signing = signing_config(contract, settings)
    content, unresolved = build_content(contract, settings, signing)
    errors = validate_for_issue(contract, unresolved, signing)
    if errors:
        raise ContentError(errors)
    content['consent_text'] = settings.consent_text
    content['intent_text'] = settings.intent_text
    cur = contract.current_version
    nxt = (contract.versions.order_by('-version_number').values_list('version_number', flat=True).first() or 0) + 1
    content['version'] = nxt
    if cur is not None and cur.status in (ContractVersion.PENDING_APPROVAL, ContractVersion.READY):
        probe = dict(content, version=cur.version_number)
        if sha256(canonical_json(probe)) == cur.content_hash:
            return cur, False
        _supersede_version(cur, by, reason='Edited before sending')
    digest = sha256(canonical_json(content))
    body = render_body(content, version_number=nxt)
    snap = snapshot_html(content, body)
    try:
        pdf = build_pdf(content, version_number=nxt)
    except Exception:  # noqa: BLE001 — the HTML snapshot is the evidence; retried at send
        logger.exception('issued contract PDF failed')
        pdf = None
    v = ContractVersion.objects.create(
        contract=contract, version_number=nxt, content=content, content_hash=digest, rendered_html=body,
        snapshot_html=snap, snapshot_hash=sha256(snap.encode('utf-8')), pdf=pdf, pdf_hash=sha256(pdf) if pdf else '',
        consent_text=settings.consent_text, intent_text=settings.intent_text, signing_order=signing['order'],
        require_verification=signing['verification'], require_countersignature=signing['countersignature'],
        requires_approval=requires_approval,
        status=ContractVersion.PENDING_APPROVAL if requires_approval else ContractVersion.READY,
        issued_by=by)
    contract.current_version = v
    ContractDocument.objects.filter(pk=contract.pk).update(current_version=v)
    events.record(contract, 'issued', version=v, actor=by,
                  message=f'Version {nxt} frozen (SHA-256 {digest[:12]}…)',
                  data={'content_hash': digest, 'snapshot_hash': v.snapshot_hash, 'pdf_hash': v.pdf_hash})
    return v, True


def submit(contract, by, request=None):
    """Draft → pending approval (when approval is required) or ready to send."""
    perms.require(by, perms.EDIT, contract.organization_id)
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        if contract.status != D.DRAFT:
            raise InvalidTransition('Only a draft can be finalized.')
        needs = signing_config(contract)['approval']
        v, _new = _issue(contract, by, requires_approval=needs)
        if needs and v.status == ContractVersion.PENDING_APPROVAL:
            transition(contract, D.PENDING_APPROVAL)
            events.record(contract, 'submitted', version=v, actor=by, request=request,
                          message=f'Version {v.version_number} submitted for internal approval')
        else:
            transition(contract, D.READY)
    if contract.status == D.PENDING_APPROVAL:
        notify.notify(contract, 'approval', f'Contract {contract.reference} "{contract.title}" for '
                      f'{contract.client_name} is waiting for internal approval.',
                      f'approval:{v.pk}', users=[u for u in notify.approvers(contract) if u.pk != by.pk])
        jobs.run_now(_pending_staff_jobs(contract))
    return v


def _pending_staff_jobs(contract):
    from .models import ContractJob
    return list(ContractJob.objects.filter(contract=contract, status=ContractJob.PENDING, kind='staff_email'))


def decide(contract, by, *, approve, content_hash, comment='', request=None):
    perms.require(by, perms.APPROVE, contract.organization_id)
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        v = contract.current_version
        if contract.status != D.PENDING_APPROVAL or v is None or v.status != ContractVersion.PENDING_APPROVAL:
            raise InvalidTransition('This contract is not waiting for approval.')
        if content_hash != v.content_hash:
            raise ContractError('The contract changed since you opened it. Review the current version again.')
        settings = settings_for(contract)
        if approve and v.issued_by_id == by.pk and not settings.allow_self_approval:
            raise ContractError('Someone other than the person who submitted it must approve this contract.')
        ContractApproval.objects.create(version=v, decision='approved' if approve else 'rejected',
                                        content_hash=v.content_hash, decided_by=by,
                                        decided_by_name=by.get_full_name() or by.username, comment=comment[:2000])
        if approve:
            v.status = ContractVersion.READY
            v.save(update_fields=['status'])
            transition(contract, D.READY)
            events.record(contract, 'approved', version=v, actor=by, request=request,
                          message=f'Version {v.version_number} approved' + (f': {comment}' if comment else ''),
                          data={'content_hash': v.content_hash})
        else:
            v.status = ContractVersion.REJECTED
            v.save(update_fields=['status'])
            transition(contract, D.DRAFT)
            events.record(contract, 'rejected', version=v, actor=by, request=request,
                          message=f'Version {v.version_number} sent back' + (f': {comment}' if comment else ''))
    notify.notify(contract, 'approval_decision',
                  f'Contract {contract.reference} was {"approved" if approve else "sent back for changes"} by '
                  f'{by.get_full_name() or by.username}.', f'decision:{v.pk}',
                  users=[u for u in [contract.owner, v.issued_by] if u is not None and u.pk != by.pk])
    jobs.run_now(_pending_staff_jobs(contract))
    return v


def approval_valid(version) -> bool:
    if not version.requires_approval:
        return True
    last = version.approvals.order_by('-decided_at', '-pk').first()
    return bool(last and last.decision == 'approved' and last.content_hash == version.content_hash)


# --- sending ---------------------------------------------------------------------

def _expiry(contract, settings, now):
    days = contract.invitation_expiry_days or settings.invitation_expiry_days or 30
    exp = now + timedelta(days=days)
    if contract.acceptance_deadline:
        end = timezone.make_aware(datetime.combine(contract.acceptance_deadline, time(23, 59, 59)))
        exp = min(exp, end)
    return exp


def send(contract, by, *, email=True, request=None, signers=None):
    """Ready to send → sent: one invitation per signer of the version."""
    perms.require(by, perms.SEND, contract.organization_id)
    created = []
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        v = contract.current_version
        if contract.status != D.READY or v is None or v.status != ContractVersion.READY:
            raise InvalidTransition('Only a contract that is ready to send can be sent.')
        if not approval_valid(v):
            raise ContractError('This exact version has not been approved.')
        if contract.acceptance_deadline and contract.acceptance_deadline < timezone.localdate():
            raise ContractError('The acceptance deadline has passed; revise the contract and set a new one.')
        if not v.pdf:
            from .pdf import build_pdf
            try:
                pdf = build_pdf(v.content, version_number=v.version_number)
            except Exception as exc:  # noqa: BLE001
                raise ContractError(f'The PDF of this version could not be made: {exc}')
            v.pdf, v.pdf_hash = pdf, sha256(pdf)
            v.save(update_fields=['pdf', 'pdf_hash'])
        signers = list(signers if signers is not None else contract.signers.all())
        from .content import ordered_signers
        ordered = ordered_signers(signers)
        specs = v.signer_specs
        if len(specs) != len(ordered):
            raise ContractError('The signers changed since this version was issued; revise and issue it again.')
        for spec, s in zip(specs, ordered):
            inv = ContractInvitation.objects.create(
                version=v, contract=contract, signer_ref=spec['ref'], role=spec['role'], name=s.name, email=s.email,
                title=s.title, order=spec['order'], user=s.user, created_by=by, status=ContractInvitation.WAITING)
            created.append(inv)
            events.record(contract, 'invitation_issued', version=v, invitation=inv, actor=by,
                          message=f'{spec["label"]}: {s.name} <{s.email}>')
        v.status = ContractVersion.SENT
        v.save(update_fields=['status'])
        transition(contract, D.SENT, sent_at=timezone.now())
        events.record(contract, 'sent', version=v, actor=by, request=request,
                      message=f'Version {v.version_number} sent to {len(created)} signer(s)'
                              + ('' if email else ' (links only, no e-mail)'))
        queued = activate_next(v, by=by, email=email)
    jobs.run_now(queued)
    return created


def activate_next(version, *, by=None, email=True):
    """Open the invitations whose turn it is. Returns queued e-mail jobs.
    Client signers first (all at once, or one at a time in sequential
    order); internal countersigners once every client signer has signed."""
    contract = version.contract
    settings = settings_for(contract)
    invs = list(version.invitations.all())
    client = [i for i in invs if i.role == 'client']
    internal = [i for i in invs if i.role == 'internal']
    open_now = []
    if any(i.status in (ContractInvitation.DECLINED,) for i in invs):
        return []
    pending_client = [i for i in client if i.status != ContractInvitation.SIGNED]
    if pending_client:
        if version.signing_order == 'sequential':
            first = sorted(pending_client, key=lambda i: i.order)[0]
            open_now = [first] if first.status == ContractInvitation.WAITING else []
        else:
            open_now = [i for i in pending_client if i.status == ContractInvitation.WAITING]
    else:
        open_now = [i for i in sorted(internal, key=lambda i: i.order) if i.status == ContractInvitation.WAITING][:1] \
            if version.signing_order == 'sequential' else \
            [i for i in internal if i.status == ContractInvitation.WAITING]
    queued = []
    now = timezone.now()
    for inv in open_now:
        n = ContractInvitation.objects.filter(pk=inv.pk, status=ContractInvitation.WAITING).update(
            status=ContractInvitation.ACTIVE, activated_at=now, expires_at=_expiry(contract, settings, now),
            delivery_status='queued' if email else '')
        if not n:
            continue
        inv.refresh_from_db()
        events.record(contract, 'invitation_activated', version=version, invitation=inv, actor=by,
                      message=f'{inv.name} may now sign (link expires {inv.expires_at:%Y-%m-%d})')
        if email:
            job, _ = jobs.enqueue('invitation_email', f'invite:{inv.pk}:{inv.send_count + 1}', contract=contract,
                                  version=version, invitation=inv)
            events.record(contract, 'email_queued', version=version, invitation=inv, actor_label='System',
                          message=f'Invitation e-mail to {inv.email} queued')
            queued.append(job)
    return queued


def resend(inv, by, request=None):
    perms.require(by, perms.SEND, inv.contract.organization_id)
    if inv.status != ContractInvitation.ACTIVE or inv.is_expired():
        raise ContractError('Only an active, unexpired invitation can be resent. Replace it instead.')
    if inv.contract.status not in D.OPEN_FOR_SIGNING:
        raise ContractError('This contract is not open for signing.')
    from .models import ContractJob
    n = inv.send_count + ContractJob.objects.filter(invitation=inv, kind='invitation_email').count() + 1
    job, created = jobs.enqueue('invitation_email', f'invite:{inv.pk}:{n}', contract=inv.contract,
                                version=inv.version, invitation=inv)
    ContractInvitation.objects.filter(pk=inv.pk).update(delivery_status='queued')
    events.record(inv.contract, 'invitation_resent', version=inv.version, invitation=inv, actor=by, request=request,
                  message=f'Resent to {inv.email}')
    jobs.run_now([job])
    return job


def copy_link(inv, by, request=None) -> str:
    """Mint a link for staff to share by other means; shown once."""
    from django.urls import reverse
    from . import mail, signing
    perms.require(by, perms.SEND, inv.contract.organization_id)
    if inv.status != ContractInvitation.ACTIVE or inv.is_expired():
        raise ContractError('Only an active, unexpired invitation has a signing link.')
    raw, _token = signing.mint_token(inv, 'link', by)
    events.record(inv.contract, 'link_generated', version=inv.version, invitation=inv, actor=by, request=request,
                  message=f'Signing link for {inv.name} generated to share directly')
    path = reverse('contract_sign:open', kwargs={'token': raw})
    try:
        return mail.base_url() + path
    except mail.MailNotConfigured:
        if request is not None:
            return request.build_absolute_uri(path)
        raise ContractError('Set the site URL (Settings → General) to make signing links.')


def revoke(inv, by, reason='', request=None, *, status=ContractInvitation.REVOKED, record=True):
    if by is not None:
        perms.require(by, perms.SEND, inv.contract.organization_id)
    now = timezone.now()
    n = ContractInvitation.objects.filter(pk=inv.pk, status__in=ContractInvitation.OPEN).update(
        status=status, revoked_at=now, revoke_reason=reason[:255])
    inv.tokens.filter(revoked_at__isnull=True).update(revoked_at=now)
    jobs.cancel_for(invitation=inv, kinds=['invitation_email', 'reminder_email'], reason=f'invitation {status}')
    if n and record:
        events.record(inv.contract, 'invitation_revoked' if status == ContractInvitation.REVOKED else
                      'invitation_expired' if status == ContractInvitation.EXPIRED else 'superseded',
                      version=inv.version, invitation=inv, actor=by, request=request,
                      message=f'{inv.name} <{inv.email}>' + (f': {reason}' if reason else ''))
    inv.refresh_from_db()
    return bool(n)


def replace_invitation(inv, by, *, name, email, title='', request=None):
    """Revoke an invitation and issue a new one for the same signer slot
    (e.g. a corrected address, or a fresh expiry)."""
    perms.require(by, perms.SEND, inv.contract.organization_id)
    contract = ContractDocument.objects.get(pk=inv.contract_id)
    if contract.status not in D.OPEN_FOR_SIGNING or contract.current_version_id != inv.version_id:
        raise ContractError('This contract is not open for signing.')
    if inv.status in (ContractInvitation.SIGNED, ContractInvitation.DECLINED):
        raise ContractError('This signer has already answered.')
    others = inv.version.invitations.exclude(pk=inv.pk).filter(
        status__in=ContractInvitation.OPEN + (ContractInvitation.SIGNED,))
    if others.filter(email__iexact=email).exists():
        raise ContractError('Another signer already uses that e-mail address.')
    with transaction.atomic():
        revoke(inv, by, reason='Replaced', record=False)
        new = ContractInvitation.objects.create(
            version=inv.version, contract=contract, signer_ref=inv.signer_ref, role=inv.role, name=name[:200],
            email=email, title=title[:200], order=inv.order, user=inv.user, created_by=by,
            status=ContractInvitation.WAITING)
        ContractInvitation.objects.filter(pk=inv.pk).update(replaced_by=new)
        events.record(contract, 'invitation_replaced', version=inv.version, invitation=new, actor=by, request=request,
                      message=f'{inv.name} <{inv.email}> replaced by {new.name} <{new.email}>')
        queued = activate_next(inv.version, by=by)
    jobs.run_now(queued)
    return new


# --- revise / void / supersede ---------------------------------------------------

def _supersede_version(v, by, reason=''):
    for inv in v.invitations.filter(status__in=ContractInvitation.OPEN):
        revoke(inv, None, reason='The contract was revised', status=ContractInvitation.SUPERSEDED, record=False)
    if v.status not in (ContractVersion.SIGNED, ContractVersion.VOIDED, ContractVersion.SUPERSEDED):
        v.status = ContractVersion.SUPERSEDED
        v.superseded_at = timezone.now()
        v.save(update_fields=['status', 'superseded_at'])
    events.record(v.contract, 'superseded', version=v, actor=by,
                  message=f'Version {v.version_number} superseded' + (f': {reason}' if reason else ''))


def revise(contract, by, reason='', request=None):
    """Back to a draft. A sent version is superseded and its links revoked;
    an unsent one is kept until the next issue shows whether it changed."""
    perms.require(by, perms.EDIT, contract.organization_id)
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        if contract.status in (D.SIGNED, D.VOIDED, D.SUPERSEDED):
            raise InvalidTransition('A signed, voided or superseded contract cannot be edited. '
                                    'Create an amendment or a replacement instead.')
        if contract.status == D.DRAFT:
            return contract
        v = contract.current_version
        if v is not None and v.status not in (ContractVersion.PENDING_APPROVAL, ContractVersion.READY):
            _supersede_version(v, by, reason or 'Revised')
            jobs.cancel_for(contract=contract, kinds=['invitation_email', 'reminder_email', 'finalize'],
                            reason='contract revised')
        transition(contract, D.DRAFT)
    return contract


def void(contract, by, reason, request=None):
    perms.require(by, perms.VOID, contract.organization_id)
    reason = (reason or '').strip()
    if len(reason) < 3:
        raise ContractError('Give a reason for voiding.')
    with transaction.atomic():
        contract = ContractDocument.objects.select_for_update().get(pk=contract.pk)
        transition(contract, D.VOIDED, voided_at=timezone.now(), voided_by=by, void_reason=reason[:2000])
        v = contract.current_version
        if v is not None:
            for inv in v.invitations.filter(status__in=ContractInvitation.OPEN):
                revoke(inv, None, reason='Contract voided', record=False)
            if v.status not in (ContractVersion.SIGNED, ContractVersion.SUPERSEDED):
                v.status = ContractVersion.VOIDED
                v.save(update_fields=['status'])
        jobs.cancel_for(contract=contract, kinds=['invitation_email', 'reminder_email'], reason='contract voided')
        events.record(contract, 'voided', version=v, actor=by, request=request, message=reason[:450])
    notify.notify(contract, 'voided', f'Contract {contract.reference} "{contract.title}" was voided by '
                  f'{by.get_full_name() or by.username}: {reason[:200]}', f'voided:{contract.pk}')
    jobs.run_now(_pending_staff_jobs(contract))
    return contract


def create_billing_contract(contract, by, request=None):
    """Create a draft PSA billing contract from a signed contract document."""
    from psa.models import Contract
    perms.require(by, perms.EDIT, contract.organization_id)
    if contract.status != D.SIGNED:
        raise ContractError('Only a signed contract can create a billing contract.')
    if contract.billing_contract_id:
        return contract.billing_contract
    freq = {'monthly': 'monthly', 'quarterly': 'quarterly', 'annually': 'yearly'}.get(contract.billing_frequency,
                                                                                      'none')
    bc = Contract.objects.create(
        organization=contract.organization, client_org=contract.organization, name=contract.title[:200],
        contract_type='managed_services', status='draft', start_date=contract.effective_date or timezone.localdate(),
        end_date=contract.expiration_date, billing_frequency=freq, recurring_amount=contract.recurring_total,
        auto_renew=contract.auto_renew)
    ContractDocument.objects.filter(pk=contract.pk).update(billing_contract=bc)
    contract.billing_contract = bc
    events.record(contract, 'billing_linked', actor=by, request=request,
                  message=f'Draft PSA billing contract #{bc.pk} created (review it before activating)')
    return bc
