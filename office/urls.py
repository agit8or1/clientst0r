"""Office URLs.

/office/f/<code>/<pk>/...   file actions (code: doc / att / tkt / ofi)
/office/edit/<session>/      full-screen editor page and its JSON helpers
/office/settings/...         superuser configuration (Settings → Integrations)
/office/organization/        organization admin policy
/office/api/...              RESERVED for provider endpoints (ONLYOFFICE
                             callbacks, WOPI). They authenticate with
                             office.tokens, are csrf_exempt, and are added by
                             the provider connectors in their own url modules
                             included below.
"""
from django.urls import include, path

from . import views, views_admin

app_name = 'office'

F = 'f/<str:code>/<int:pk>/'

urlpatterns = [
    path(F, views.target_detail, name='target_detail'),
    path(F + 'versions/', views.target_versions, name='target_versions'),
    path(F + 'download/', views.download, name='download'),
    path(F + 'revisions/<int:number>/download/', views.download, name='download_revision'),
    path(F + 'revisions/<int:number>/restore/', views.restore, name='restore'),
    path(F + 'rename/', views.rename, name='rename'),
    path(F + 'copy/', views.copy, name='copy'),
    path(F + 'open/', views.open_editor, name='open'),
    path(F + 'export/pdf/', views.export_pdf, name='export_pdf'),
    path(F + 'convert/', views.convert, name='convert'),
    path(F + 'quarantine/<int:qid>/download/', views.quarantine_download, name='quarantine_download'),
    path(F + 'quarantine/<int:qid>/restore/', views.quarantine_restore, name='quarantine_restore'),

    path('new/<str:fmt>/', views.new_document, name='new_document'),
    path('new-attachment/<str:fmt>/', views.new_attachment, name='new_attachment'),
    path('new-from-template/', views.new_from_template, name='new_from_template'),
    path('templates/', views_admin.template_list, name='template_list'),
    path('templates/<int:pk>/retire/', views_admin.template_delete, name='template_delete'),

    path('edit/<uuid:session_id>/', views.editor, name='editor'),
    path('edit/<uuid:session_id>/status/', views.editor_status, name='editor_status'),
    path('edit/<uuid:session_id>/renew/', views.editor_renew, name='editor_renew'),
    path('edit/<uuid:session_id>/close/', views.editor_close, name='editor_close'),

    path('settings/', views_admin.settings_index, name='settings'),
    path('settings/instances/new/', views_admin.instance_edit, name='instance_new'),
    path('settings/instances/<int:pk>/', views_admin.instance_edit, name='instance_edit'),
    path('settings/instances/<int:pk>/delete/', views_admin.instance_delete, name='instance_delete'),
    path('settings/instances/<int:pk>/health/', views_admin.instance_health, name='instance_health'),
    path('settings/instances/<int:pk>/diagnostics/', views_admin.instance_diagnostics,
         name='instance_diagnostics'),
    path('settings/install/', views_admin.install_page, name='install'),
    path('settings/quarantine/', views_admin.quarantine_list, name='quarantine_list'),
    path('settings/quarantine/<int:qid>/download/', views_admin.quarantine_admin_download,
         name='quarantine_admin_download'),

    path('organization/', views_admin.org_policy, name='org_policy'),

    # Provider endpoints (callbacks / WOPI) — see office/providers/*/urls.py.
    path('api/', include('office.provider_urls')),
]
