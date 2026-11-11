"""
Technician workspace plumbing: recent devices, saved list views, opening a
record in its customer's context, and the extra My Work panels.

Access model
------------
Nothing here grants access. Every list is re-read through the same scoping
the destination page applies:

* customers: ``core.tenancy.accessible_org_ids`` (MSP staff and superusers
  reach every customer, everyone else their memberships and those customers'
  subsidiaries), narrowed by the role flag the destination needs
  (``accounts.permission_utils.orgs_with_perm``);
* devices and alerts additionally need the device's customer to be settled
  (``RMMDevice.OWNERSHIP_RESOLVED``) — an unowned device is invisible to
  every customer-scoped query until a technician decides;
* the device, alert, maintenance, review and AI panels are MSP staff only;
  a customer user's My Work keeps the ticket panels it always had.

"My customers" — the default scope of the device and alert panels — is the
customers the technician is working for right now: customers of their open
assigned tickets, customers they hold a live technician-access assignment
for, their memberships, and the customer selected in the switcher. MSP staff
can widen it to every customer they can reach (?scope=all, the same switch
My Work already had for its waiting queues).

Optional data sources
---------------------
Remote sessions (Rem0te) and remote jobs are built by other modules. They
plug in through ``register_source(name, fn)``; ``fn(request, customer_ids)``
returns ``{'count', 'items': [{title, context, url, action}], 'url'}`` or
None. A panel without a source is not drawn; My Work lists it once under
"Set up more of My Work" instead.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

logger = logging.getLogger('core')

PANEL_LIMIT = 6
RECENT_DEVICE_LIMIT = 6
RECENT_DEVICE_KEEP = 30
SLA_SOON = timedelta(hours=2)
MAINTENANCE_WINDOW = timedelta(days=7)
REVIEW_LOOKBACK = timedelta(days=7)
CONTEXT_TRAIL_TTL = timedelta(hours=4)
TRAIL_KEY = 'work_context_return'


# ---------------------------------------------------------------------------
# Optional sources
# ---------------------------------------------------------------------------

_SOURCES = {}


def register_source(name, fn):
    """Plug a data source into a My Work panel ('remote_sessions', 'jobs')."""
    _SOURCES[name] = fn


def _from_source(name, request, customer_ids):
    fn = _SOURCES.get(name)
    if fn is None:
        return None
    try:
        return fn(request, customer_ids)
    except Exception:  # a broken plug-in must not take My Work down
        logger.exception('My Work source %s failed', name)
        return None


# ---------------------------------------------------------------------------
# Scoping helpers
# ---------------------------------------------------------------------------

def _is_staff(user):
    from psa.visibility import is_msp_staff
    return bool(is_msp_staff(user))


def _narrow(qs, allowed, field='organization'):
    """`allowed` is None (every customer) or a set of ids."""
    if allowed is None:
        return qs
    return qs.filter(**{f'{field}_id__in': allowed})


def _intersect(a, b):
    """Intersection where None means 'everything'."""
    if a is None:
        return b
    if b is None:
        return a
    return set(a) & set(b)


def work_customer_ids(request, scope_all=False):
    """Customers the device / alert panels read (None = every customer).

    Always within ``accessible_org_ids``. Without ``scope_all`` it is the
    technician's working set (see the module docstring)."""
    from core.tenancy import accessible_org_ids
    from core.utils import descendant_org_ids

    reach = accessible_org_ids(request)
    if scope_all and _is_staff(request.user):
        return reach

    user = request.user
    ids = set()
    try:
        from psa.models import Ticket
        from psa.my_work import open_q
        ids.update(Ticket.objects.filter(open_q(), assigned_to=user)
                   .values_list('organization_id', flat=True).distinct())
    except Exception:
        logger.debug('My Work: ticket customers unavailable', exc_info=True)
    try:
        from tech_access.models import AccessAssignment
        ids.update(AccessAssignment.objects.live().filter(
            Q(user=user) | Q(group__members=user)).values_list('organization_id', flat=True))
    except Exception:
        logger.debug('My Work: technician access unavailable', exc_info=True)
    for org_id in user.memberships.filter(is_active=True).values_list('organization_id', flat=True):
        ids.update(descendant_org_ids(org_id))
    current = getattr(request, 'current_organization', None)
    if current is not None:
        ids.update(descendant_org_ids(current))
    ids.discard(None)
    return _intersect(reach, ids)


# ---------------------------------------------------------------------------
# Devices: kinds, opening in context, recent devices
# ---------------------------------------------------------------------------

def _asset_model():
    from assets.models import Asset
    return Asset


def _rmm_model():
    from integrations.models import RMMDevice
    return RMMDevice


def _hardware_model():
    from hardware.models import HardwareDevice
    return HardwareDevice


# kind -> (model getter, detail url name, role flag, label getter, extra filter)
DEVICE_KINDS = {
    'asset': (_asset_model, 'assets:asset_detail', 'assets_view',
              lambda o: o.name, None),
    'rmm_device': (_rmm_model, 'integrations:rmm_device_detail', 'assets_view',
                   lambda o: o.device_name,
                   lambda: Q(ownership_status='resolved')),
    'hardware': (_hardware_model, 'hardware:device_detail', 'assets_view',
                 lambda o: str(o), None),
}
DEVICE_VIEWS = {spec[1]: kind for kind, spec in DEVICE_KINDS.items()}
# Opening an asset's Device Workspace counts as opening the asset.
DEVICE_VIEWS['assets:device_workspace'] = 'asset'


def _device_qs(kind):
    model, _url, _perm, _label, extra = DEVICE_KINDS[kind]
    qs = model()._default_manager.all()
    if extra is not None:
        qs = qs.filter(extra())
    return qs


def device_open_url(kind, pk, next_url='', workspace=False):
    """`workspace`: open the asset's Device Workspace (MSP staff; an RMM
    device opens its linked asset's workspace) instead of the detail page."""
    url = reverse('core:open_device', args=[kind, pk])
    q = {}
    if workspace and kind in ('asset', 'rmm_device'):
        q['to'] = 'workspace'
    if next_url:
        q['next'] = next_url
    if q:
        url += '?' + urlencode(q)
    return url


def workspace_path(kind, obj):
    """The Device Workspace for `obj` (an asset, or an RMM device linked to
    an asset of the same customer), or ''."""
    if kind == 'asset':
        return reverse('assets:device_workspace', args=[obj.pk])
    if kind == 'rmm_device' and obj.linked_asset_id:
        asset = obj.linked_asset
        if asset is not None and asset.organization_id == obj.organization_id:
            return reverse('assets:device_workspace', args=[asset.pk]) + '?' + urlencode({'device': obj.pk})
    return ''


def _visible_device_ids(request, kind, ids):
    """The subset of `ids` this user may open right now (customer + role)."""
    from accounts.permission_utils import orgs_with_perm
    from core.tenancy import accessible_org_ids
    _model, _url, perm, _label, _extra = DEVICE_KINDS[kind]
    allowed = _intersect(accessible_org_ids(request), orgs_with_perm(request.user, perm))
    qs = _narrow(_device_qs(kind).filter(pk__in=ids), allowed)
    return qs


def record_recent_device(user, kind, pk, organization_id):
    from core.models import RecentDevice
    if not user.is_authenticated or kind not in DEVICE_KINDS:
        return
    RecentDevice.objects.update_or_create(
        user=user, kind=kind, object_id=pk,
        defaults={'opened_at': timezone.now(), 'organization_id': organization_id},
    )
    stale = list(RecentDevice.objects.filter(user=user).order_by('-opened_at')
                 .values_list('id', flat=True)[RECENT_DEVICE_KEEP:])
    if stale:
        RecentDevice.objects.filter(id__in=stale).delete()


def recent_devices(request, limit=RECENT_DEVICE_LIMIT, next_url=''):
    """The user's recently opened devices they can still open, newest first."""
    from core.models import RecentDevice
    rows = list(RecentDevice.objects.filter(user=request.user).order_by('-opened_at')[:RECENT_DEVICE_KEEP])
    staff = _is_staff(request.user)
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r.kind, []).append(r.object_id)
    objects = {}
    for kind, ids in by_kind.items():
        if kind not in DEVICE_KINDS:
            continue
        for obj in _visible_device_ids(request, kind, ids).select_related('organization'):
            objects[(kind, obj.pk)] = obj
    out = []
    for r in rows:
        obj = objects.get((r.kind, r.object_id))
        if obj is None:
            continue
        label = DEVICE_KINDS[r.kind][3](obj)
        out.append({
            'kind': r.kind,
            'kind_label': dict(RecentDevice.KIND_CHOICES).get(r.kind, r.kind),
            'title': label,
            'customer': getattr(obj.organization, 'name', ''),
            'opened_at': r.opened_at,
            'url': device_open_url(r.kind, obj.pk, next_url),
            'workspace_url': (device_open_url(r.kind, obj.pk, next_url, workspace=True)
                              if staff and workspace_path(r.kind, obj) else ''),
        })
        if len(out) >= limit:
            break
    return out


def _safe_next(request, raw):
    raw = (raw or '').strip()
    if raw and url_has_allowed_host_and_scheme(raw, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()) \
            and raw.startswith('/') and not raw.startswith('//'):
        return raw
    return ''


def _referer_path(request):
    from urllib.parse import urlparse
    ref = request.META.get('HTTP_REFERER', '')
    if not ref:
        return ''
    if not url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        return ''
    parsed = urlparse(ref)
    path = parsed.path + (f'?{parsed.query}' if parsed.query else '')
    return path if path.startswith('/') and not path.startswith('//') else ''


@login_required
def open_device(request, kind, pk):
    """Open a device page in its customer's context.

    Cross-customer lists (My Work, search, recent devices) link here instead
    of to the detail page, which reads the session's current customer. When
    the device belongs to another customer the session switches to it — only
    if the user may switch there (client switcher rule) and their role there
    grants the device section (SectionPermissionMiddleware, re-checked for
    that customer) — and a "Back" trail remembers where they came from, so
    returning puts them back in the customer they were working in.
    Anything the user may not open is a 404, the same answer as an unknown id.
    """
    if kind not in DEVICE_KINDS:
        raise Http404
    _model, url_name, _perm, label_of, _extra = DEVICE_KINDS[kind]
    obj = _visible_device_ids(request, kind, [pk]).select_related('organization').first()
    if obj is None or obj.organization_id is None:
        raise Http404
    target = obj.organization
    detail = reverse(url_name, args=[obj.pk])
    if request.GET.get('to') == 'workspace' and _is_staff(request.user):
        detail = workspace_path(kind, obj) or detail
    current = getattr(request, 'current_organization', None)

    from core.utils import descendant_org_ids
    if current is not None and target.pk in descendant_org_ids(current):
        return redirect(detail)

    from core.client_switcher import authorized_organizations
    from core.org_handoff import _check_section_perm, switch_session_org
    if not authorized_organizations(request).filter(pk=target.pk).exists():
        raise Http404
    original_path = request.path
    request.path = detail.split('?', 1)[0]  # the section gate is keyed by path
    try:
        _check_section_perm(request, target)
    finally:
        request.path = original_path

    back = _safe_next(request, request.GET.get('next')) or _referer_path(request)
    request.session[TRAIL_KEY] = {
        'from_org_id': current.pk if current is not None else None,
        'from_org_name': current.name if current is not None else '',
        'to_org_id': target.pk,
        'path': back,
        'record': label_of(obj)[:120],
        'at': timezone.now().isoformat(),
    }
    switch_session_org(request, target)
    return redirect(detail)


def context_trail(request):
    """The "you switched customer to open X" trail, while it still applies."""
    trail = request.session.get(TRAIL_KEY)
    if not trail:
        return None
    current = getattr(request, 'current_organization', None)
    try:
        at = datetime.fromisoformat(trail.get('at', ''))
    except (TypeError, ValueError):
        at = None
    stale = at is None or timezone.now() - at > CONTEXT_TRAIL_TTL
    if stale or current is None or current.pk != trail.get('to_org_id'):
        # The user moved on (switched customer themselves, or it is old).
        request.session.pop(TRAIL_KEY, None)
        return None
    return trail


@login_required
@require_POST
def context_return(request):
    """Go back to where an open-in-context jump started, in that customer."""
    trail = request.session.pop(TRAIL_KEY, None) or {}
    from core.client_switcher import authorized_organizations, has_all_client_access
    from core.org_handoff import switch_session_org
    org_id = trail.get('from_org_id')
    if org_id:
        org = authorized_organizations(request).filter(pk=org_id).first()
        if org is not None:
            switch_session_org(request, org)
            messages.info(request, f'Back in {org.name}.')
    elif trail and has_all_client_access(request):
        request.session.pop('current_organization_id', None)
        request.session['global_view_mode'] = True
        request.session.modified = True
        messages.info(request, 'Back in Global View.')
    dest = _safe_next(request, trail.get('path')) or reverse('core:dashboard')
    return redirect(dest)


# ---------------------------------------------------------------------------
# Saved views
# ---------------------------------------------------------------------------

SAVED_VIEW_LISTS = {
    'tickets': {
        'view': 'psa:ticket_list', 'label': 'tickets',
        'params': ('client', 'status', 'priority', 'queue', 'assigned', 'q'),
        'presets': (
            ('My open tickets', 'assigned=me&queue=open'),
            ('Unassigned', 'assigned=unassigned&queue=open'),
            ('Waiting on us', 'queue=waiting_us'),
            ('Customer replied', 'queue=customer_replied'),
        ),
    },
    'rmm_devices': {
        'view': 'integrations:rmm_devices', 'label': 'devices',
        'params': ('q', 'status', 'type', 'link'),
        'presets': (
            ('Offline', 'status=offline'),
            ('Servers', 'type=server'),
            ('Not linked to an asset', 'link=unlinked'),
        ),
    },
    'assets': {
        'view': 'assets:asset_list', 'label': 'assets',
        'params': ('type', 'manufacturer', 'status', 'location', 'needs_reorder', 'q', 'search'),
        'presets': (),
    },
}
SAVED_VIEW_BY_VIEW = {spec['view']: key for key, spec in SAVED_VIEW_LISTS.items()}
# A list URL with this parameter skips the default view.
NO_DEFAULT_PARAM = 'view'
MAX_SAVED_VIEWS = 20


def clean_query(list_key, raw):
    """`raw` reduced to the list's own filter parameters, in a stable order."""
    spec = SAVED_VIEW_LISTS[list_key]
    allowed = spec['params']
    pairs = []
    for k, v in parse_qsl((raw or '').lstrip('?'), keep_blank_values=False):
        if k in allowed and v and len(v) <= 200:
            pairs.append((k, v))
    pairs.sort(key=lambda kv: (allowed.index(kv[0]), kv[1]))
    return urlencode(pairs)[:1000]


def saved_view_bar(request):
    """Context for the saved-views bar on a registered list, or None."""
    match = getattr(request, 'resolver_match', None)
    key = SAVED_VIEW_BY_VIEW.get(getattr(match, 'view_name', '') or '')
    if key is None or not request.user.is_authenticated:
        return None
    if key in ('tickets', 'rmm_devices') and not _is_staff(request.user):
        return None
    from core.models import SavedView
    spec = SAVED_VIEW_LISTS[key]
    current = clean_query(key, request.META.get('QUERY_STRING', ''))
    base = request.path
    views = []
    for v in SavedView.objects.filter(user=request.user, list_key=key):
        views.append({'id': v.pk, 'name': v.name, 'url': f'{base}?{v.query}' if v.query else f'{base}?{NO_DEFAULT_PARAM}=all',
                      'active': v.query == current, 'is_default': v.is_default})
    presets = [{'name': n, 'url': f'{base}?{q}', 'active': q == current} for n, q in spec['presets']
               if not any(v['name'] == n for v in views)]
    return {
        'list_key': key,
        'label': spec['label'],
        'views': views,
        'presets': presets,
        'current_query': current,
        'can_save': bool(current) and len(views) < MAX_SAVED_VIEWS,
        'all_url': f'{base}?{NO_DEFAULT_PARAM}=all',
        'next': request.get_full_path(),
    }


def _back_to_list(request, key, fallback_query=''):
    nxt = _safe_next(request, request.POST.get('next'))
    if nxt:
        return redirect(nxt)
    url = reverse(SAVED_VIEW_LISTS[key]['view'])
    return redirect(f'{url}?{fallback_query}' if fallback_query else url)


@login_required
@require_POST
def saved_view_save(request):
    from core.models import SavedView
    key = request.POST.get('list_key', '')
    if key not in SAVED_VIEW_LISTS:
        raise Http404
    name = (request.POST.get('name') or '').strip()[:60]
    query = clean_query(key, request.POST.get('query', ''))
    if not name:
        messages.error(request, 'Give the view a name to save it.')
        return _back_to_list(request, key, query)
    existing = SavedView.objects.filter(user=request.user, list_key=key)
    if existing.count() >= MAX_SAVED_VIEWS and not existing.filter(name=name).exists():
        messages.error(request, f'You already have {MAX_SAVED_VIEWS} saved views here. Delete one first.')
        return _back_to_list(request, key, query)
    view, _created = SavedView.objects.update_or_create(
        user=request.user, list_key=key, name=name, defaults={'query': query})
    if request.POST.get('is_default'):
        existing.exclude(pk=view.pk).update(is_default=False)
        view.is_default = True
        view.save(update_fields=['is_default', 'updated_at'])
    messages.success(request, f'Saved view "{name}".')
    return _back_to_list(request, key, query)


@login_required
@require_POST
def saved_view_default(request, pk):
    from core.models import SavedView
    view = SavedView.objects.filter(user=request.user, pk=pk).first()
    if view is None:
        raise Http404
    turn_on = not view.is_default
    SavedView.objects.filter(user=request.user, list_key=view.list_key).update(is_default=False)
    if turn_on:
        SavedView.objects.filter(pk=view.pk).update(is_default=True)
        messages.success(request, f'"{view.name}" now opens by default.')
    else:
        messages.info(request, f'"{view.name}" no longer opens by default.')
    return _back_to_list(request, view.list_key, view.query)


@login_required
@require_POST
def saved_view_delete(request, pk):
    from core.models import SavedView
    view = SavedView.objects.filter(user=request.user, pk=pk).first()
    if view is None:
        raise Http404
    key, name = view.list_key, view.name
    view.delete()
    messages.success(request, f'Deleted view "{name}".')
    return _back_to_list(request, key)


# ---------------------------------------------------------------------------
# Middleware: default saved view + recent devices
# ---------------------------------------------------------------------------

class WorkspaceMiddleware:
    """Two small jobs that need the resolved view:

    * a registered list opened with no query string redirects to the user's
      default saved view (``?view=all`` opts out);
    * a device page that answered 200 to a GET is recorded as recently
      opened. Only after the view itself allowed it, so the list can never
      hold something the user could not open.
    Runs after authentication and CurrentOrganizationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:
            logger.exception('recording a recent device failed')
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'GET' or request.META.get('QUERY_STRING'):
            return None
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        match = getattr(request, 'resolver_match', None)
        key = SAVED_VIEW_BY_VIEW.get(getattr(match, 'view_name', '') or '')
        if key is None:
            return None
        from core.models import SavedView
        view = SavedView.objects.filter(user=user, list_key=key, is_default=True).first()
        if view is None or not view.query:
            return None
        return redirect(f'{request.path}?{clean_query(key, view.query)}')

    @staticmethod
    def _record(request, response):
        if request.method != 'GET' or response.status_code != 200:
            return
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return
        match = getattr(request, 'resolver_match', None)
        kind = DEVICE_VIEWS.get(getattr(match, 'view_name', '') or '')
        if kind is None:
            return
        pk = match.kwargs.get('pk')
        if pk is None:
            return
        org_id = _device_qs(kind).filter(pk=pk).values_list('organization_id', flat=True).first()
        if org_id is None:
            return
        record_recent_device(user, kind, int(pk), org_id)


# ---------------------------------------------------------------------------
# My Work panels
# ---------------------------------------------------------------------------

def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _sla_panel(request, base_tickets, customer_ids):
    """Open tickets breached or due within SLA_SOON: mine, plus unassigned
    ones at my customers. Paused (waiting) tickets are excluded."""
    from psa.my_work import annotate_activity, open_q, order_by_sla
    now = timezone.now()
    mine_or_unassigned = Q(assigned_to=request.user)
    if customer_ids is None:
        mine_or_unassigned |= Q(assigned_to__isnull=True)
    elif customer_ids:
        mine_or_unassigned |= Q(assigned_to__isnull=True, organization_id__in=customer_ids)
    qs = annotate_activity(base_tickets.filter(open_q()).filter(mine_or_unassigned)
                           .filter(status__pauses_sla=False))
    qs = order_by_sla(qs.filter(sla_due_at__isnull=False, sla_due_at__lte=now + SLA_SOON))
    rows = list(qs[:PANEL_LIMIT])
    return {
        'count': qs.count(),
        'items': [{'ticket': t, 'breached': t.sla_due_at <= now,
                   'url': _url('psa:ticket_detail', t.ticket_number)} for t in rows],
    }


def _alert_panel(request, customer_ids, next_url):
    from accounts.permission_utils import orgs_with_perm
    items, count = [], 0
    try:
        from integrations.models import RMMAlert, RMMDevice
        allowed = _intersect(customer_ids, orgs_with_perm(request.user, 'assets_view'))
        rmm = _narrow(RMMAlert.objects.filter(
            status='active', device__ownership_status=RMMDevice.OWNERSHIP_RESOLVED),
            allowed, 'device__organization').select_related('device', 'device__organization')
        count += rmm.count()
        for a in rmm.order_by('-triggered_at')[:PANEL_LIMIT]:
            items.append({'title': a.alert_type or a.message[:80], 'severity': a.severity,
                          'context': f'{a.device.device_name} · {a.device.organization.name}',
                          'when': a.triggered_at, 'source': 'RMM',
                          'url': device_open_url('rmm_device', a.device_id, next_url),
                          'action': 'Open device'})
    except Exception:
        logger.debug('My Work: RMM alerts unavailable', exc_info=True)
    try:
        from security_alerts.models import SecurityAlert
        sec = SecurityAlert.objects.filter(status='new')
        reach = orgs_with_perm(request.user, 'security_alerts_view')
        sec = _narrow(sec, reach)
        if customer_ids is not None:
            sec = sec.filter(Q(client_org_id__in=customer_ids)
                             | Q(client_org__isnull=True, organization_id__in=customer_ids))
        sec = sec.select_related('client_org', 'organization')
        count += sec.count()
        for a in sec.order_by('-seen_at')[:PANEL_LIMIT]:
            org = a.client_org or a.organization
            items.append({'title': a.title, 'severity': a.severity,
                          'context': getattr(org, 'name', ''), 'when': a.seen_at, 'source': 'Security',
                          'url': _url('security_alerts:alert_detail', a.pk), 'action': 'Review'})
    except Exception:
        logger.debug('My Work: security alerts unavailable', exc_info=True)
    items.sort(key=lambda i: i['when'] or timezone.now(), reverse=True)
    return {'count': count, 'items': items[:PANEL_LIMIT]}


def _device_health_panel(request, customer_ids, next_url):
    """Offline devices, and online ones with an active error/critical alert."""
    from accounts.permission_utils import orgs_with_perm
    from integrations.models import RMMDevice
    allowed = _intersect(customer_ids, orgs_with_perm(request.user, 'assets_view'))
    qs = _narrow(RMMDevice.objects.filter(ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
                                          organization__isnull=False), allowed)
    unhealthy = qs.filter(Q(is_online=False)
                          | Q(alerts__status='active', alerts__severity__in=('error', 'critical'))).distinct()
    rows = list(unhealthy.select_related('organization')
                .order_by('is_online', '-last_seen')[:PANEL_LIMIT])
    return {
        'count': unhealthy.count(),
        'items': [{'title': d.device_name, 'context': d.organization.name,
                   'state': 'Online · alerting' if d.is_online else 'Offline',
                   'when': d.last_seen,
                   'url': device_open_url('rmm_device', d.pk, next_url)} for d in rows],
        'list_url': _url('integrations:rmm_devices') + '?status=offline',
    }


def _maintenance_panel(request, customer_ids):
    from accounts.permission_utils import orgs_with_perm
    from statuspage.models import MaintenanceWindow
    now = timezone.now()
    qs = MaintenanceWindow.objects.filter(is_cancelled=False, ends_at__gte=now,
                                          starts_at__lte=now + MAINTENANCE_WINDOW)
    reach = _intersect(customer_ids, orgs_with_perm(request.user, 'monitoring_view'))
    if reach is not None:
        qs = qs.filter(Q(page__organization_id__in=reach) | Q(page__organization__isnull=True))
    rows = list(qs.select_related('page', 'page__organization').order_by('starts_at')[:PANEL_LIMIT])
    return {
        'count': qs.count(),
        'items': [{'title': w.title,
                   'context': getattr(w.page.organization, 'name', '') or w.page.title,
                   'starts_at': w.starts_at, 'ends_at': w.ends_at,
                   'ongoing': w.starts_at <= now,
                   'url': _url('statuspage:detail', w.page_id)} for w in rows],
    }


def _review_panel(request, customer_ids):
    """Remote jobs of mine that ended badly or have results to read, and
    devices whose customer needs a technician's decision."""
    items, count = [], 0
    try:
        from psa_ai.models import RMMRequest
        since = timezone.now() - REVIEW_LOOKBACK
        jobs = RMMRequest.objects.filter(actor=request.user, updated_at__gte=since).filter(
            Q(status__in=('failed', 'rejected', 'unavailable', 'expired'))
            | Q(kind=RMMRequest.KIND_DIAGNOSTIC, status__in=('completed', 'succeeded'))
        ).select_related('ticket')
        jobs = _narrow(jobs, customer_ids)
        count += jobs.count()
        for j in jobs.order_by('-updated_at')[:PANEL_LIMIT]:
            ok = j.status in ('completed', 'succeeded')
            items.append({'title': j.diagnostic_label or j.fix_title or j.get_kind_display(),
                          'context': f'{j.device_name or j.device_external_id} · {j.ticket.ticket_number}',
                          'state': 'Results ready' if ok else j.get_status_display(),
                          'bad': not ok,
                          'url': _url('psa:ticket_detail', j.ticket.ticket_number),
                          'action': 'Read results' if ok else 'Review'})
    except Exception:
        logger.debug('My Work: remote jobs unavailable', exc_info=True)
    extra = _from_source('jobs', request, customer_ids)
    if extra:
        count += extra.get('count', 0)
        items.extend(extra.get('items', []))
    try:
        from integrations.models import RMMDevice
        current = getattr(request, 'current_organization', None)
        # rmm_review opens connections of the current customer only.
        if current is not None and (request.user.is_superuser or getattr(request, 'is_staff_user', False)):
            from core.utils import descendant_org_ids
            pending = (RMMDevice.objects.exclude(ownership_status=RMMDevice.OWNERSHIP_RESOLVED)
                       .filter(connection__organization_id__in=descendant_org_ids(current))
                       .values('connection_id', 'connection__name').order_by())
            from django.db.models import Count
            for row in pending.annotate(n=Count('id'))[:PANEL_LIMIT]:
                count += row['n']
                items.append({'title': f"{row['n']} device{'s' if row['n'] != 1 else ''} need a customer",
                              'context': row['connection__name'], 'state': 'Ownership review',
                              'bad': False, 'url': _url('integrations:rmm_review', row['connection_id']),
                              'action': 'Decide'})
    except Exception:
        logger.debug('My Work: device review unavailable', exc_info=True)
    return {'count': count, 'items': items[:PANEL_LIMIT]}


def _ai_panel(request):
    """OPTIONAL AI: suggestions waiting for review, only with psa_ai_enabled."""
    from core.models import SystemSetting
    if not getattr(SystemSetting.get_settings(), 'psa_ai_enabled', False):
        return None
    try:
        from psa_ai.models import AISuggestion
        from psa_ai.permissions import can_view_suggestion
    except Exception:
        return None
    qs = (AISuggestion.objects.filter(review_state='pending_review')
          .select_related('organization', 'native_ticket').order_by('-created_at'))
    visible = [s for s in qs[:50] if can_view_suggestion(request.user, s, request=request)]
    items = []
    for s in visible[:PANEL_LIMIT]:
        t = s.native_ticket
        items.append({'title': f'{s.get_kind_display()} suggestion',
                      'context': f'{t.ticket_number} · {s.organization.name}' if t else s.organization.name,
                      'url': _url('psa:ticket_detail', t.ticket_number) if t else _url('psa_ai:inbox'),
                      'action': 'Review'})
    return {'count': len(visible), 'items': items, 'url': _url('psa_ai:inbox') + '?state=pending_review',
            'capped': len(visible) >= 50}


def my_work_panels(request, base_tickets, scope_all=False):
    """Everything My Work adds on top of its ticket queues, for MSP staff.

    Returns {} for customer users. Each panel is None when its module is not
    there at all (no RMM connection, AI off, no remote-session source); the
    'setup' list then tells the technician what would fill it."""
    if not _is_staff(request.user):
        return {}
    customer_ids = work_customer_ids(request, scope_all=scope_all)
    next_url = reverse('psa:my_work')
    panels = {'customer_count': None if customer_ids is None else len(customer_ids)}
    setup = []

    try:
        panels['sla'] = _sla_panel(request, base_tickets, customer_ids)
    except Exception:
        logger.exception('My Work: SLA panel failed')
        panels['sla'] = None

    has_rmm = False
    try:
        from integrations.models import RMMConnection
        has_rmm = RMMConnection.objects.exists()
    except Exception:
        pass
    if has_rmm:
        panels['devices'] = _device_health_panel(request, customer_ids, next_url)
    else:
        panels['devices'] = None
        setup.append({'title': 'Device health and RMM alerts',
                      'text': 'Connect an RMM to see offline and alerting devices for your customers here.',
                      'url': _url('integrations:integration_list') if request.user.is_superuser else '',
                      'action': 'Connect an RMM'})
    panels['alerts'] = _alert_panel(request, customer_ids, next_url)
    try:
        panels['maintenance'] = _maintenance_panel(request, customer_ids)
    except Exception:
        logger.debug('My Work: maintenance unavailable', exc_info=True)
        panels['maintenance'] = None
    panels['recent_devices'] = recent_devices(request, next_url=next_url)
    panels['remote_sessions'] = _from_source('remote_sessions', request, customer_ids)
    if panels['remote_sessions'] is None:
        setup.append({'title': 'Active remote sessions',
                      'text': 'Remote sessions appear here once remote access is connected for your customers.',
                      'url': '', 'action': ''})
    panels['review'] = _review_panel(request, customer_ids)
    panels['ai'] = _ai_panel(request)
    panels['setup'] = setup
    return panels


# ---------------------------------------------------------------------------
# JSON for the global search box: pages + recent devices
# ---------------------------------------------------------------------------

@login_required
def recent_devices_json(request):
    return JsonResponse({'devices': [
        {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in d.items()}
        for d in recent_devices(request, limit=8, next_url=_safe_next(request, request.GET.get('next')))
    ]})
