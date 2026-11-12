"""Link and view tracking: telling likely people from scanners.

Detection is a heuristic and will sometimes be wrong. Three levels are kept
apart, and only the last two ever count as a view:

1. **Link requested** — every request for the signing link is recorded with
   the indicators below. E-mail security scanners, link previews and
   prefetchers land here and nowhere else.
2. **Likely human view** — the viewer page sends a POST "beacon" only after
   real interaction in a visible tab (pointer, touch, key or scroll, at least
   1.5 s after the page loaded). The beacon carries a signed, single-use,
   per-page-view nonce and the page's CSRF token, and is refused from an
   automated-looking client. Sandboxes that run scripts and fake input can
   still pass; that is why it is called *likely*.
3. **Verified signer view** — a view after the signer entered a code e-mailed
   to the invited address (or opened it while signed in to their own staff
   account). Only this level supports saying the named person opened it.

Indicators (strong: any one marks the request automated; weak: two needed):
  strong  HEAD request; Purpose / Sec-Purpose / X-Purpose / X-Moz header of
          prefetch or preview; no User-Agent; a User-Agent of a known
          scanner, link-preview bot, crawler, HTTP library or headless
          browser; a client IP in CONTRACTS_SCANNER_NETWORKS
  weak    no Accept-Language; requested within 20 seconds of the e-mail
          being sent; no Sec-Fetch-Mode / Sec-Fetch-Site from a browser
          that would send them
No tracking pixels are used.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import timedelta

from django.conf import settings as django_settings
from django.db.models import F
from django.utils import timezone

from . import events, notify
from .models import ContractDocument, ContractInvitation, ContractSettings

SCANNER_UA = re.compile(
    r'(?i)(bot\b|bot/|crawler|spider|slurp|preview|scanner|scan/|safelinks|safe ?links|protection|'
    r'barracuda|mimecast|proofpoint|messagelabs|symantec|fireeye|trend ?micro|forcepoint|ironport|cisco|'
    r'sophos|zscaler|mcafee|kaspersky|bitdefender|checkpoint|fortinet|virustotal|urldefense|'
    r'microsoft office protection|outlook-|ms-office|microsoft\.office|google-safety|googleother|'
    r'facebookexternalhit|slack|discord|whatsapp|telegram|skype|linkedin|twitter|embedly|iframely|'
    r'curl/|wget/|python-|aiohttp|httpx|go-http-client|java/|okhttp|libwww|apache-httpclient|node-fetch|'
    r'axios/|postman|headlesschrome|phantomjs|puppeteer|playwright|electron/|lighthouse)')
PREFETCH_HEADERS = ('HTTP_PURPOSE', 'HTTP_SEC_PURPOSE', 'HTTP_X_PURPOSE', 'HTTP_X_MOZ')
FAST_AFTER_SEND = timedelta(seconds=20)


def _scanner_networks():
    nets = []
    for cidr in getattr(django_settings, 'CONTRACTS_SCANNER_NETWORKS', []) or []:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return nets


def classify(request, invitation=None, now=None) -> dict:
    from core.client_ip import get_client_ip
    now = now or timezone.now()
    meta = request.META
    strong, weak = [], []
    if request.method == 'HEAD':
        strong.append('head_request')
    for h in PREFETCH_HEADERS:
        v = (meta.get(h) or '').lower()
        if 'prefetch' in v or 'preview' in v or 'prerender' in v:
            strong.append('prefetch_header')
            break
    ua = meta.get('HTTP_USER_AGENT') or ''
    if not ua.strip():
        strong.append('no_user_agent')
    else:
        m = SCANNER_UA.search(ua)
        if m:
            strong.append(f'automated_user_agent:{m.group(0).strip().lower()[:30]}')
    ip = get_client_ip(request)
    try:
        addr = ipaddress.ip_address(ip) if ip else None
    except ValueError:
        addr = None
    if addr is not None and any(addr in n for n in _scanner_networks()):
        strong.append('scanner_network')
    if not meta.get('HTTP_ACCEPT_LANGUAGE'):
        weak.append('no_accept_language')
    if invitation is not None and invitation.last_sent_at and now - invitation.last_sent_at < FAST_AFTER_SEND:
        weak.append('requested_seconds_after_email')
    if re.search(r'(?i)chrome/|firefox/|edg/', ua) and not meta.get('HTTP_SEC_FETCH_MODE'):
        weak.append('no_fetch_metadata')
    automated = bool(strong) or len(weak) >= 2
    return {'automated': automated, 'indicators': strong + weak}


def record_link_request(inv, request, classification):
    ContractInvitation.objects.filter(pk=inv.pk).update(link_request_count=F('link_request_count') + 1)
    ContractDocument.objects.filter(pk=inv.contract_id).update(link_request_count=F('link_request_count') + 1)
    events.record(inv.contract, 'link_requested', version=inv.version, invitation=inv,
                  actor_label='Automated client (likely)' if classification['automated'] else 'Link holder',
                  request=request, data={'automated': classification['automated'],
                                         'indicators': classification['indicators']},
                  message='Link requested' + (' — looks automated (' + ', '.join(classification['indicators'])
                                              + ')' if classification['automated'] else ''))


VERIFIED_LEVELS = ('email_code', 'staff_account')


def view_message(inv, level):
    c = inv.contract
    what = f'{c.reference} "{c.title}"'
    if level == 'email_code':
        return f'{inv.name} ({inv.email}) opened {what} after entering a code sent to that address.'
    if level == 'staff_account':
        return f'{inv.name} opened {what} while signed in to their own account.'
    return (f'The contract link for {c.client_name} was opened — {what}. Likely a person; identity not verified, '
            'so this does not show who opened it.')


def record_view(inv, request, level, now=None):
    """A likely human (or verified) view. Updates counters, moves Sent to
    Viewed (and nothing else), and raises the de-duplicated alerts."""
    from . import services
    now = now or timezone.now()
    verified = level in VERIFIED_LEVELS
    upd = {'view_count': F('view_count') + 1, 'last_viewed_at': now}
    if verified:
        upd['verified_view_count'] = F('verified_view_count') + 1
    ContractInvitation.objects.filter(pk=inv.pk).update(**upd)
    ContractInvitation.objects.filter(pk=inv.pk, first_viewed_at__isnull=True).update(first_viewed_at=now)
    ContractDocument.objects.filter(pk=inv.contract_id).update(view_count=F('view_count') + 1, last_viewed_at=now)
    ContractDocument.objects.filter(pk=inv.contract_id, first_viewed_at__isnull=True).update(first_viewed_at=now)
    contract = inv.contract
    events.record(contract, 'verified_view' if verified else 'human_view', version=inv.version, invitation=inv,
                  actor_label=f'{inv.name} (verified)' if verified else 'Link holder (not verified)',
                  request=request, data={'verification': level},
                  message=view_message(inv, level))
    services.transition(contract, ContractDocument.VIEWED, only_from=(ContractDocument.SENT,))
    settings = ContractSettings.for_organization(contract.organization)
    told = False
    if notify.raise_alert(contract, f'first-view:{inv.version_id}', 'first_view'):
        notify.notify(contract, 'view', view_message(inv, level), f'first-view:{inv.version_id}', settings=settings,
                      subject=f'[{contract.reference}] Contract opened')
        ContractInvitation.objects.filter(pk=inv.pk).update(last_view_alert_at=now)
        told = True
    if verified and notify.raise_alert(contract, f'verified-view:{inv.pk}', 'verified_view') and not told:
        notify.notify(contract, 'view', view_message(inv, level), f'verified-view:{inv.pk}', settings=settings,
                      subject=f'[{contract.reference}] Contract opened by the signer')
        ContractInvitation.objects.filter(pk=inv.pk).update(last_view_alert_at=now)
        told = True
    if not told and settings.notify_repeat_views:
        cutoff = now - timedelta(minutes=max(1, settings.repeat_view_cooldown_minutes))
        from django.db.models import Q
        if ContractInvitation.objects.filter(pk=inv.pk).filter(
                Q(last_view_alert_at__isnull=True) | Q(last_view_alert_at__lt=cutoff)).update(last_view_alert_at=now):
            key = f'repeat-view:{inv.pk}:{int(now.timestamp())}'
            notify.notify(contract, 'view', 'Viewed again: ' + view_message(inv, level), key, settings=settings,
                          subject=f'[{contract.reference}] Contract viewed again')
            told = True
    if told:
        from . import jobs
        from .models import ContractJob
        jobs.run_now(list(ContractJob.objects.filter(contract=contract, kind='staff_email',
                                                     status=ContractJob.PENDING)[:20]))
    return told
