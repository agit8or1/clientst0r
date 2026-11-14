"""Back to the ticket" context for the daily ticket workflow.

A technician working a ticket often opens its client, then a device, then
the device's RMM view. Links on those pages carry ``?return_to=<ticket
path>`` (static/js/app_nav.js adds it to in-page links that lead to client
and device pages), and base.html shows a "Back to PSA-…" link while it is
present.

The value is never trusted: :func:`clean_return_to` accepts only a
same-site relative path that resolves to one of RETURN_VIEWS, and the link
it returns is rebuilt with ``reverse()`` from the resolved arguments, so a
crafted value can neither point off-site nor smuggle a query string or a
fragment. Nothing is looked up in the database: the label is the ticket
number already in the URL, and the ticket page itself still decides who may
open it. Nothing is stored server-side or in the browser.
"""
import re

from django.urls import NoReverseMatch, Resolver404, resolve, reverse

PARAM = 'return_to'
MAX_LEN = 200

# view name -> URL kwarg holding the reference shown on the link.
RETURN_VIEWS = {
    'psa:ticket_detail': 'ticket_number',
}

_REF_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,31}$')
_PATH_RE = re.compile(r'^/[A-Za-z0-9/_.~-]*$')


def clean_return_to(raw):
    """``{'href', 'label', 'view'}`` for a valid return path, else None."""
    if not raw or not isinstance(raw, str) or len(raw) > MAX_LEN:
        return None
    path = raw.strip()
    # Relative, single leading slash, no scheme / host / backslash / control
    # characters / query / fragment / dot segments.
    if not _PATH_RE.match(path) or path.startswith('//') or '/../' in path or path.endswith('/..') \
            or '/./' in path:
        return None
    try:
        match = resolve(path)
    except Resolver404:
        return None
    kwarg = RETURN_VIEWS.get(match.view_name)
    if kwarg is None:
        return None
    ref = str(match.kwargs.get(kwarg) or '')
    if not _REF_RE.match(ref):
        return None
    try:
        href = reverse(match.view_name, kwargs={kwarg: ref})
    except NoReverseMatch:
        return None
    if href != path:
        return None
    return {'href': href, 'label': ref, 'view': match.view_name}


def origin_for(request):
    """The current page as a return target (it is a ticket page), else ''."""
    match = getattr(request, 'resolver_match', None)
    if match is None or match.view_name not in RETURN_VIEWS:
        return ''
    found = clean_return_to(request.path)
    return found['href'] if found else ''


def return_context(request):
    """What base.html needs: ``{'chip', 'origin', 'scope'}``.

    ``chip`` is the validated return target from the query string (None
    when absent, invalid, or the current page itself); ``origin`` the path
    links on this page should carry onward (the chip's target, or this page
    when it is a ticket); ``scope`` the path patterns of the pages that
    carry it (client workspace and device pages).
    """
    out = {'chip': None, 'origin': '', 'scope': ''}
    if request is None:
        return out
    chip = clean_return_to(request.GET.get(PARAM, ''))
    if chip is not None and chip['href'] == request.path:
        chip = None
    out['chip'] = chip
    out['origin'] = chip['href'] if chip else origin_for(request)
    out['scope'] = ' '.join(scope_patterns())
    return out


_SCOPE = None


def scope_patterns():
    """Path prefixes (with ``{id}`` for the numeric id) of the pages a
    return target is carried to: the client workspace and device pages."""
    global _SCOPE
    if _SCOPE is None:
        out = []
        for name in ('accounts:organization_detail', 'assets:asset_detail', 'assets:device_workspace',
                     'integrations:rmm_device_detail', 'hardware:device_detail'):
            try:
                out.append(reverse(name, args=[987654321]).replace('987654321', '{id}'))
            except NoReverseMatch:
                continue
        try:
            out.append(reverse('core:open_device', args=['asset', 987654321])
                       .replace('asset', '{kind}', 1).replace('987654321', '{id}'))
        except NoReverseMatch:
            pass
        _SCOPE = out
    return _SCOPE
