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

    # Organization Mapping
    path('<int:pk>/map-organizations/', views.psa_organization_mapping, name='psa_organization_mapping'),
    path('rmm/<int:pk>/map-organizations/', views.rmm_organization_mapping, name='rmm_organization_mapping'),

    # RMM Views
    path('rmm/create/', views.rmm_create, name='rmm_create'),
    path('rmm/<int:pk>/', views.rmm_detail, name='rmm_detail'),
    path('rmm/<int:pk>/edit/', views.rmm_edit, name='rmm_edit'),
    path('rmm/<int:pk>/delete/', views.rmm_delete, name='rmm_delete'),
    path('rmm/<int:pk>/sync/', views.rmm_trigger_sync, name='rmm_trigger_sync'),
    path('rmm/<int:pk>/import-clients/', views.rmm_import_clients, name='rmm_import_clients'),

    # RMM Data Views
    path('rmm/devices/', views.rmm_devices, name='rmm_devices'),
    path('rmm/devices/<int:pk>/', views.rmm_device_detail, name='rmm_device_detail'),
    path('rmm/devices/<int:pk>/delete/', views.rmm_device_delete, name='rmm_device_delete'),
    path('rmm/device-map-data/', views.rmm_device_map_data, name='rmm_device_map_data'),
    path('rmm/global-device-map-data/', views.global_rmm_device_map_data, name='global_rmm_device_map_data'),
    path('rmm/alerts/', views.rmm_alerts, name='rmm_alerts'),
    path('rmm/software/', views.rmm_software, name='rmm_software'),

    # UniFi
    path('unifi/create/', views.unifi_create, name='unifi_create'),
    path('unifi/<int:pk>/', views.unifi_detail, name='unifi_detail'),
    path('unifi/<int:pk>/edit/', views.unifi_edit, name='unifi_edit'),
    path('unifi/<int:pk>/delete/', views.unifi_delete, name='unifi_delete'),
    path('unifi/<int:pk>/test/', views.unifi_test, name='unifi_test'),
    path('unifi/<int:pk>/sync/', views.unifi_sync, name='unifi_sync'),
    path('unifi/<int:pk>/import-assets/', views.unifi_import_assets, name='unifi_import_assets'),
    path('unifi/<int:pk>/site-org/', views.unifi_site_org, name='unifi_site_org'),

    # M365
    path('m365/create/', views.m365_create, name='m365_create'),
    path('m365/<int:pk>/', views.m365_detail, name='m365_detail'),
    path('m365/<int:pk>/edit/', views.m365_edit, name='m365_edit'),
    path('m365/<int:pk>/delete/', views.m365_delete, name='m365_delete'),
    path('m365/<int:pk>/test/', views.m365_test, name='m365_test'),
    path('m365/<int:pk>/sync/', views.m365_sync, name='m365_sync'),

    # Omada
    path('omada/create/', views.omada_create, name='omada_create'),
    path('omada/<int:pk>/', views.omada_detail, name='omada_detail'),
    path('omada/<int:pk>/edit/', views.omada_edit, name='omada_edit'),
    path('omada/<int:pk>/delete/', views.omada_delete, name='omada_delete'),
    path('omada/<int:pk>/test/', views.omada_test, name='omada_test'),
    path('omada/<int:pk>/sync/', views.omada_sync, name='omada_sync'),
    path('omada/<int:pk>/import-assets/', views.omada_import_assets, name='omada_import_assets'),

    # Grandstream
    path('grandstream/create/', views.grandstream_create, name='grandstream_create'),
    path('grandstream/<int:pk>/', views.grandstream_detail, name='grandstream_detail'),
    path('grandstream/<int:pk>/edit/', views.grandstream_edit, name='grandstream_edit'),
    path('grandstream/<int:pk>/delete/', views.grandstream_delete, name='grandstream_delete'),
    path('grandstream/<int:pk>/test/', views.grandstream_test, name='grandstream_test'),
    path('grandstream/<int:pk>/sync/', views.grandstream_sync, name='grandstream_sync'),
    path('grandstream/<int:pk>/import-assets/', views.grandstream_import_assets, name='grandstream_import_assets'),

    # Distributors (Workstream 8) — catalog/pricing/stock/order/webhook
    path('distributors/', views.distributor_list, name='distributor_list'),
    path('distributors/create/', views.distributor_create, name='distributor_create'),
    path('distributors/<int:pk>/edit/', views.distributor_edit, name='distributor_edit'),
    path('distributors/<int:pk>/delete/', views.distributor_delete, name='distributor_delete'),
    path('distributors/<int:pk>/test/', views.distributor_test, name='distributor_test'),
    path('distributors/<int:pk>/pricing/', views.distributor_pricing, name='distributor_pricing'),
    # Phase 13 v10 (v3.17.272): cross-distributor stock check.
    path('distributors/stock-check/', views.distributor_stock_check,
         name='distributor_stock_check'),
    # Webhook receiver — opaque token in path, signature verified inside.
    path('distributors/webhooks/<str:token>/', views.distributor_webhook,
         name='distributor_webhook'),

    # Accounting (Workstream 5 — billing handoff)
    path('accounting/', views.accounting_list, name='accounting_list'),
    path('accounting/create/', views.accounting_create, name='accounting_create'),
    path('accounting/<int:pk>/edit/', views.accounting_edit, name='accounting_edit'),
    path('accounting/<int:pk>/delete/', views.accounting_delete, name='accounting_delete'),
    path('accounting/<int:pk>/test/', views.accounting_test, name='accounting_test'),
    path('accounting/<int:pk>/audit-log/', views.accounting_audit_log,
         name='accounting_audit_log'),
    # Phase 44.3 (v3.17.530) — run the sync on demand.
    path('accounting/<int:pk>/sync/', views.accounting_sync_now,
         name='accounting_sync_now'),
    # Phase 44.1 (v3.17.528) — the customer mapping, now a real table.
    path('accounting/<int:pk>/customers/', views.accounting_customers,
         name='accounting_customers'),
    path('accounting/<int:pk>/customers/pull/', views.accounting_pull_customers,
         name='accounting_pull_customers'),
    path('accounting/<int:pk>/customers/<int:org_pk>/push/',
         views.accounting_push_customer, name='accounting_push_customer'),
    path('accounting/<int:pk>/connect/', views.accounting_connect, name='accounting_connect'),
    path('accounting/oauth/callback/', views.accounting_oauth_callback,
         name='accounting_oauth_callback'),
]
