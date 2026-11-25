"""
field_ops URLs — Phase 8 Timeclock + privacy.

Mounted at `/field-ops/` in `config/urls.py`. The timeclock dashboard
also gets a top-level `/timeclock/` mount for discoverability.
"""
from django.urls import path

from . import dispatch_views, views

app_name = 'field_ops'

urlpatterns = [
    # Sub-phase 8.3 (v3.17.413)
    path('timeclock/', views.timeclock_dashboard, name='timeclock_dashboard'),
    path(
        'timeclock/payroll-export.csv',
        views.timeclock_payroll_export, name='timeclock_payroll_export',
    ),
    # Sub-phase 8.5 (v3.17.415)
    path(
        'my-location-history/', views.my_location_history,
        name='my_location_history',
    ),
    path(
        'my-location-history/<int:pk>/delete/',
        views.my_location_delete, name='my_location_delete',
    ),
    path(
        'my-location-history/delete-all/',
        views.my_location_delete_all, name='my_location_delete_all',
    ),
    # Sub-phase 8.5 part 3 (v3.17.416)
    path('settings/', views.settings_view, name='settings'),
    # Phase 11 — geo-aware dispatch (opt-in)
    path('dispatch-sharing/', dispatch_views.dispatch_sharing, name='dispatch_sharing'),
    path('dispatch-geo/', dispatch_views.dispatch_geo_settings, name='dispatch_geo_settings'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
# Settings and a user's own location history (view / delete) stay
# available while the module is off.
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'field_ops_enabled', exclude=('my_location_delete', 'my_location_delete_all', 'my_location_history', 'settings'))
