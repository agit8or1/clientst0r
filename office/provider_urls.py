"""URL patterns contributed by provider connectors, mounted at /office/api/.

Each connector appends its patterns here, e.g.

    from office.providers.onlyoffice import views as oo
    urlpatterns += [path('onlyoffice/callback/<uuid:session_id>/', oo.callback, ...)]

Views here are reached by the editor service, not a browser session: they
must be csrf_exempt, authenticate with office.tokens.validate() (or the
provider's signature check followed by it), and never rely on request.user.
(Exception: a connector's own browser helpers, such as Collabora's token
renewal, are login_required and keep CSRF protection.)
"""
urlpatterns = []

from django.urls import include, path  # noqa: E402

urlpatterns += [path('onlyoffice/', include('office.providers.onlyoffice.urls'))]

# Collabora Online: WOPI host + editor-page helpers (office/providers/collabora/urls.py).
from office.providers.collabora.urls import urlpatterns as _collabora  # noqa: E402
urlpatterns += _collabora
