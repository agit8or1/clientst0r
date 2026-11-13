"""Staff pulse check pages under /pulse/ (MSP staff only). The customer
pages are in the portal namespace (portal/urls.py → pulse.portal_views)."""
from django.urls import path

from core.feature_gates import gate_patterns

from . import views

app_name = 'pulse'

urlpatterns = gate_patterns([
    path('', views.check_list, name='check_list'),
    path('new/', views.check_create, name='check_create'),
    path('opt-outs/', views.opt_out_list, name='opt_out_list'),
    path('<int:pk>/', views.check_detail, name='check_detail'),
    path('<int:pk>/edit/', views.check_edit, name='check_edit'),
    path('<int:pk>/send/', views.check_send, name='check_send'),
    path('<int:pk>/toggle/', views.check_toggle, name='check_toggle'),
    path('sends/<int:pk>/', views.send_detail, name='send_detail'),
], 'pulse_enabled')
