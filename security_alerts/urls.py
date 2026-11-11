from django.urls import path
from . import views


app_name = 'security_alerts'

urlpatterns = [
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/<int:pk>/', views.alert_detail, name='alert_detail'),
    path('alerts/<int:pk>/decide/', views.alert_decide, name='alert_decide'),
    path('alerts/bulk/', views.alert_bulk_decide, name='alert_bulk_decide'),
    path('connections/', views.connection_list, name='connection_list'),
    path('connections/new/', views.connection_form, name='connection_create'),
    path('connections/<int:pk>/edit/', views.connection_form, name='connection_edit'),
    path('connections/<int:pk>/test/', views.connection_test, name='connection_test'),
    path('connections/<int:pk>/sync/', views.connection_sync, name='connection_sync'),
    path('rules/', views.rule_list, name='rule_list'),
    path('rules/new/', views.rule_form, name='rule_create'),
    path('rules/<int:pk>/edit/', views.rule_form, name='rule_edit'),
    path('webhook/<str:token>/', views.webhook_receive, name='webhook_receive'),
    # Phase 23 v3.17.337 — SIEM webhook endpoints
    path('siem/', views.siem_endpoint_list, name='siem_endpoint_list'),
    path('siem/new/', views.siem_endpoint_form, name='siem_endpoint_create'),
    path('siem/<int:pk>/edit/', views.siem_endpoint_form, name='siem_endpoint_edit'),
    path('siem/webhook/<str:token>/', views.siem_webhook_receive, name='siem_webhook_receive'),
    # Phase 23 v3.17.338 — incidents + timelines
    path('incidents/', views.incident_list, name='incident_list'),
    path('incidents/<int:pk>/', views.incident_detail, name='incident_detail'),
    path('incidents/<int:pk>/decide/', views.incident_decide, name='incident_decide'),
    # Phase 23 v3.17.362 — OPTIONAL AI incident summarization
    path('incidents/<int:pk>/ai-summarize/', views.incident_ai_summarize, name='incident_ai_summarize'),
    # Phase 23 v3.17.356 — remediation playbooks
    path('playbooks/', views.playbook_list, name='playbook_list'),
    # Phase 23 v3.17.359 — threat visibility dashboard
    path('threat-overview/', views.threat_overview, name='threat_overview'),
    # Phase 9.4 — weekly digest of unresolved alerts for customer contacts
    path('digest/', views.digest_subscriptions, name='digest_subscriptions'),
    path('digest/unsubscribe/<str:token>/', views.digest_unsubscribe, name='digest_unsubscribe'),
]
