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
]
