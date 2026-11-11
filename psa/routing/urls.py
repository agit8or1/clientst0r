from django.urls import path

from . import alert_views, views

app_name = 'ticket_routing'

urlpatterns = [
    path('alerts/', alert_views.alerts, name='alerts'),
    path('alerts/rules/new/', alert_views.alert_rule_form, name='alert_rule_new'),
    path('alerts/rules/<int:pk>/', alert_views.alert_rule_form, name='alert_rule_edit'),
    path('alerts/maintenance/', alert_views.alert_maintenance, name='alert_maintenance'),
    path('', views.overview, name='overview'),
    path('mode/', views.quick_mode, name='quick_mode'),
    path('customers/<int:org_id>/', views.customer_settings, name='customer'),
    path('rules/new/', views.rule_form, name='rule_new'),
    path('rules/<int:pk>/', views.rule_detail, name='rule_detail'),
    path('rules/<int:pk>/edit/', views.rule_form, name='rule_edit'),
    path('rules/<int:pk>/toggle/', views.rule_toggle, name='rule_toggle'),
    path('rules/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
    path('on-call/', views.on_call, name='on_call'),
    path('test/', views.test_routing, name='test'),
    path('triage/', views.triage, name='triage'),
    path('decisions/<int:pk>/decide/', views.decide, name='decide'),
]
