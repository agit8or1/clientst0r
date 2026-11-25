from django.urls import path

from . import views

app_name = 'licensing'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('customer/<int:org_id>/', views.customer, name='customer'),
    path('customer/<int:org_id>/subscriptions/new/', views.subscription_edit, name='subscription_create'),
    path('customer/<int:org_id>/sync/', views.sync_now, name='sync_now'),
    path('subscriptions/<int:pk>/', views.subscription_detail, name='subscription_detail'),
    path('subscriptions/<int:pk>/edit/', views.subscription_edit, name='subscription_edit'),
    path('subscriptions/<int:pk>/delete/', views.subscription_delete, name='subscription_delete'),
    path('subscriptions/<int:pk>/assign/', views.assignment_add, name='assignment_add'),
    path('assignments/<int:pk>/delete/', views.assignment_delete, name='assignment_delete'),
    path('renewals/', views.renewals, name='renewals'),
    path('export.csv', views.export_csv, name='export_csv'),
    path('mappings/', views.mappings, name='mappings'),
    path('mappings/<int:pk>/delete/', views.mapping_delete, name='mapping_delete'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'licensing_enabled')
