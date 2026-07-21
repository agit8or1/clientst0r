"""
Docs URL configuration
"""
from django.urls import path
from . import views

app_name = 'docs'

urlpatterns = [
    path('', views.document_list, name='document_list'),
    path('create/', views.document_create, name='document_create'),
    path('upload/', views.document_upload, name='document_upload'),
    # Issue #140 — import DOCX/PDF/TXT/MD as editable docs + optional AI review.
    path('import/', views.document_import, name='document_import'),
    path('ai/review-import/', views.ai_review_import, name='ai_review_import'),
    # Phase 22 v1 (v3.17.245) — review queue + mark-reviewed.
    path('review-queue/', views.kb_review_queue, name='kb_review_queue'),
    path('<slug:slug>/mark-reviewed/', views.kb_mark_reviewed, name='kb_mark_reviewed'),
    # Phase 22 v2 (v3.17.250) — editorial approval queue.
    path('approval-queue/', views.kb_approval_queue, name='kb_approval_queue'),
    path('<slug:slug>/approve/', views.kb_approve, name='kb_approve'),
    path('<slug:slug>/reject/', views.kb_reject, name='kb_reject'),
    path('<slug:slug>/submit-for-review/', views.kb_submit_for_review, name='kb_submit_for_review'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/create/', views.template_create, name='template_create'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('kb/', views.global_kb_list, name='global_kb_list'),
    path('kb/create/', views.global_kb_create, name='global_kb_create'),
    path('kb/<slug:slug>/', views.global_kb_detail, name='global_kb_detail'),
    path('kb/<slug:slug>/edit/', views.global_kb_edit, name='global_kb_edit'),
    path('kb/<slug:slug>/delete/', views.global_kb_delete, name='global_kb_delete'),

    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Diagrams
    path('diagrams/', views.diagram_list, name='diagram_list'),
    path('diagrams/create/', views.diagram_create, name='diagram_create'),
    path('diagrams/templates/', views.diagram_template_list, name='diagram_template_list'),
    path('diagrams/templates/create/', views.diagram_template_create, name='diagram_template_create'),
    path('diagrams/templates/<int:pk>/edit/', views.diagram_template_edit, name='diagram_template_edit'),
    path('diagrams/templates/<int:pk>/delete/', views.diagram_template_delete, name='diagram_template_delete'),
    path('diagrams/<slug:slug>/', views.diagram_detail, name='diagram_detail'),
    path('diagrams/<slug:slug>/edit/', views.diagram_edit, name='diagram_edit'),
    path('diagrams/<slug:slug>/delete/', views.diagram_delete, name='diagram_delete'),
    path('diagrams/<int:pk>/save/', views.diagram_save, name='diagram_save'),

    # API Endpoints
    path('api/template/<int:template_id>/', views.api_get_template, name='api_get_template'),

    # AI Documentation Features
    path('ai/assistant/', views.ai_assistant, name='ai_assistant'),
    path('ai/generate/', views.ai_generate, name='ai_generate'),
    path('ai/enhance/', views.ai_enhance, name='ai_enhance'),
    path('ai/validate/', views.ai_validate, name='ai_validate'),

    # Documents (must be last due to slug catch-all)
    path('<slug:slug>/', views.document_detail, name='document_detail'),
    path('<slug:slug>/edit/', views.document_edit, name='document_edit'),
    path('<slug:slug>/delete/', views.document_delete, name='document_delete'),
]
