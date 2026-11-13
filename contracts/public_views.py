"""Public, account-less signing pages under /sign/ (see signing.py).

Every response here: a strict Referrer-Policy (no-referrer on the token
link itself; same-origin on the session pages, because browsers send
"Origin: null" on form posts from a no-referrer page and CSRF protection
then refuses them; those page URLs carry no secret), Cache-Control: no-store,
X-Robots-Tag: noindex, and only same-origin assets (no fonts, scripts or
styles from any CDN). Requests are rate-limited per client IP. GET requests
record what happened (link requested) but never sign, decline, verify or use
up an invitation; those are CSRF-protected POSTs.
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from . import events, notify, signing, tracking
from .models import ContractAttachment, ContractInvitation, ContractSettings

RATES = {'open': '30/m', 'page': '60/m', 'action': '20/m', 'code': '10/h', 'verify': '20/h', 'seen': '30/m'}


def _ip_key(group, request):
    from core.client_ip import get_client_ip
    return get_client_ip(request) or 'unknown'


def _limited(request, group) -> bool:
    from django_ratelimit.core import is_ratelimited
    return is_ratelimited(request, group=f'contracts.sign.{group}', key=_ip_key, rate=RATES[group],
                          method=['GET', 'HEAD', 'POST'], increment=True)


def _harden(resp, referrer='same-origin'):
    resp['Referrer-Policy'] = referrer
    resp['Cache-Control'] = 'no-store, private'
    resp['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


def public(group, referrer='same-origin'):
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if _limited(request, group):
                return _harden(render(request, 'contracts/sign/message.html', {
                    'title': 'Too many requests', 'text': 'Please wait a minute and try again.'}, status=429),
                    referrer)
            return _harden(view(request, *args, **kwargs), referrer)
        return wrapper
    return deco


def _message(request, title, text, status=200, inv=None):
    return render(request, 'contracts/sign/message.html', {'title': title, 'text': text, 'inv': inv}, status=status)


@public('open', referrer='no-referrer')
@require_http_methods(['GET', 'HEAD'])
def open_link(request, token):
    tok = signing.token_lookup(token)
    if tok is None:
        return _message(request, 'This link does not work',
                        'The link is incomplete, was replaced, or was withdrawn. Ask the sender for a new one.', 404)
    inv = tok.invitation
    cls = tracking.classify(request, inv)
    tracking.record_link_request(inv, request, cls)
    if request.method == 'HEAD':
        return HttpResponse(status=200)
    signing.bind_session(request, inv, token=tok)
    type(tok).objects.filter(pk=tok.pk).update(last_used_at=timezone.now())
    return redirect('contract_sign:page', public_id=inv.public_id)


def _inv(request, public_id):
    inv = get_object_or_404(ContractInvitation.objects.select_related('contract', 'version', 'contract__organization'),
                            public_id=public_id)
    if not signing.session_allows(request, inv):
        return inv, False
    return inv, True


def _no_session(request, inv):
    return _message(request, 'Open the link from your e-mail',
                    'For your security this page only opens from the personal link you were sent. Open that link '
                    'again (in this browser), or ask the sender for a new one.', 403)


CLOSED_TEXT = {
    'superseded': ('This version was replaced', 'The sender revised the contract, so this version can no longer be '
                   'signed. If you still need to sign, you will receive a new link.'),
    'revoked': ('This link was withdrawn', 'The sender withdrew this signing link. Ask them for a new one if you '
                'still need it.'),
    'expired': ('This link has expired', 'Ask the sender for a new link.'),
    'closed': ('This contract is closed', 'It is no longer open for signing.'),
}


@public('page')
@require_http_methods(['GET'])
def page(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        entry = signing.session_entry(request, inv)
        state = signing.page_state(inv)
        if entry and entry.get('inv') == inv.pk and state in CLOSED_TEXT:
            # This browser opened a genuine link that has since been closed:
            # say why, without showing the document.
            title, text = CLOSED_TEXT[state]
            return _message(request, title, text, inv=inv)
        return _no_session(request, inv)
    state = signing.page_state(inv)
    v = inv.version
    level = signing.verification_level(request, inv)
    settings = ContractSettings.for_organization(inv.contract.organization)
    from .content import DOC_CSS
    sig = getattr(inv, 'signature', None) if inv.status == ContractInvitation.SIGNED else None
    attachments = [a for a in v.content.get('attachments', [])]
    others = v.invitations.exclude(pk=inv.pk).filter(status__in=[ContractInvitation.SIGNED]).count()
    return render(request, 'contracts/sign/page.html', {
        'inv': inv, 'c': inv.contract, 'v': v, 'state': state, 'level': level,
        'needs_code': v.require_verification and level == 'link', 'nonce': signing.view_nonce(inv),
        'doc_css': DOC_CSS, 'brand': settings.provider_display_name(), 'brand_color': settings.brand_color,
        'sig': sig, 'attachments': attachments, 'signed_count': others, 'total': len(v.signer_specs),
        'final_ready': v.finalization_status == 'done', 'today': timezone.localdate(),
        'code_sent': bool(inv.code_sent_at and inv.code_expires_at and inv.code_expires_at > timezone.now()),
        'signer_denial': signing.signer_denial(request, inv) if state == 'open' else '',
    })


@public('seen')
@require_POST
def seen(request, public_id):
    """Interaction beacon from the viewer page (see tracking.py)."""
    inv, ok = _inv(request, public_id)
    if not ok:
        return HttpResponse(status=204)
    nonce = signing.check_view_nonce(inv, request.POST.get('nonce'))
    if not nonce or request.POST.get('interacted') != '1':
        return HttpResponse(status=204)
    if tracking.classify(request, inv)['automated']:
        return HttpResponse(status=204)
    if signing.page_state(inv) in ('superseded', 'revoked'):
        return HttpResponse(status=204)
    if not notify.raise_alert(inv.contract, f'view-nonce:{nonce}', 'nonce'):
        return HttpResponse(status=204)  # this page view was already counted
    tracking.record_view(inv, request, signing.verification_level(request, inv))
    return HttpResponse(status=204)


@public('code')
@require_POST
def request_code(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    if signing.page_state(inv) != 'open':
        return redirect('contract_sign:page', public_id=inv.public_id)
    try:
        signing.request_code(request, inv)
        messages.success(request, f'We e-mailed a 6-digit code to {inv.email}. It expires in 10 minutes.')
    except signing.SigningError as exc:
        messages.error(request, str(exc))
    return redirect('contract_sign:page', public_id=inv.public_id)


@public('verify')
@require_POST
def verify_code(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    try:
        if signing.check_code(request, inv, request.POST.get('code', '')):
            messages.success(request, 'Thank you — your e-mail address is verified.')
        else:
            messages.error(request, 'That code is not right. Check the e-mail and try again.')
    except signing.SigningError as exc:
        messages.error(request, str(exc))
    return redirect('contract_sign:page', public_id=inv.public_id)


@public('action')
@require_POST
def sign(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    try:
        signing.sign(request, inv, request.POST)
    except signing.SigningError as exc:
        messages.error(request, str(exc))
        return redirect('contract_sign:page', public_id=inv.public_id)
    messages.success(request, 'Thank you — your signature is recorded.')
    return redirect('contract_sign:page', public_id=inv.public_id)


@public('action')
@require_POST
def decline(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    if request.POST.get('confirm') != 'yes':
        messages.error(request, 'Tick the box to confirm that you decline.')
        return redirect('contract_sign:page', public_id=inv.public_id)
    try:
        signing.decline(request, inv, request.POST.get('reason', ''))
    except signing.SigningError as exc:
        messages.error(request, str(exc))
        return redirect('contract_sign:page', public_id=inv.public_id)
    messages.info(request, 'You declined this contract. The sender has been told.')
    return redirect('contract_sign:page', public_id=inv.public_id)


def _file(data, name, ctype):
    from django.utils.text import get_valid_filename
    resp = HttpResponse(bytes(data), content_type=ctype)
    resp['Content-Disposition'] = f'attachment; filename="{get_valid_filename(name)}"'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


@public('page')
@require_http_methods(['GET'])
def download(request, public_id):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    from .pdf import final_filename, issued_filename
    v = inv.version
    if signing.page_state(inv) in ('superseded', 'revoked'):
        raise Http404
    if v.final_pdf and inv.status == ContractInvitation.SIGNED:
        data, name, what = v.final_pdf, final_filename(v), 'signed copy'
    elif v.pdf:
        data, name, what = v.pdf, issued_filename(v), 'copy'
    else:
        raise Http404
    events.record(inv.contract, 'downloaded', version=v, invitation=inv, actor_label=inv.name, request=request,
                  message=f'Signer downloaded the {what}')
    return _file(data, name, 'application/pdf')


@public('page')
@require_http_methods(['GET'])
def attachment(request, public_id, pk):
    inv, ok = _inv(request, public_id)
    if not ok:
        return _no_session(request, inv)
    if signing.page_state(inv) in ('superseded', 'revoked'):
        raise Http404
    cited = {a['id']: a for a in inv.version.content.get('attachments', [])}
    if pk not in cited:
        raise Http404
    a = get_object_or_404(ContractAttachment, pk=pk, contract_id=inv.contract_id, sha256=cited[pk]['sha256'])
    return _file(a.data, a.name, 'application/octet-stream')
