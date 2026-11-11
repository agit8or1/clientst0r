"""
Process URLs
"""
from django.urls import path
from . import views

app_name = 'processes'

urlpatterns = [
    # Process CRUD
    path('', views.process_list, name='process_list'),
    path('create/', views.process_create, name='process_create'),

    # Execution list - MUST come before slug patterns
    path('executions/', views.execution_list, name='execution_list'),

    # Global processes (superuser only) - MUST come before slug patterns
    path('global/', views.global_process_list, name='global_process_list'),
    path('global/create/', views.global_process_create, name='global_process_create'),

    # Phase 38 v2: per-org runbook dashboard - MUST come before slug patterns.
    path('dashboard/', views.runbook_dashboard, name='runbook_dashboard'),
    path('dashboard/<int:org_id>/', views.runbook_dashboard, name='runbook_dashboard_org'),

    # Process detail/edit/delete - slug patterns come AFTER specific paths
    path('<slug:slug>/', views.process_detail, name='process_detail'),
    path('<slug:slug>/generate-diagram/', views.process_generate_diagram, name='process_generate_diagram'),
    path('<slug:slug>/edit/', views.process_edit, name='process_edit'),
    path('<slug:slug>/delete/', views.process_delete, name='process_delete'),
    path('<slug:slug>/reorder/', views.stage_reorder, name='stage_reorder'),
    # Phase 38: clone an is_template=True Process into a new run.
    path('<slug:slug>/clone-template/', views.process_clone_template, name='process_clone_template'),

    # Process Execution
    path('<slug:slug>/execute/', views.execution_create, name='execution_create'),
    path('execution/<int:pk>/', views.execution_detail, name='execution_detail'),
    # Phase 38: spawn a PSA Ticket from a stage in a running execution.
    path('execution/<int:execution_pk>/stage/<int:stage_pk>/spawn-ticket/',
         views.stage_spawn_ticket, name='stage_spawn_ticket'),
    path('execution/<int:pk>/audit-log/', views.execution_audit_log, name='execution_audit_log'),
    # Phase 38: read-only access removal verification for offboarding runs.
    path('execution/<int:pk>/access-verification/', views.execution_access_verification,
         name='execution_access_verification'),
    path('execution/<int:pk>/delete/', views.execution_delete, name='execution_delete'),
    path('completion/<int:pk>/complete/', views.stage_complete, name='stage_complete'),
    path('completion/<int:pk>/uncomplete/', views.stage_uncomplete, name='stage_uncomplete'),
]
