"""The top bar's notification bell.

There is no general notification model. The bell adds up counts the app
already keeps, each computed with the same checks as the page it links to,
so a number never points at a page the user cannot open:

* PSA approvals waiting for staff (psa.views.approval_list: PSA on, MSP
  staff; tenant scope as on the page; customer sign-offs excluded, staff
  cannot decide those);
* RMM approval requests another technician raised that this user is
  qualified to decide (rmm_permissions.views.approvals: a technician;
  rmm_permissions.approvals.open_for + refusal);
* unread secure notes (core.securenotes_views.secure_note_inbox: the
  module on; the inbox's own query);
* unread contract notifications (contracts.views.dashboard: MSP staff with
  contracts_view; only contracts the user may see);
* a newer release found by the scheduled update check (superusers).

Counts are cached per user and customer for a minute, so a page costs one
cache read; the pages themselves always show live data.
"""
import logging

from django.core.cache import cache
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
# Bound on how many RMM requests are checked one by one for qualification.
RMM_CHECK_LIMIT = 25


def _psa_approvals(user, ctx):
    if not ctx.get('psa_enabled'):
        return None
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return None
    from psa.models import PSAApproval
    org = _org(ctx)
    qs = PSAApproval.objects.filter(status='pending', is_client_approval=False)
    if org is not None:
        qs = qs.filter(organization=org)
    elif not (user.is_superuser or ctx.get('is_staff_user')):
        return None
    return qs.count()


def _rmm_approvals(user, ctx):
    from rmm_permissions.decision import is_technician
    if not is_technician(user):
        return None
    from rmm_permissions import approvals as svc
    n = 0
    for a in svc.open_for(user).exclude(requester=user)[:RMM_CHECK_LIMIT]:
        try:
            if not svc.refusal(a, user):
                n += 1
        except Exception:
            continue
    return n


def _secure_notes(user, ctx):
    if not ctx.get('secure_notes_enabled'):
        return None
    from core.models import SecureNote
    return (SecureNote.objects.filter(recipients=user, is_deleted=False)
            .exclude(expires_at__lt=timezone.now())
            .exclude(read_by=user).count())


def _contracts(user, ctx):
    from psa.visibility import is_msp_staff
    from contracts import permissions as perms
    if not (is_msp_staff(user) and perms.has_any(user, perms.VIEW)):
        return None
    from contracts.models import ContractDocument, ContractNotification
    return ContractNotification.objects.filter(
        user=user, read_at__isnull=True,
        contract__in=perms.scope(ContractDocument.objects.all(), user)).count()


# key, label, icon, url name, counter
SOURCES = (
    ('psa_approvals', _('Approvals waiting for a decision'), 'fa-circle-check', 'psa:approval_list',
     _psa_approvals),
    ('rmm_approvals', _('RMM approval requests'), 'fa-user-lock', 'rmm_permissions:approvals',
     _rmm_approvals),
    ('secure_notes', _('Unread secure notes'), 'fa-lock', 'core:secure_note_inbox', _secure_notes),
    ('contracts', _('Contract notifications'), 'fa-file-signature', 'contracts:dashboard', _contracts),
)


def _org(ctx):
    request = ctx.get('request')
    org = getattr(request, 'current_organization', None) if request is not None else None
    return org if org is not None else ctx.get('current_organization')


def _counts(user, ctx):
    org = _org(ctx)
    joined = getattr(user, 'date_joined', None)
    # The module switches the sources depend on are part of the key, so
    # turning one off drops its row at once rather than after a minute.
    key = 'navnotes:%s:%s:%s:%d%d' % (user.pk, joined.timestamp() if joined else '',
                                      getattr(org, 'pk', ''), bool(ctx.get('psa_enabled')),
                                      bool(ctx.get('secure_notes_enabled')))
    counts = cache.get(key)
    if counts is not None:
        return counts
    counts = {}
    for name, _label, _icon, _url, fn in SOURCES:
        try:
            n = fn(user, ctx)
        except Exception:
            logger.exception('notification source %s failed', name)
            n = None
        if n is not None:
            counts[name] = n
    cache.set(key, counts, CACHE_SECONDS)
    return counts


def for_context(ctx):
    """``{'items': [{key, label, icon, href, count}], 'total'}`` for the bell.

    Only sources the user may open are listed (with a zero count when there
    is nothing new), and each link passes the sidebar's URL-prefix probe.
    """
    user = ctx.get('user')
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'items': [], 'total': 0}
    from core.navigation import _PermProbe
    probe = _PermProbe(ctx)
    counts = _counts(user, ctx)
    items = []
    for name, label, icon, url_name, _fn in SOURCES:
        if name not in counts:
            continue
        try:
            href = reverse(url_name)
        except NoReverseMatch:
            continue
        if not probe.allows(href):
            continue
        items.append({'key': name, 'label': label, 'icon': f'fas {icon}', 'href': href,
                      'count': counts[name]})
    # A newer release the scheduled update check found (superusers only, the
    # ones who can apply it; core.context_processors._update_badge).
    badge = ctx.get('update_badge')
    if badge and user.is_superuser:
        try:
            items.insert(0, {'key': 'update', 'label': _('Update available: v%(v)s') % {'v': badge['version']},
                             'icon': 'fas fa-circle-arrow-up', 'href': reverse('core:system_updates'),
                             'count': 1})
        except NoReverseMatch:
            pass
    return {'items': items, 'total': sum(i['count'] for i in items)}
