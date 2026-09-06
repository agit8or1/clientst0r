"""Phase 32 (v3.17.556) — network discovery URLs."""
from django.urls import path

from . import views

app_name = 'network_discovery'

urlpatterns = [
    # The upload endpoint. Token-only, write-only, no session. Registered
    # first because it is the one address that is not org-scoped.
    path('upload/', views.upload, name='upload'),

    path('orgs/<int:org_id>/locations/<int:location_id>/',
         views.discovery_home, name='home'),
    path('orgs/<int:org_id>/locations/<int:location_id>/generate/',
         views.generate, name='generate'),
    path('orgs/<int:org_id>/locations/<int:location_id>/download/<int:token_id>/',
         views.download_script, name='download'),
    path('orgs/<int:org_id>/locations/<int:location_id>/revoke/<int:token_id>/',
         views.revoke, name='revoke'),
    path('orgs/<int:org_id>/locations/<int:location_id>/imports/<int:import_id>/',
         views.import_detail, name='import_detail'),

    # Phase 33 (v3.17.557–558) — collector endpoints. Key-only, like the
    # Phase 32 upload: config is the single read this credential can perform,
    # and it returns nothing but the site's own scan settings.
    path('collector/config/', views.collector_config, name='collector_config'),
    path('collector/results/', views.collector_results, name='collector_results'),

    path('orgs/<int:org_id>/locations/<int:location_id>/collectors/',
         views.sites, name='sites'),
    path('orgs/<int:org_id>/locations/<int:location_id>/collectors/register/',
         views.site_register, name='site_register'),
    path('orgs/<int:org_id>/locations/<int:location_id>/collectors/<int:site_id>/rotate/',
         views.site_rotate, name='site_rotate'),
    path('orgs/<int:org_id>/locations/<int:location_id>/collectors/<int:site_id>/revoke/',
         views.site_revoke, name='site_revoke'),
    path('orgs/<int:org_id>/locations/<int:location_id>/collectors/<int:site_id>/scan-now/',
         views.site_scan_now, name='site_scan_now'),
    path('orgs/<int:org_id>/locations/<int:location_id>/topology/',
         views.topology, name='topology'),
    path('orgs/<int:org_id>/locations/<int:location_id>/port-map/',
         views.port_map, name='port_map'),
]
