"""JSON endpoints behind the command palette and the top bar's Favorites
and Recent menus (core/palette.py has the rules).

* ``core:palette_home``   GET  — favorites, recent, quick commands and the
  navigation destinations (``?parts=`` narrows it; ``?path=`` adds whether
  that page can be starred).
* ``core:palette_search`` GET  — grouped record results. The query travels
  in the ``X-Palette-Query`` header (``?q=`` is accepted as a fallback), so
  it does not end up in web-server access logs; the audit middleware does
  not record list-type GETs, and this view records nothing itself.
  Rate-limited per user.
* ``core:palette_favorite`` POST — star / unstar a page by path.

All answers are ``Cache-Control: no-store`` and carry labels and links only.
"""
from urllib.parse import unquote

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from . import palette

SEARCH_RATE = '120/m'
_PARTS = ('favorites', 'recent', 'commands', 'destinations')


def _search_rate(group, request):
    return SEARCH_RATE


def _json(data, status=200):
    resp = JsonResponse(data, status=status)
    resp['Cache-Control'] = 'no-store'
    return resp


@never_cache
@login_required
@require_GET
def palette_home(request):
    pal = palette.Palette(request)
    wanted = [p for p in (request.GET.get('parts') or ','.join(_PARTS)).split(',') if p in _PARTS]
    data = {}
    if 'favorites' in wanted:
        data['favorites'] = palette.favorites(pal)
    if 'recent' in wanted:
        data['recent'] = palette.recent(pal)
    if 'commands' in wanted:
        data['commands'] = palette.commands(pal)
    if 'destinations' in wanted:
        data['destinations'] = pal.destinations
    if request.GET.get('path'):
        data['current'] = palette.current_state(pal, request.GET.get('path'))
    return _json(data)


@never_cache
@login_required
@require_GET
@ratelimit(group='core.palette_search', key='user', rate=_search_rate, method='GET', block=False)
def palette_search(request):
    if getattr(request, 'limited', False):
        return _json({'error': 'rate_limited', 'groups': []}, status=429)
    raw = request.headers.get('X-Palette-Query')
    query = unquote(raw) if raw else (request.GET.get('q') or '')
    pal = palette.Palette(request)
    return _json({'groups': palette.search(pal, query)})


@login_required
@require_POST
def palette_favorite(request):
    pal = palette.Palette(request)
    try:
        state = palette.toggle_favorite(pal, request.POST.get('path', ''))
    except palette.FavoriteRefused as why:
        status = 400 if str(why) in ('bad path', 'full') else 404
        return _json({'error': str(why)}, status=status)
    return _json({'current': state})
