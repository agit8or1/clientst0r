"""
URL Configuration for Client St0r
"""
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include, re_path
from django.views.generic import RedirectView, TemplateView
from django.conf import settings
from two_factor.urls import urlpatterns as tf_urls

from accounts.otp_views import BackupTokensView

from core.views import privacy_policy as core_privacy_policy
from core.views import beta_onboarding as core_beta_onboarding
from core.views import health as core_health
from core.csp_views import csp_report as core_csp_report

urlpatterns = [
    # v3.17.490 — anonymous health endpoint for Docker HEALTHCHECK +
    # load balancers + uptime monitors. Returns 200 + JSON immediately.
    path('health/', core_health, name='health'),

    # CSP violation reports (core/csp_middleware.py report-uri / report-to).
    path('csp-report/', core_csp_report, name='csp_report'),

    # Favicon
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/favicon.svg', permanent=True)),

    # Legacy compatibility — see v3.17.154 fix; old bookmarks to /inbox/ now bounce to PSA AI inbox.
    path('inbox/', RedirectView.as_view(url='/psa/ai/inbox/', permanent=False), name='legacy_inbox'),

    # PWA offline fallback page (no login required, cached by service worker)
    path('offline/', TemplateView.as_view(template_name='core/offline.html'), name='offline'),

    # Admin
    path('admin/', admin.site.urls),

    # Two-Factor Auth
    # Backup codes are stored hashed: this view shows new codes once instead
    # of listing stored ones. Same path as two_factor:backup_tokens, listed
    # first so it wins; reverse() of the two_factor name still resolves here.
    path('account/two_factor/backup/tokens/', BackupTokensView.as_view(),
         name='backup_tokens_hashed'),
    path('', include(tf_urls)),

    # Legacy logout alias (for compatibility)
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),

    # Home - redirect to dashboard
    path('', RedirectView.as_view(url='/core/dashboard/', permanent=False), name='home'),

    # Apps
    path('core/', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('assets/', include('assets.urls')),
    path('vault/', include('vault.urls')),
    path('docs/', include('docs.urls')),
    path('readiness/', include('readiness.urls')),
    path('processes/', include('processes.urls')),
    path('files/', include('files.urls')),
    path('integrations/', include('integrations.urls')),
    path('audit/', include('audit.urls')),
    path('compliance/', include('compliance.urls')),
    path('monitoring/', include('monitoring.urls')),
    path('locations/', include('locations.urls')),
    path('imports/', include('imports.urls')),
    path('reports/', include('reports.urls')),
    path('vehicles/', include('vehicles.urls')),
    path('inventory/', include('inventory.urls')),
    path('scheduling/', include('scheduling.urls')),
    path('psa/', include('psa.urls')),
    path('psa/ai/', include('psa_ai.urls')),
    path('portal/', include('portal.urls')),
    path('resourcing/', include('resourcing.urls')),
    path('crm/', include('crm.urls')),
    path('security/', include('security_alerts.urls')),

    # Phase 8 — Field Ops + Timeclock + privacy
    path('field-ops/', include('field_ops.urls')),
    # Phase 40.2 (v3.17.540) — status pages. `/status/p/<token>/` is public.
    path('status/', include('statuspage.urls')),
    # Phase 34.1 (v3.17.544) — network device config backups.
    path('netconfig/', include('netconfig.urls')),
    # Phase 32 (v3.17.556) — remote network discovery. `/network-discovery/upload/`
    # is token-only and unauthenticated by design; everything else is gated.
    path('network-discovery/', include('network_discovery.urls')),

    # API
    path('api/', include('api.urls')),

    # Mobile API (token-authenticated REST surface for the RN client app)
    path('api/mobile/v1/', include('api_mobile.urls')),

    # Public privacy policy (Play Console + Apple App Store require a public URL)
    path('privacy-policy/', core_privacy_policy, name='privacy_policy'),

    # Public beta onboarding (v3.17.481) — landing page for testers who
    # follow the Play Open-Testing opt-in URL.
    path('beta-onboarding/', core_beta_onboarding, name='beta_onboarding'),
]

# Optional: GraphQL API v2 (only if graphene_django is installed)
try:
    from graphene_django.views import GraphQLView
    urlpatterns.append(
        # Session-authenticated, so CSRF protection stays on: an exempt
        # endpoint let any site drive mutations with a visitor's cookie.
        path('api/v2/graphql/', GraphQLView.as_view(graphiql=settings.DEBUG), name='graphql')
    )
except ImportError:
    pass

# Uploaded files. Every /media/ request goes through an authorization check
# (core.media_views): static() is a no-op with DEBUG=False and, where it did
# work, served every upload to anyone who could guess the path.
import re as _re
from core.media_views import serve_media as _serve_media
urlpatterns.append(re_path(
    r'^%s(?P<path>.+)$' % _re.escape(settings.MEDIA_URL.lstrip('/')),
    _serve_media, name='serve_media',
))


# ---------------------------------------------------------------------------
# Local-only app URL loader (v3.17.432).
# For each app in `<BASE_DIR>/local_apps/<name>/` that has a `urls.py`,
# mount it at `/<name>/`. Mirrors the INSTALLED_APPS auto-discover in
# settings.py. Generic — does not name any specific app.
# ---------------------------------------------------------------------------
from pathlib import Path as _PPath
_LOCAL_APPS_DIR = _PPath(settings.BASE_DIR) / 'local_apps'
if _LOCAL_APPS_DIR.is_dir():
    for _entry in sorted(_LOCAL_APPS_DIR.iterdir()):
        if _entry.is_dir() and (_entry / 'urls.py').exists() \
                and not _entry.name.startswith(('_', '.')):
            try:
                urlpatterns.append(
                    path(f'{_entry.name}/', include(f'{_entry.name}.urls'))
                )
            except Exception:
                # Don't crash the whole URL conf if one local app's
                # urls.py raises — just log and skip.
                import logging as _logging
                _logging.getLogger(__name__).exception(
                    'Local app %s urls.py failed to import', _entry.name
                )
