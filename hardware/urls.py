from django.urls import path

from . import views as V
from . import views_catalog as K
from . import views_tools as T

app_name = 'hardware'

urlpatterns = [
    # Client inventory
    path('', V.device_list, name='device_list'),
    path('search/', V.search, name='search'),
    path('devices/add/', V.device_add, name='device_add'),
    path('devices/<int:pk>/', V.device_detail, name='device_detail'),
    path('devices/<int:pk>/edit/', V.device_edit, name='device_edit'),
    path('devices/<int:pk>/clone/', V.device_clone, name='device_clone'),
    path('devices/<int:pk>/delete/', V.device_delete, name='device_delete'),
    path('devices/<int:pk>/template-update/', V.template_update, name='template_update'),
    path('devices/<int:pk>/modules/install/', V.module_install, name='module_install'),
    path('devices/<int:pk>/ports/add/', V.port_add, name='port_add'),
    path('devices/<int:pk>/art/<str:face>.svg', V.device_art, name='device_art'),
    path('devices/<int:pk>/patch-panel/', V.patch_panel_view, name='patch_panel'),
    path('modules/<int:pk>/remove/', V.module_remove, name='module_remove'),
    path('ports/<int:pk>/trace/', V.trace_page, name='trace_page'),
    path('cables/', V.cable_list, name='cable_list'),
    path('cables/<int:pk>/', V.cable_detail, name='cable_detail'),
    path('vlans/', V.vlan_list, name='vlan_list'),
    path('request-model/', V.model_request, name='model_request'),
    path('q/<str:kind>/<uuid:uid>/', V.qr_resolve, name='qr'),

    # Racks & diagrams
    path('racks/<int:pk>/', T.rack_view, name='rack'),
    path('racks/<int:pk>/<str:face>.<str:fmt>', T.rack_export, name='rack_export'),
    path('diagrams/<str:kind>/', T.diagram, name='diagram'),
    path('diagrams/<str:kind>/export/', T.diagram_export, name='diagram_export'),

    # Labels
    path('labels/', T.labels, name='labels'),
    path('labels/pdf/', T.labels_pdf, name='labels_pdf'),
    path('labels/templates/save/', T.label_template_save, name='label_template_save'),

    # CSV
    path('import/', T.import_csv, name='import_csv'),
    path('export/<str:what>.csv', T.export_csv, name='export_csv'),

    # Catalog (global)
    path('catalog/', K.catalog, name='catalog'),
    path('catalog/coverage/', K.coverage, name='coverage'),
    path('catalog/imports/', K.import_jobs, name='import_jobs'),
    path('catalog/imports/<int:pk>/', K.import_job_detail, name='import_job'),
    path('catalog/requests/', K.model_requests, name='model_requests'),
    path('catalog/models/add/', K.model_add, name='model_add'),
    path('catalog/models/<int:pk>/', K.model_detail, name='model_detail'),
    path('catalog/models/<int:pk>/edit/', K.model_edit, name='model_edit'),
    path('catalog/models/<int:pk>/layout/', K.layout_editor, name='layout_editor'),
    path('catalog/models/<int:pk>/layout/preview/', K.layout_preview, name='layout_preview'),
    path('catalog/models/<int:pk>/art/<str:face>.svg', K.model_art, name='model_art'),

    # Session JSON API
    path('api/models/', V.api_models, name='api_models'),
    path('api/devices/<int:pk>/ports/', V.api_device_ports, name='api_device_ports'),
    path('api/ports/<int:pk>/', V.api_port, name='api_port'),
    path('api/ports/bulk/', V.api_ports_bulk, name='api_ports_bulk'),
    path('api/ports/search/', V.api_port_search, name='api_port_search'),
    path('api/ports/<int:pk>/trace/', V.api_trace, name='api_trace'),
    path('api/cables/', V.api_connect, name='api_connect'),
    path('api/cables/<int:pk>/delete/', V.api_disconnect, name='api_disconnect'),
    path('api/patch-assign/', V.api_patch_assign, name='api_patch_assign'),
    path('api/diagrams/<str:kind>/', T.api_diagram, name='api_diagram'),
]
