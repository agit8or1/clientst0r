"""Branded 404 and 500 pages (113.4).

404: a signed-in user gets the page inside the app shell (templates/404.html,
search and a way back); anyone else gets the same message on a bare page with
no navigation (templates/errors/404_public.html), so the shell never leaks.

500: static. The template is rendered with no request and no context
processors, so it makes no database query and cannot fail the way the page it
replaces did; if even that fails, a literal string is returned. Nothing about
the error (message, path, traceback) is shown. Django has already logged it.

With DEBUG on, Django shows its technical pages before these handlers run.
"""
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.template import loader
from django.views.decorators.csrf import requires_csrf_token

_FALLBACK_500 = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
    'content="width=device-width, initial-scale=1"><title>Something went wrong</title></head>'
    '<body><main><h1>Something went wrong</h1><p>The page could not be shown because of a '
    'problem on the server. It has been logged. Try again in a minute, or go back to the '
    '<a href="/">start page</a>. If it keeps happening, tell your administrator.</p>'
    '<p>Error 500</p></main></body></html>'
)


@requires_csrf_token
def not_found(request, exception=None, template_name='404.html'):
    user = getattr(request, 'user', None)
    if not (user is not None and user.is_authenticated):
        template_name = 'errors/404_public.html'
    try:
        body = loader.get_template(template_name).render({}, request)
    except Exception:
        body = loader.get_template('errors/404_public.html').render({}, None)
    return HttpResponseNotFound(body)


@requires_csrf_token
def server_error(request, template_name='500.html'):
    try:
        body = loader.get_template(template_name).render({})
    except Exception:
        body = _FALLBACK_500
    return HttpResponseServerError(body)
