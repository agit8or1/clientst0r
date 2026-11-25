from django.urls import path

from . import views

app_name = 'backup_monitoring'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('customer/<int:org_id>/', views.customer_detail, name='customer_detail'),
    path('jobs/<int:pk>/', views.job_detail, name='job_detail'),
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/<int:pk>/decide/', views.alert_decide, name='alert_decide'),
    path('restore-tests/', views.restore_test_list, name='restore_test_list'),
    path('restore-tests/new/', views.restore_test_form, name='restore_test_create'),
    path('connections/', views.connection_list, name='connection_list'),
    path('connections/new/', views.connection_form, name='connection_create'),
    path('connections/<int:pk>/edit/', views.connection_form, name='connection_edit'),
    path('connections/<int:pk>/test/', views.connection_test, name='connection_test'),
    path('connections/<int:pk>/poll/', views.connection_poll, name='connection_poll'),
    path('connections/<int:pk>/delete/', views.connection_delete, name='connection_delete'),
    path('systems/new/', views.system_create, name='system_create'),
    path('systems/<int:pk>/edit/', views.system_edit, name='system_edit'),
    path('policy/<int:org_id>/', views.policy_edit, name='policy_edit'),
    path('ingest/<uuid:ingest_id>/', views.ingest, name='ingest'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'backup_monitoring_enabled')
