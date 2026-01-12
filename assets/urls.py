"""
Assets URL configuration
"""
from django.urls import path
from . import views
from . import relationship_views
from . import quick_views
from . import port_config_views
from . import port_views

app_name = 'assets'

urlpatterns = [
    path('', views.asset_list, name='asset_list'),
    path('create/', views.asset_create, name='asset_create'),
    path('quick/pc/', quick_views.quick_pc_add, name='quick_pc_add'),
    path('quick/server/', quick_views.quick_server_add, name='quick_server_add'),
    path('<int:pk>/', views.asset_detail, name='asset_detail'),
    path('<int:pk>/edit/', views.asset_edit, name='asset_edit'),
    path('<int:pk>/ports/', port_views.asset_port_config, name='asset_port_config'),
    path('<int:pk>/ports/save/', port_views.asset_port_config_save, name='asset_port_config_save'),

    # API endpoints
    path('api/equipment-model/<int:pk>/', views.equipment_model_api, name='equipment_model_api'),
    path('api/equipment-models-by-vendor/<int:vendor_id>/', views.equipment_models_by_vendor_api, name='equipment_models_by_vendor_api'),

    path('contacts/', views.contact_list, name='contact_list'),
    path('contacts/create/', views.contact_create, name='contact_create'),
    path('contacts/<int:pk>/', views.contact_detail, name='contact_detail'),
    path('contacts/<int:pk>/edit/', views.contact_edit, name='contact_edit'),
    path('contacts/<int:pk>/delete/', views.contact_delete, name='contact_delete'),

    # Relationships
    path('relationships/map/', relationship_views.relationship_map, name='relationship_map'),
    path('relationships/create/', relationship_views.relationship_create, name='relationship_create'),
    path('relationships/<int:pk>/delete/', relationship_views.relationship_delete, name='relationship_delete'),

    # Equipment Catalog
    path('vendors/', views.vendor_list, name='vendor_list'),
    path('vendors/create/', views.vendor_create, name='vendor_create'),
    path('vendors/<int:pk>/', views.vendor_detail, name='vendor_detail'),
    path('vendors/<int:pk>/edit/', views.vendor_edit, name='vendor_edit'),

    path('equipment-models/', views.equipment_model_list, name='equipment_model_list'),
    path('equipment-models/create/', views.equipment_model_create, name='equipment_model_create'),
    path('equipment-models/<int:pk>/', views.equipment_model_detail, name='equipment_model_detail'),
    path('equipment-models/<int:pk>/edit/', views.equipment_model_edit, name='equipment_model_edit'),

    # Port Configuration
    path('port-configs/', port_config_views.port_config_list, name='port_config_list'),
    path('port-configs/create/', port_config_views.port_config_create, name='port_config_create'),
    path('port-configs/<int:pk>/', port_config_views.port_config_detail, name='port_config_detail'),
    path('port-configs/<int:pk>/edit/', port_config_views.port_config_edit, name='port_config_edit'),
    path('port-configs/<int:pk>/delete/', port_config_views.port_config_delete, name='port_config_delete'),

    # Port Configuration API
    path('api/port-configs/<int:pk>/ports/', port_config_views.port_config_api_ports, name='port_config_api_ports'),
    path('api/equipment-model/<int:pk>/image/', port_config_views.equipment_model_image_api, name='equipment_model_image_api'),
]
