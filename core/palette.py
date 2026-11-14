"""Command palette, Favorites and Recent: what the top bar's quick menus and
the Ctrl+K palette may show this user.

Nothing here grants access; everything is re-derived on every request from
the same sources the pages use:

* navigation destinations come from ``core.navigation`` — its
  ``destinations_for(ctx)`` when present, otherwise the sidebar itself
  (``primary_nav``: the PRIMARY / ADMIN groups, their sections'
  ``resolve_tabs`` and the ``_PermProbe`` URL-prefix gate) flattened;
* records are read through ``core.search_views.SearchScope`` (the search
  page's scoping: customer reach, role flag, feature flag), plus the project
  and report-template list pages' own scoping;
* every link must also pass ``_PermProbe.allows`` (SectionPermissionMiddleware
  and the view's permission decorators), so a row the server would answer
  with 403 is never listed.

Stored favorites and recent pages are paths only (``PageFavorite``,
``RecentPage``). Each read resolves the path again: a deleted record, a
revoked membership or role flag, or a module switched off drops the entry
without touching the table. Labels are never stored.

Never returned: password-vault entries in search (the palette excludes the
vault; the vault's own search stays the way to find credentials), secret
fields of any kind, query strings.
"""
from __future__ import annotations

import logging

from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.translation import gettext as _

logger = logging.getLogger('core')

PER_GROUP = 5
TOTAL_LIMIT = 30
MIN_QUERY = 2
MAX_QUERY = 100
RECENT_KEEP = 30
RECENT_SHOW = 10
FAVORITES_KEEP = 50
FAVORITES_SHOW = 20
MAX_PATH = 255

# Pages that are never worth a Recent entry.
_NOT_RECENT = {'core:dashboard', 'core:search', 'core:favorite_list'}


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

def nav_context(request):
    """The template context the sidebar is built from (the configured
    context processors), for JSON views that render no template."""
    from django.template import engines
    ctx = {'request': request, 'user': request.user}
    try:
        processors = engines['django'].engine.template_context_processors
    except Exception:  # pragma: no cover - misconfigured engine
        processors = ()
    for proc in processors:
        try:
            ctx.update(proc(request) or {})
        except Exception:
            logger.debug('context processor %r failed for the palette', proc, exc_info=True)
    return ctx


class Palette:
    """One request's view of the palette: context, probe, scope, destinations."""

    def __init__(self, request):
        from core import navigation
        from core.search_views import SearchScope
        self.request = request
        self.user = request.user
        self.ctx = nav_context(request)
        self.probe = navigation._PermProbe(self.ctx)
        self.scope = SearchScope(request)
        self._dest = None
        self._dest_by_path = None

    # -- gates -------------------------------------------------------------

    def flag(self, name, default=False):
        value = self.ctx.get(name, default)
        return bool(default if value is None else value)

    def allows(self, href):
        if not href:
            return False
        try:
            return bool(self.probe.allows(href.split('?', 1)[0]))
        except Exception:
            logger.debug('palette probe failed for %s', href, exc_info=True)
            return False

    # -- navigation destinations ---------------------------------------------

    @property
    def destinations(self):
        if self._dest is None:
            self._dest = destinations(self.ctx)
        return self._dest

    @property
    def dest_by_path(self):
        if self._dest_by_path is None:
            self._dest_by_path = {d['href'].split('?', 1)[0]: d for d in self.destinations}
        return self._dest_by_path


def _clean_dest(d):
    href = str(d.get('href') or '')
    if not href.startswith('/') or href.startswith('//'):
        return None
    icon = str(d.get('icon') or 'fa-circle')
    if ' ' not in icon:
        icon = f'fas {icon}'
    return {
        'label': str(d.get('label') or ''),
        'href': href,
        'icon': icon,
        'group': str(d.get('group') or ''),
        'section': str(d.get('section') or ''),
        'keywords': str(d.get('keywords') or ''),
    }


def destinations(ctx):
    """Every navigation destination this user may open, flattened, without
    duplicates: ``[{label, href, icon, group, section, keywords}]``."""
    from core import navigation
    raw = None
    fn = getattr(navigation, 'destinations_for', None)
    if callable(fn):
        try:
            raw = list(fn(ctx))
        except Exception:
            logger.exception('navigation.destinations_for failed; using the sidebar walk')
            raw = None
    if raw is None:
        raw = _walk_sidebar(ctx)
    out, seen = [], set()
    for d in raw:
        item = _clean_dest(d)
        if item is None or not item['label'] or item['href'] in seen:
            continue
        seen.add(item['href'])
        out.append(item)
    return out


def _walk_sidebar(ctx):
    """The sidebar flattened: what `primary_nav` draws (group entries, their
    section tabs, the Administration categories' pages, and the settings
    workspace for customer-side administrators), with its gates."""
    from core import navigation
    try:
        pnav = navigation.primary_nav(ctx)
    except Exception:
        logger.exception('primary_nav failed for the palette')
        return []
    out = []
    groups = list(pnav.get('groups') or [])
    if pnav.get('settings'):
        groups.append(pnav['settings'])
    for g in groups:
        for e in g.get('entries') or ():
            out.append({'label': e.get('label'), 'href': e.get('href'), 'icon': e.get('icon'),
                        'group': g.get('label'), 'section': e.get('label'),
                        'keywords': e.get('keywords', '')})
            for t in (e.get('tabs') or e.get('children') or ()):
                if t.get('modal') or t.get('download'):
                    continue
                out.append({'label': t.get('label'), 'href': t.get('href'), 'icon': t.get('icon'),
                            'group': g.get('label'), 'section': e.get('label'),
                            'keywords': t.get('keywords', '')})
    ws = pnav.get('workspace') or {}
    for cat in ws.get('categories') or ():
        for t in cat.get('tabs') or ():
            out.append({'label': t.get('label'), 'href': t.get('href'), 'icon': t.get('icon'),
                        'group': _('Settings'), 'section': cat.get('label'),
                        'keywords': t.get('keywords', '')})
    return out


# ---------------------------------------------------------------------------
# Quick commands (navigation only — every one opens a page, none acts)
# ---------------------------------------------------------------------------

def _rev(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def commands(pal):
    """The quick commands this user may run: each opens its page, and only
    when that page would let the user in and its module is on."""
    from core import navigation, quick_actions
    dests = pal.dest_by_path
    out = []

    def add(key, label, icon, href, keywords=''):
        if href and pal.allows(href):
            out.append({'key': key, 'label': label, 'icon': f'fas {icon}', 'href': href,
                        'keywords': keywords})

    # Create Ticket: the dashboard quick action's own gate (PSA on,
    # require_write, tickets_create somewhere).
    action = quick_actions.get_action('new_ticket')
    try:
        ticket_ok = bool(action and action['enabled'](pal.ctx)
                         and quick_actions.action_allowed(action, pal.request))
    except Exception:
        ticket_ok = False
    if ticket_ok:
        add('create_ticket', _('Create Ticket'), 'fa-plus', _rev('psa:ticket_create'), 'new ticket')

    # Create Client: accounts.views.organization_create refuses customer
    # users; offered with the client list (same people).
    from accounts.delegation import is_customer_actor
    org_list = _rev('accounts:organization_list')
    if org_list in dests and not is_customer_actor(pal.user):
        add('create_client', _('Create Client'), 'fa-building',
            _rev('accounts:organization_create'), 'new client organization customer')

    for key, label, icon, name, kw in (
            ('my_queue', _('Open My Queue'), 'fa-user-check', 'psa:my_work', 'my work assigned'),
            ('log_time', _('Log Time'), 'fa-clock', 'psa:my_timesheet', 'timesheet time entry'),
            ('dispatch', _('Open Dispatch Board'), 'fa-table-list', 'psa:dispatch_board', 'dispatch')):
        href = _rev(name)
        if href in dests:
            add(key, label, icon, href, kw)

    # View Alerts: the first alert page this user has (RMM, security, monitoring).
    for name in ('integrations:rmm_alerts', 'security_alerts:alert_list',
                 'monitoring:website_monitor_list'):
        href = _rev(name)
        if href in dests:
            add('alerts', _('View Alerts'), 'fa-bell', href, 'alerts monitoring')
            break

    # Open Settings: the first Administration / settings page in this user's navigation.
    admin_label = str(getattr(getattr(navigation, 'ADMIN', None), 'label', 'Administration'))
    settings_href = next((d['href'] for d in pal.destinations
                          if d['group'] in (admin_label, str(_('Settings')))), '')
    if settings_href:
        add('settings', _('Open Settings'), 'fa-gear', settings_href, 'administration preferences')
    return out


# ---------------------------------------------------------------------------
# Records: scoping beyond SearchScope (list pages' own rules)
# ---------------------------------------------------------------------------

def projects_qs(pal):
    """psa.views.project_list: the selected customer's projects; all of them
    for superusers and MSP staff in global view; nothing otherwise."""
    if not pal.flag('psa_enabled') or not pal.allows(_rev('psa:project_list')):
        return None
    from psa.models import Project
    org = pal.scope.org
    qs = Project.objects.select_related('organization')
    if org is not None:
        return qs.filter(organization=org)
    if pal.user.is_superuser or getattr(pal.request, 'is_staff_user', False):
        return qs
    return None


def report_templates_qs(pal):
    """reports.views.template_list: the user's organizations' templates and
    the global ones (behind /reports/ staff-only and reports_view_dashboards)."""
    if pal.ctx.get('reports_enabled', True) is False or not pal.allows(_rev('reports:template_list')):
        return None
    from django.db.models import Q
    from reports.models import ReportTemplate
    from reports.views import get_user_organizations
    return ReportTemplate.objects.filter(
        Q(organization__in=get_user_organizations(pal.user)) | Q(is_global=True))


def _org_name(obj):
    org = getattr(obj, 'organization', None)
    return getattr(org, 'name', '') or ''


def _item(label, href, icon, kind, detail=''):
    return {'label': str(label), 'href': href, 'icon': icon, 'type': str(kind), 'detail': str(detail or '')}


def _ticket_item(t):
    return _item(f'{t.ticket_number} · {t.subject}', _rev('psa:ticket_detail', t.ticket_number),
                 'fas fa-ticket', _('Ticket'), _org_name(t))


def _asset_item(a):
    bits = [b for b in (_org_name(a), a.asset_tag, a.serial_number) if b]
    return _item(a.name, _rev('assets:asset_detail', a.pk), 'fas fa-server', _('Asset'), ' · '.join(bits))


def _rmm_item(d, next_url=''):
    from core.workspace import device_open_url
    bits = [b for b in (_org_name(d), d.hostname) if b]
    return _item(d.device_name or d.hostname, device_open_url('rmm_device', d.pk, next_url),
                 'fas fa-desktop', _('RMM device'), ' · '.join(bits))


def _client_item(o):
    return _item(o.name, _rev('core:customer_ops', o.pk), 'fas fa-building', _('Client'))


def _doc_item(d):
    return _item(d.title, _rev('docs:document_detail', d.slug), 'fas fa-file-alt', _('Document'),
                 _org_name(d))


def _kb_item(d):
    return _item(d.title, _rev('docs:global_kb_detail', d.slug), 'fas fa-book', _('Knowledge base'))


def _project_item(p):
    return _item(p.name, _rev('psa:project_detail', p.pk), 'fas fa-diagram-project', _('Project'),
                 _org_name(p))


def _report_item(r):
    return _item(r.name, _rev('reports:template_detail', r.pk), 'fas fa-chart-bar', _('Report'))


# ---------------------------------------------------------------------------
# Search (server side of the palette)
# ---------------------------------------------------------------------------

def search(pal, query):
    """Grouped results for `query`: ``[{key, label, icon, items}]``. Every
    group goes through its list page's scoping and its section gate; at most
    PER_GROUP rows each and TOTAL_LIMIT overall. Passwords are not searched."""
    query = (query or '').strip()[:MAX_QUERY]
    if len(query) < MIN_QUERY:
        return []
    scope = pal.scope
    groups = []
    budget = [TOTAL_LIMIT]

    def run(key, label, icon, build):
        if budget[0] <= 0:
            return
        try:
            items = build()
        except Exception:
            logger.debug('palette group %s skipped', key, exc_info=True)
            return
        items = [i for i in items if i['href'] and pal.allows(i['href'])][:min(PER_GROUP, budget[0])]
        if items:
            budget[0] -= len(items)
            groups.append({'key': key, 'label': label, 'icon': icon, 'items': items})

    def clients():
        if not pal.allows(_rev('core:customer_ops_current')):
            return []
        qs = scope.clients(query)
        return [] if qs is None else [_client_item(o) for o in qs[:PER_GROUP]]

    def tickets():
        if not pal.flag('psa_enabled') or not pal.allows(_rev('psa:ticket_list')):
            return []
        qs = scope.tickets(query)
        return [] if qs is None else [_ticket_item(t) for t in qs[:PER_GROUP]]

    def devices():
        out = []
        if pal.allows(_rev('assets:asset_list')):
            qs = scope.assets(query, fields=('name', 'asset_tag', 'serial_number', 'hostname'))
            out += [_asset_item(a) for a in qs.order_by('name')[:PER_GROUP]]
        if pal.allows(_rev('integrations:rmm_devices')):
            qs = scope.rmm_devices(query)
            if qs is not None:
                out += [_rmm_item(d) for d in qs.order_by('device_name')[:PER_GROUP]]
        return out

    def projects():
        qs = projects_qs(pal)
        if qs is None:
            return []
        return [_project_item(p) for p in qs.filter(name__icontains=query).order_by('-created_at')[:PER_GROUP]]

    def documents():
        if not pal.allows(_rev('docs:document_list')):
            return []
        qs = scope.documents(query, fields=('title',))
        return [_doc_item(d) for d in qs.order_by('title')[:PER_GROUP]]

    def kb():
        if not pal.flag('global_kb_enabled', True) or not pal.allows(_rev('docs:global_kb_list')):
            return []
        qs = scope.global_kb(query, fields=('title',))
        return [] if qs is None else [_kb_item(d) for d in qs.order_by('title')[:PER_GROUP]]

    def reports():
        qs = report_templates_qs(pal)
        if qs is None:
            return []
        return [_report_item(r) for r in qs.filter(name__icontains=query).order_by('name')[:PER_GROUP]]

    run('clients', _('Clients'), 'fas fa-building', clients)
    run('tickets', _('Tickets'), 'fas fa-ticket', tickets)
    run('devices', _('Devices & assets'), 'fas fa-server', devices)
    run('projects', _('Projects'), 'fas fa-diagram-project', projects)
    run('documents', _('Documents'), 'fas fa-file-alt', documents)
    run('kb', _('Knowledge base'), 'fas fa-book', kb)
    run('reports', _('Reports'), 'fas fa-chart-bar', reports)
    return groups


# ---------------------------------------------------------------------------
# Paths: what a stored favorite / recent page is now, for this user
# ---------------------------------------------------------------------------

def clean_path(raw):
    """A same-site path without query string or fragment, or ''."""
    path = str(raw or '').strip().split('#', 1)[0].split('?', 1)[0]
    if not path.startswith('/') or path.startswith('//') or '\\' in path or len(path) > MAX_PATH:
        return ''
    return path


def _match(path):
    try:
        return resolve(path)
    except Resolver404:
        return None
    except Exception:  # pragma: no cover - a broken URLconf must not 500 a menu
        return None


def _record_ticket(pal, kw):
    if not pal.flag('psa_enabled'):
        return None
    qs = pal.scope.tickets(None)
    t = qs.filter(ticket_number=kw.get('ticket_number')).first() if qs is not None else None
    return _ticket_item(t) if t else None


def _record_project(pal, kw):
    qs = projects_qs(pal)
    p = qs.filter(pk=kw.get('pk')).first() if qs is not None else None
    return _project_item(p) if p else None


def _record_document(pal, kw):
    d = pal.scope.documents(None).filter(slug=kw.get('slug')).first()
    return _doc_item(d) if d else None


def _record_kb(pal, kw):
    qs = pal.scope.global_kb(None)
    d = qs.filter(slug=kw.get('slug')).first() if qs is not None else None
    return _kb_item(d) if d else None


def _record_report(pal, kw):
    qs = report_templates_qs(pal)
    r = qs.filter(pk=kw.get('pk')).first() if qs is not None else None
    return _report_item(r) if r else None


def _record_device(kind):
    def read(pal, kw):
        from core.workspace import _visible_device_ids
        obj = _visible_device_ids(pal.request, kind, [kw.get('pk')]).select_related('organization').first()
        if obj is None:
            return None
        if kind == 'asset':
            return _asset_item(obj)
        if kind == 'rmm_device':
            return _rmm_item(obj)
        return _item(str(obj), _rev('hardware:device_detail', obj.pk), 'fas fa-hdd', _('Hardware device'),
                     _org_name(obj))
    return read


def _record_client(pal, kw):
    from core.client_switcher import authorized_organizations
    o = authorized_organizations(pal.request).filter(pk=kw.get('org_id')).first()
    return _client_item(o) if o else None


RECORD_VIEWS = {
    'psa:ticket_detail': _record_ticket,
    'psa:project_detail': _record_project,
    'docs:document_detail': _record_document,
    'docs:global_kb_detail': _record_kb,
    'reports:template_detail': _record_report,
    'assets:asset_detail': _record_device('asset'),
    'integrations:rmm_device_detail': _record_device('rmm_device'),
    'hardware:device_detail': _record_device('hardware'),
    'core:customer_ops': _record_client,
}

# Records that already have a content-type Favorite (core.favorites_views):
# view name -> (app_label, model, url kwarg).
CONTENT_FAVORITES = {
    'assets:asset_detail': ('assets', 'asset', 'pk'),
    'vault:password_detail': ('vault', 'password', 'pk'),
    'core:customer_ops': ('core', 'organization', 'org_id'),
}


def describe(pal, path):
    """What `path` is for this user right now — an item dict — or None when
    they may not open it (not a destination, record gone or out of reach,
    module off, section refused)."""
    path = clean_path(path)
    if not path:
        return None
    dest = pal.dest_by_path.get(path)
    if dest is not None:
        return _item(dest['label'], dest['href'], dest['icon'], dest['section'] or dest['group'] or _('Page'))
    match = _match(path)
    reader = RECORD_VIEWS.get(getattr(match, 'view_name', '') or '')
    if reader is None or not pal.allows(path):
        return None
    try:
        item = reader(pal, match.kwargs)
    except Exception:
        logger.debug('palette could not describe %s', path, exc_info=True)
        return None
    if item is None or not pal.allows(item['href']):
        return None
    return item


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------

def _content_favorite_item(pal, fav):
    from core.favorites_views import _may_see
    obj = fav.content_object
    if obj is None or not _may_see(pal.request, obj):
        return None
    model = obj._meta.model_name
    if model == 'password':
        item = _item(obj.title, _rev('vault:password_detail', obj.pk), 'fas fa-key', _('Password'),
                     _org_name(obj))
    elif model == 'asset':
        item = _asset_item(obj)
    elif model == 'organization':
        item = _client_item(obj)
    else:
        return None
    return item if pal.allows(item['href']) else None


def favorites(pal, limit=FAVORITES_SHOW):
    """The user's favorites they may still open, newest first: the existing
    content-type favorites (passwords by title only, assets, clients) and
    starred pages."""
    from core.models import Favorite, PageFavorite
    rows = []
    for fav in (Favorite.objects.filter(user=pal.user).select_related('content_type')
                .order_by('-created_at')[:FAVORITES_KEEP]):
        try:
            item = _content_favorite_item(pal, fav)
        except Exception:
            item = None
        if item:
            rows.append((fav.created_at, item))
    for fav in PageFavorite.objects.filter(user=pal.user).order_by('-created_at')[:FAVORITES_KEEP]:
        item = describe(pal, fav.path)
        if item:
            item['path'] = fav.path
            rows.append((fav.created_at, item))
    rows.sort(key=lambda r: r[0], reverse=True)
    out, seen = [], set()
    for _when, item in rows:
        if item['href'] in seen:
            continue
        seen.add(item['href'])
        out.append(item)
    return out[:limit]


def _content_target(path):
    """(ContentType, object id) when `path` is a record with a content-type
    favorite, else None."""
    match = _match(path)
    spec = CONTENT_FAVORITES.get(getattr(match, 'view_name', '') or '')
    if spec is None:
        return None
    from django.contrib.contenttypes.models import ContentType
    app_label, model, kwarg = spec
    try:
        ct = ContentType.objects.get(app_label=app_label, model=model)
    except ContentType.DoesNotExist:
        return None
    pk = match.kwargs.get(kwarg)
    return (ct, pk) if pk is not None else None


def current_state(pal, path):
    """Can the current page be starred, and is it?"""
    from core.models import Favorite, PageFavorite
    path = clean_path(path)
    state = {'path': path, 'favoritable': False, 'favorited': False, 'label': ''}
    if not path:
        return state
    target = _content_target(path)
    if target is not None:
        ct, pk = target
        model = ct.model_class()
        obj = model._default_manager.filter(pk=pk).first() if model else None
        from core.favorites_views import _may_see
        if obj is not None and _may_see(pal.request, obj):
            state['favoritable'] = True
            state['favorited'] = Favorite.objects.filter(user=pal.user, content_type=ct, object_id=pk).exists()
            state['label'] = str(getattr(obj, 'title', None) or getattr(obj, 'name', None) or obj)
        return state
    item = describe(pal, path)
    if item is not None:
        state['favoritable'] = True
        state['label'] = item['label']
        state['favorited'] = PageFavorite.objects.filter(user=pal.user, path=path).exists()
    return state


class FavoriteRefused(Exception):
    pass


def toggle_favorite(pal, path):
    """Star or unstar `path`. Removing your own favorite always works;
    adding needs the page to be one this user may open. Returns the new
    `current_state`."""
    from core.models import Favorite, PageFavorite
    path = clean_path(path)
    if not path:
        raise FavoriteRefused('bad path')
    target = _content_target(path)
    if target is not None:
        ct, pk = target
        existing = Favorite.objects.filter(user=pal.user, content_type=ct, object_id=pk).first()
        if existing:
            existing.delete()
        else:
            model = ct.model_class()
            obj = model._default_manager.filter(pk=pk).first() if model else None
            from core.favorites_views import _may_see
            if obj is None or not _may_see(pal.request, obj):
                raise FavoriteRefused('not visible')
            org = obj if ct.model == 'organization' else getattr(obj, 'organization', None)
            Favorite.objects.create(user=pal.user, organization=org, content_type=ct, object_id=pk)
        return current_state(pal, path)
    existing = PageFavorite.objects.filter(user=pal.user, path=path).first()
    if existing:
        existing.delete()
        return current_state(pal, path)
    if describe(pal, path) is None:
        raise FavoriteRefused('not visible')
    if PageFavorite.objects.filter(user=pal.user).count() >= FAVORITES_KEEP:
        raise FavoriteRefused('full')
    PageFavorite.objects.get_or_create(user=pal.user, path=path)
    return current_state(pal, path)


# ---------------------------------------------------------------------------
# Recent
# ---------------------------------------------------------------------------

def _page_view_names():
    """View names of navigation pages without arguments (sidebar entries and
    section tabs): visiting one is a Recent entry."""
    from core import navigation
    names = set()
    for section in getattr(navigation, 'SECTIONS', ()):
        for tab in getattr(section, 'tabs', ()):
            if getattr(tab, 'url_name', '') and not getattr(tab, 'args', ()) \
                    and not getattr(tab, 'modal', '') and not getattr(tab, 'download', False):
                names.add(tab.url_name)
    for group in getattr(navigation, 'ALL_GROUPS', ()):
        for entry in getattr(group, 'entries', ()):
            if getattr(entry, 'url_name', '') and not getattr(entry, 'args', ()):
                names.add(entry.url_name)
    return names - _NOT_RECENT


_PAGE_VIEWS = None


def recordable(view_name):
    global _PAGE_VIEWS
    if _PAGE_VIEWS is None:
        _PAGE_VIEWS = _page_view_names()
    # Devices are recorded by core.workspace (RecentDevice); clients by the
    # switcher (RecentClient).
    if view_name in ('assets:asset_detail', 'integrations:rmm_device_detail', 'hardware:device_detail'):
        return False
    return view_name in RECORD_VIEWS or view_name in _PAGE_VIEWS


def record_recent_page(user, path):
    from core.models import RecentPage
    path = clean_path(path)
    if not path or not user.is_authenticated:
        return
    RecentPage.objects.update_or_create(user=user, path=path, defaults={'visited_at': timezone.now()})
    stale = list(RecentPage.objects.filter(user=user).order_by('-visited_at')
                 .values_list('id', flat=True)[RECENT_KEEP:])
    if stale:
        RecentPage.objects.filter(id__in=stale).delete()


def recent(pal, limit=RECENT_SHOW):
    """Recently opened pages, records, devices and clients the user may
    still open, newest first."""
    from core.models import RecentClient, RecentPage
    rows = []
    for r in RecentPage.objects.filter(user=pal.user).order_by('-visited_at')[:RECENT_KEEP]:
        item = describe(pal, r.path)
        if item:
            rows.append((r.visited_at, item))
    try:
        from core.workspace import recent_devices
        for d in recent_devices(pal.request, limit=limit):
            icon = {'asset': 'fas fa-server', 'rmm_device': 'fas fa-desktop'}.get(d['kind'], 'fas fa-hdd')
            item = _item(d['title'], d['url'], icon, d['kind_label'], d['customer'])
            if pal.allows(d['url']):
                rows.append((d['opened_at'], item))
    except Exception:
        logger.debug('palette: recent devices unavailable', exc_info=True)
    if pal.scope.staff_user:
        from core.client_switcher import authorized_organizations
        for r in (RecentClient.objects.filter(user=pal.user, organization__is_active=True,
                                              organization__in=authorized_organizations(pal.request))
                  .select_related('organization').order_by('-switched_at')[:limit]):
            item = _client_item(r.organization)
            if pal.allows(item['href']):
                rows.append((r.switched_at, item))
    rows.sort(key=lambda r: r[0], reverse=True)
    out, seen = [], set()
    for _when, item in rows:
        if item['href'] in seen:
            continue
        seen.add(item['href'])
        out.append(item)
        if len(out) >= limit:
            break
    return out


class RecentPageMiddleware:
    """Records a navigation page or a record page (ticket, project, document,
    KB article, report template, client operations) the user opened, after
    the page itself answered 200 to a plain GET. The path is stored without
    its query string. Runs after authentication and the organization
    middleware (it only reads request.user and the resolved view)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:
            logger.debug('recording a recent page failed', exc_info=True)
        return response

    @staticmethod
    def _record(request, response):
        if request.method != 'GET' or response.status_code != 200:
            return
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return
        if request.headers.get('X-Requested-With') or 'text/html' not in response.get('Content-Type', ''):
            return
        match = getattr(request, 'resolver_match', None)
        view_name = getattr(match, 'view_name', '') or ''
        if not view_name or not recordable(view_name):
            return
        record_recent_page(user, request.path)
