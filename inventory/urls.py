from django.urls import path
from . import views
from .access import msp_staff_only

app_name = 'inventory'

# Every inventory page is MSP-staff only (inventory/access.py).

urlpatterns = [
    path('', msp_staff_only(views.inventory_dashboard), name='inventory_dashboard'),
    path('items/', msp_staff_only(views.item_list), name='item_list'),
    path('items/create/', msp_staff_only(views.item_create), name='item_create'),
    path('items/<int:pk>/', msp_staff_only(views.item_detail), name='item_detail'),
    path('items/<int:pk>/edit/', msp_staff_only(views.item_edit), name='item_edit'),
    path('items/<int:pk>/delete/', msp_staff_only(views.item_delete), name='item_delete'),
    path('items/<int:pk>/adjust/', msp_staff_only(views.item_adjust), name='item_adjust'),
    path('items/scan/<str:qr_code>/', msp_staff_only(views.item_scan), name='item_scan'),
    path('categories/', msp_staff_only(views.category_list), name='category_list'),
    path('categories/create/', msp_staff_only(views.category_create), name='category_create'),
    path('categories/<int:pk>/edit/', msp_staff_only(views.category_edit), name='category_edit'),
    path('categories/<int:pk>/delete/', msp_staff_only(views.category_delete), name='category_delete'),
    path('locations/', msp_staff_only(views.location_list), name='location_list'),
    path('locations/create/', msp_staff_only(views.location_create), name='location_create'),
    path('locations/<int:pk>/edit/', msp_staff_only(views.location_edit), name='location_edit'),
    path('locations/<int:pk>/delete/', msp_staff_only(views.location_delete), name='location_delete'),
    # Phase 46 (v3.17.533) — tools are durable, unlike stock.
    path('tools/', msp_staff_only(views.tool_list), name='tool_list'),
    path('tools/create/', msp_staff_only(views.tool_create), name='tool_create'),
    path('tools/<int:pk>/edit/', msp_staff_only(views.tool_edit), name='tool_edit'),
    path('tools/<int:pk>/delete/', msp_staff_only(views.tool_delete), name='tool_delete'),
    path('transactions/', msp_staff_only(views.transaction_list), name='transaction_list'),
    path('low-stock/', msp_staff_only(views.low_stock_report), name='low_stock_report'),
]
