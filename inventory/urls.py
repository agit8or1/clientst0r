from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_dashboard, name='inventory_dashboard'),
    path('items/', views.item_list, name='item_list'),
    path('items/create/', views.item_create, name='item_create'),
    path('items/<int:pk>/', views.item_detail, name='item_detail'),
    path('items/<int:pk>/edit/', views.item_edit, name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('items/<int:pk>/adjust/', views.item_adjust, name='item_adjust'),
    path('items/scan/<str:qr_code>/', views.item_scan, name='item_scan'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('locations/', views.location_list, name='location_list'),
    path('locations/create/', views.location_create, name='location_create'),
    path('locations/<int:pk>/edit/', views.location_edit, name='location_edit'),
    path('locations/<int:pk>/delete/', views.location_delete, name='location_delete'),
    # Phase 46 (v3.17.533) — tools are durable, unlike stock.
    path('tools/', views.tool_list, name='tool_list'),
    path('tools/create/', views.tool_create, name='tool_create'),
    path('tools/<int:pk>/edit/', views.tool_edit, name='tool_edit'),
    path('tools/<int:pk>/delete/', views.tool_delete, name='tool_delete'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('low-stock/', views.low_stock_report, name='low_stock_report'),
]
