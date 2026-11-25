from django.urls import path

from . import views

app_name = 'onboarding'

urlpatterns = [
    path('', views.start, name='start'),
    path('session/<int:pk>/', views.session_detail, name='session'),
    path('session/<int:pk>/step/<slug:key>/', views.step_view, name='step'),
    path('session/<int:pk>/step/<slug:key>/skip/', views.step_skip, name='skip'),
    path('session/<int:pk>/step/<slug:key>/reopen/', views.step_reopen, name='reopen'),
    path('session/<int:pk>/cancel/', views.session_cancel, name='cancel'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'onboarding_enabled')
