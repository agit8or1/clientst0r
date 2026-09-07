"""
Mobile API URL config — `/api/mobile/v1/`.
"""
from django.urls import path

from . import (
    views_assets,
    views_auth,
    views_dashboard,
    views_dispatch,
    views_field_ops,
    views_inventory,
    views_kb,
    views_netconfig,
    views_notifications,
    views_ocr,
    views_projects,
    views_receipts,
    views_scan,
    views_tickets,
    views_users,
    views_vault,
    views_vehicles,
    views_version,
    views_workflows,
)

app_name = 'api_mobile'


urlpatterns = [
    # Version probe (v3.17.472) — anonymous, mobile compares app vs server
    path('version/', views_version.version_view, name='version'),

    # Auth (v3.17.346)
    path('auth/login/', views_auth.login_view, name='login'),
    path('auth/mfa/', views_auth.mfa_view, name='mfa'),
    path('auth/logout/', views_auth.logout_view, name='logout'),
    path('auth/me/', views_auth.me_view, name='me'),
    path('auth/refresh/', views_auth.refresh_view, name='refresh'),

    # Projects (v3.17.558) — Phase 35's field-relevant slice.
    path('projects/', views_projects.project_list_view, name='project_list'),
    path('projects/<int:pk>/', views_projects.project_detail_view,
         name='project_detail'),
    path('project-tasks/<int:pk>/', views_projects.project_task_view,
         name='project_task'),

    # Network device configs (v3.17.558) — Phase 34's field-relevant slice.
    path('netconfig/devices/', views_netconfig.device_list_view,
         name='netconfig_devices'),
    path('netconfig/devices/<int:pk>/', views_netconfig.device_detail_view,
         name='netconfig_device_detail'),
    path('netconfig/devices/<int:pk>/collect/', views_netconfig.collect_view,
         name='netconfig_collect'),
    path('netconfig/backups/<int:pk>/', views_netconfig.backup_detail_view,
         name='netconfig_backup'),

    # Dashboard + organizations (v3.17.347)
    path('dashboard/', views_dashboard.dashboard_view, name='dashboard'),
    path('organizations/', views_dashboard.organization_list_view, name='org_list'),
    path('organizations/<int:pk>/', views_dashboard.organization_detail_view, name='org_detail'),

    # Assets (v3.17.348; PATCH + vault link/unlink v3.17.480)
    path('assets/', views_assets.asset_list_view, name='asset_list'),
    path('assets/<int:pk>/', views_assets.asset_detail_view, name='asset_detail'),
    path('assets/<int:pk>/vault-links/',
         views_assets.asset_vault_link_view, name='asset_vault_link'),

    # Tickets (v3.17.349)
    path('tickets/', views_tickets.ticket_list_view, name='ticket_list'),
    path('tickets/<int:pk>/', views_tickets.ticket_detail_view, name='ticket_detail'),
    path('tickets/<int:pk>/comments/', views_tickets.ticket_comment_view, name='ticket_comment'),
    path('tickets/<int:pk>/time/', views_tickets.ticket_time_view, name='ticket_time'),

    # Users — assignable picker for ticket re-assignment (v3.17.477)
    path('users/assignable/', views_users.assignable_users_view, name='users_assignable'),

    # KB / docs (v3.17.350)
    path('kb/', views_kb.kb_list_view, name='kb_list'),
    path('kb/<int:pk>/', views_kb.kb_detail_view, name='kb_detail'),

    # Vault (v3.17.449)
    path('vault/', views_vault.vault_list_view, name='vault_list'),
    path('vault/<int:pk>/', views_vault.vault_detail_view, name='vault_detail'),
    path('vault/<int:pk>/reveal/', views_vault.vault_reveal_view, name='vault_reveal'),

    # Receipt OCR (v3.17.465–467) — 503 unless OCR_PROVIDER env is set
    path('ocr/receipt/', views_ocr.ocr_receipt_view, name='ocr_receipt'),
    path('ocr/status/', views_ocr.ocr_status_view, name='ocr_status'),

    # Receipt upload (v3.17.470) — image goes to Attachment, OCR populates
    # VehicleReceipt, auto-creates FuelLog / MaintenanceRecord by category.
    path('receipts/', views_receipts.receipt_list_view, name='receipts'),
    path('receipts/<int:pk>/', views_receipts.receipt_detail_view, name='receipt_detail'),

    # Push notifications (v3.17.463)
    path('notifications/register/', views_notifications.register_push_view, name='push_register'),
    path('notifications/deregister/', views_notifications.deregister_push_view, name='push_deregister'),

    # Code scan resolver (v3.17.461)
    path('scan/', views_scan.scan_resolve_view, name='scan_resolve'),

    # Inventory (v3.17.458)
    path('inventory/', views_inventory.inventory_list_view, name='inventory_list'),
    path('inventory/<int:pk>/', views_inventory.inventory_detail_view, name='inventory_detail'),
    path('inventory/<int:pk>/transactions/',
         views_inventory.inventory_transactions_view, name='inventory_transactions'),

    # Dispatch board + scheduled tasks (v3.17.457)
    path('dispatch/', views_dispatch.dispatch_board_view, name='dispatch_board'),
    path('dispatch/calendar/', views_dispatch.dispatch_calendar_view, name='dispatch_calendar'),
    # 7-day agenda strip for the mobile dashboard (v3.17.478)
    path('dispatch/upcoming/', views_dispatch.dispatch_upcoming_view, name='dispatch_upcoming'),
    # Schedule-on-calendar — create a ScheduledTask from the mobile app (v3.17.479)
    path('dispatch/tasks/', views_dispatch.create_scheduled_task_view, name='dispatch_create_task'),
    path('dispatch/assignments/<int:pk>/ack/',
         views_dispatch.task_acknowledge_view, name='task_acknowledge'),
    path('dispatch/tasks/<int:pk>/comments/',
         views_dispatch.task_comment_view, name='task_comment'),

    # Vehicles + fuel + damage (v3.17.456)
    path('vehicles/', views_vehicles.my_vehicles_view, name='vehicle_list'),
    path('vehicles/<int:pk>/', views_vehicles.vehicle_detail_view, name='vehicle_detail'),
    path('vehicles/<int:pk>/inventory/', views_vehicles.vehicle_inventory_view, name='vehicle_inventory'),
    path('vehicles/<int:pk>/fuel/', views_vehicles.vehicle_fuel_view, name='vehicle_fuel'),
    path('vehicles/<int:pk>/damage/', views_vehicles.vehicle_damage_view, name='vehicle_damage'),

    # Workflows / processes (v3.17.455)
    path('workflows/', views_workflows.workflow_list_view, name='workflow_list'),
    path('workflows/<int:pk>/', views_workflows.workflow_detail_view, name='workflow_detail'),
    path('workflows/<int:pk>/start/', views_workflows.workflow_start_view, name='workflow_start'),
    path('workflows/executions/', views_workflows.my_executions_view, name='execution_list'),
    path('workflows/executions/<int:pk>/', views_workflows.execution_detail_view, name='execution_detail'),
    path('workflows/executions/<int:pk>/stages/<int:stage_id>/complete/',
         views_workflows.execution_complete_stage_view, name='execution_stage_complete'),

    # Field Ops — Phase 8 (v3.17.410)
    path('locations/', views_field_ops.location_ping_view, name='location_ping'),
    path('timeclock/clock-in/', views_field_ops.clock_in_view, name='clock_in'),
    path('timeclock/clock-out/', views_field_ops.clock_out_view, name='clock_out'),
    path('timeclock/me/', views_field_ops.timeclock_me_view, name='timeclock_me'),
    path('active-ticket/', views_field_ops.active_ticket_view, name='active_ticket'),
]
