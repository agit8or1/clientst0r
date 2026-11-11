"""URL patterns contributed by provider connectors, mounted at /office/api/.

Each connector appends its patterns here, e.g.

    from office.providers.onlyoffice import views as oo
    urlpatterns += [path('onlyoffice/callback/<uuid:session_id>/', oo.callback, ...)]

Views here are reached by the editor service, not a browser session: they
must be csrf_exempt, authenticate with office.tokens.validate() (or the
provider's signature check followed by it), and never rely on request.user.
"""
urlpatterns = []
