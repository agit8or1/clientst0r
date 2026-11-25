from django.urls import path

from . import views

app_name = 'health_score'

urlpatterns = [
    path('', views.client_list, name='list'),
    path('settings/', views.settings_view, name='settings'),
    path('<int:client_id>/', views.client_detail, name='detail'),
    path('<int:client_id>/recompute/', views.recompute, name='recompute'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'client_health_enabled')
