"""
Audit URL configuration
"""
from django.urls import path
from . import views

app_name = 'audit'

urlpatterns = [
    path('', views.audit_log_list, name='audit_log_list'),
    path('<int:pk>/', views.audit_log_detail, name='audit_log_detail'),
]
