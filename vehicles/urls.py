"""
URL configuration for Service Vehicles
"""
from django.urls import path
from . import views

app_name = 'vehicles'

urlpatterns = [
    # Dashboard
    path('', views.vehicles_dashboard, name='vehicles_dashboard'),

    # Vehicle CRUD
    path('vehicles/', views.vehicle_list, name='vehicle_list'),
    path('vehicles/create/', views.vehicle_create, name='vehicle_create'),
    path('vehicles/<int:pk>/', views.vehicle_detail, name='vehicle_detail'),
    path('vehicles/<int:pk>/edit/', views.vehicle_edit, name='vehicle_edit'),
    path('vehicles/<int:pk>/delete/', views.vehicle_delete, name='vehicle_delete'),

    # Inventory
    path('vehicles/<int:vehicle_id>/inventory/create/', views.inventory_item_create, name='inventory_item_create'),
    path('inventory/<int:pk>/edit/', views.inventory_item_edit, name='inventory_item_edit'),
    path('inventory/<int:pk>/delete/', views.inventory_item_delete, name='inventory_item_delete'),

    # Damage Reports
    path('vehicles/<int:vehicle_id>/damage/create/', views.damage_report_create, name='damage_report_create'),
    path('damage/<int:pk>/edit/', views.damage_report_edit, name='damage_report_edit'),
    path('damage/<int:pk>/delete/', views.damage_report_delete, name='damage_report_delete'),

    # Maintenance
    path('vehicles/<int:vehicle_id>/maintenance/create/', views.maintenance_record_create, name='maintenance_record_create'),
    path('maintenance/<int:pk>/edit/', views.maintenance_record_edit, name='maintenance_record_edit'),
    path('maintenance/<int:pk>/delete/', views.maintenance_record_delete, name='maintenance_record_delete'),

    # Fuel Logs
    path('vehicles/<int:vehicle_id>/fuel/create/', views.fuel_log_create, name='fuel_log_create'),
    path('fuel/<int:pk>/edit/', views.fuel_log_edit, name='fuel_log_edit'),
    path('fuel/<int:pk>/delete/', views.fuel_log_delete, name='fuel_log_delete'),

    # Assignments
    path('vehicles/<int:vehicle_id>/assign/', views.assignment_create, name='assignment_create'),
    path('assignments/<int:pk>/end/', views.assignment_end, name='assignment_end'),

    # QR Codes & Mobile Scanner
    path('inventory/<int:pk>/qr-image/', views.inventory_qr_image, name='inventory_qr_image'),
    path('vehicles/<int:vehicle_id>/inventory/print-qr/', views.inventory_print_qr_codes, name='inventory_print_qr_codes'),
    path('scan/<str:qr_code>/', views.inventory_scan, name='inventory_scan'),
    path('inventory/<int:pk>/quick-update/', views.inventory_quick_update, name='inventory_quick_update'),
]
