"""Phase 40.2 (v3.17.540) — status page URLs."""
from django.urls import path

from . import views

app_name = 'statuspage'

urlpatterns = [
    # Management (authenticated, admin-only).
    path('', views.page_list, name='list'),
    path('new/', views.page_create, name='create'),
    path('<int:pk>/', views.page_detail, name='detail'),
    # The public page. Last, so the token pattern cannot shadow the routes
    # above — a page whose token happened to be "new" would otherwise be
    # unreachable.
    path('p/<str:token>/', views.public, name='public'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'status_pages_enabled')
