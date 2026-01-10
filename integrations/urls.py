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
]
