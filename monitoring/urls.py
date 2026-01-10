"""
Monitoring URL configuration
"""
from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    # Website Monitoring
    path('websites/', views.website_monitor_list, name='website_monitor_list'),
    path('websites/create/', views.website_monitor_create, name='website_monitor_create'),
    path('websites/<int:pk>/', views.website_monitor_detail, name='website_monitor_detail'),
    path('websites/<int:pk>/edit/', views.website_monitor_edit, name='website_monitor_edit'),
    path('websites/<int:pk>/delete/', views.website_monitor_delete, name='website_monitor_delete'),
    path('websites/<int:pk>/check/', views.website_monitor_check, name='website_monitor_check'),

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
]
