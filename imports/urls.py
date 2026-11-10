"""
URL configuration for imports app
"""
from django.urls import path
from . import rehearsal_views, views

app_name = 'imports'

urlpatterns = [
    # Import job management
    path('', views.import_list, name='import_list'),
    path('create/', views.import_create, name='import_create'),
    path('<int:pk>/', views.import_detail, name='import_detail'),
    path('<int:pk>/edit/', views.import_edit, name='import_edit'),
    path('<int:pk>/delete/', views.import_delete, name='import_delete'),
    path('<int:pk>/start/', views.import_start, name='import_start'),
    path('<int:pk>/rollback/', views.import_rollback, name='import_rollback'),
    path('<int:pk>/promote/', views.import_promote, name='import_promote'),
    path('<int:pk>/log/', views.import_log, name='import_log'),
    path('<int:pk>/map-fields/', views.import_map_fields, name='import_map_fields'),

    # One-customer migration rehearsal (IT Glue / Hudu)
    path('rehearsals/', rehearsal_views.rehearsal_list, name='rehearsal_list'),
    path('rehearsals/new/', rehearsal_views.rehearsal_create, name='rehearsal_create'),
    path('rehearsals/<int:pk>/', rehearsal_views.rehearsal_detail, name='rehearsal_detail'),
    path('rehearsals/<int:pk>/stage/', rehearsal_views.rehearsal_stage, name='rehearsal_stage'),
    path('rehearsals/<int:pk>/build/', rehearsal_views.rehearsal_build, name='rehearsal_build'),
    path('rehearsals/<int:pk>/type-mapping/', rehearsal_views.rehearsal_type_override,
         name='rehearsal_type_override'),
    path('rehearsals/<int:pk>/items/', rehearsal_views.rehearsal_items, name='rehearsal_items'),
    path('rehearsals/<int:pk>/items/<int:item_id>/', rehearsal_views.rehearsal_item, name='rehearsal_item'),
    path('rehearsals/<int:pk>/freeze/', rehearsal_views.rehearsal_freeze, name='rehearsal_freeze'),
    path('rehearsals/<int:pk>/apply/', rehearsal_views.rehearsal_apply, name='rehearsal_apply'),
    path('rehearsals/<int:pk>/rollback/', rehearsal_views.rehearsal_rollback, name='rehearsal_rollback'),
    path('rehearsals/<int:pk>/report/', rehearsal_views.rehearsal_report, name='rehearsal_report'),

    # Per-customer inventory export (metadata only)
    path('inventory/<int:org_id>/export/', rehearsal_views.inventory_export, name='inventory_export'),
]
