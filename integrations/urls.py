"""
Integrations URL configuration
"""
from django.urls import path
from . import views

app_name = 'integrations'

urlpatterns = [
    path('', views.integration_list, name='integration_list'),
    path('create/', views.integration_create, name='integration_create'),
    path('<int:pk>/', views.integration_detail, name='integration_detail'),
    path('<int:pk>/edit/', views.integration_edit, name='integration_edit'),
    path('<int:pk>/delete/', views.integration_delete, name='integration_delete'),
    path('<int:pk>/test/', views.integration_test, name='integration_test'),
    path('<int:pk>/sync/', views.integration_sync, name='integration_sync'),

    # PSA Data Views
    path('companies/', views.psa_companies, name='psa_companies'),
    path('companies/<int:pk>/', views.psa_company_detail, name='psa_company_detail'),
    path('contacts/', views.psa_contacts, name='psa_contacts'),
    path('contacts/<int:pk>/', views.psa_contact_detail, name='psa_contact_detail'),
    path('tickets/', views.psa_tickets, name='psa_tickets'),
    path('tickets/<int:pk>/', views.psa_ticket_detail, name='psa_ticket_detail'),

    # RMM Views
    path('rmm/create/', views.rmm_create, name='rmm_create'),
    path('rmm/<int:pk>/', views.rmm_detail, name='rmm_detail'),
    path('rmm/<int:pk>/edit/', views.rmm_edit, name='rmm_edit'),
    path('rmm/<int:pk>/delete/', views.rmm_delete, name='rmm_delete'),
    path('rmm/<int:pk>/sync/', views.rmm_trigger_sync, name='rmm_trigger_sync'),

    # RMM Data Views
    path('rmm/devices/', views.rmm_devices, name='rmm_devices'),
    path('rmm/devices/<int:pk>/', views.rmm_device_detail, name='rmm_device_detail'),
    path('rmm/device-map-data/', views.rmm_device_map_data, name='rmm_device_map_data'),
    path('rmm/global-device-map-data/', views.global_rmm_device_map_data, name='global_rmm_device_map_data'),
    path('rmm/alerts/', views.rmm_alerts, name='rmm_alerts'),
    path('rmm/software/', views.rmm_software, name='rmm_software'),
]
