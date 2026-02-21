"""
Monitoring URL configuration
"""
from django.urls import path
from . import views
from . import api_views
from . import patch_panel_views
from . import vlan_views

app_name = 'monitoring'

urlpatterns = [
    # Website Monitoring
    path('websites/', views.website_monitor_list, name='website_monitor_list'),
    path('websites/create/', views.website_monitor_create, name='website_monitor_create'),
    path('websites/<int:pk>/', views.website_monitor_detail, name='website_monitor_detail'),
    path('websites/<int:pk>/edit/', views.website_monitor_edit, name='website_monitor_edit'),
    path('websites/<int:pk>/delete/', views.website_monitor_delete, name='website_monitor_delete'),
    path('websites/<int:pk>/check/', views.website_monitor_check, name='website_monitor_check'),

    # WAN Connection Monitoring
    path('wans/', views.wan_monitor_list, name='wan_monitor_list'),

    # Expirations Dashboard
    path('expirations/', views.expiration_list, name='expiration_list'),
    path('expirations/create/', views.expiration_create, name='expiration_create'),
    path('expirations/<int:pk>/edit/', views.expiration_edit, name='expiration_edit'),
    path('expirations/<int:pk>/delete/', views.expiration_delete, name='expiration_delete'),

    # Rack Management
    path('racks/', views.rack_list, name='rack_list'),
    path('racks/create/', views.rack_create, name='rack_create'),
    path('racks/<int:pk>/', views.rack_detail, name='rack_detail'),
    path('racks/<int:pk>/edit/', views.rack_edit, name='rack_edit'),
    path('racks/<int:pk>/delete/', views.rack_delete, name='rack_delete'),

    # Rack Devices
    path('racks/<int:rack_id>/devices/create/', views.rack_device_create, name='rack_device_create'),
    path('devices/<int:pk>/edit/', views.rack_device_edit, name='rack_device_edit'),
    path('devices/<int:pk>/delete/', views.rack_device_delete, name='rack_device_delete'),

    # IPAM - Subnets
    path('ipam/', views.subnet_list, name='subnet_list'),
    path('ipam/subnets/create/', views.subnet_create, name='subnet_create'),
    path('ipam/subnets/<int:pk>/', views.subnet_detail, name='subnet_detail'),
    path('ipam/subnets/<int:pk>/edit/', views.subnet_edit, name='subnet_edit'),
    path('ipam/subnets/<int:pk>/delete/', views.subnet_delete, name='subnet_delete'),

    # IPAM - IP Addresses
    path('ipam/subnets/<int:subnet_id>/ips/create/', views.ip_address_create, name='ip_address_create'),
    path('ipam/ips/<int:pk>/edit/', views.ip_address_edit, name='ip_address_edit'),
    path('ipam/ips/<int:pk>/delete/', views.ip_address_delete, name='ip_address_delete'),

    # VLANs
    path('vlans/', vlan_views.vlan_list, name='vlan_list'),
    path('vlans/create/', vlan_views.vlan_create, name='vlan_create'),
    path('vlans/<int:pk>/', vlan_views.vlan_detail, name='vlan_detail'),
    path('vlans/<int:pk>/edit/', vlan_views.vlan_edit, name='vlan_edit'),
    path('vlans/<int:pk>/delete/', vlan_views.vlan_delete, name='vlan_delete'),

    # Network Closets
    path('closets/', views.network_closet_list, name='network_closet_list'),
    path('closets/create/', views.network_closet_create, name='network_closet_create'),
    path('closets/<int:pk>/', views.network_closet_detail, name='network_closet_detail'),
    path('closets/<int:pk>/edit/', views.network_closet_edit, name='network_closet_edit'),
    path('closets/<int:pk>/delete/', views.network_closet_delete, name='network_closet_delete'),

    # Patch Panels
    path('patch-panels/', patch_panel_views.patch_panel_list, name='patch_panel_list'),
    path('patch-panels/create/', patch_panel_views.patch_panel_create, name='patch_panel_create'),
    path('patch-panels/quick-create/', patch_panel_views.patch_panel_quick_create, name='patch_panel_quick_create'),
    path('patch-panels/<int:pk>/', patch_panel_views.patch_panel_detail, name='patch_panel_detail'),
    path('patch-panels/<int:pk>/edit/', patch_panel_views.patch_panel_edit, name='patch_panel_edit'),
    path('patch-panels/<int:pk>/delete/', patch_panel_views.patch_panel_delete, name='patch_panel_delete'),
    path('api/patch-panels/<int:pk>/ports/', patch_panel_views.patch_panel_api_ports, name='patch_panel_api_ports'),

    # Rack Device API endpoints
    path('api/racks/<int:pk>/devices/', api_views.rack_devices_list, name='api_rack_devices_list'),
    path('api/rack-devices/<int:pk>/update-position/', api_views.update_rack_device_position, name='api_update_rack_device_position'),
    path('api/rack-devices/<int:pk>/', api_views.rack_device_detail, name='api_rack_device_detail'),
    path('api/racks/<int:pk>/devices/create/', api_views.create_rack_device, name='api_create_rack_device'),
]
