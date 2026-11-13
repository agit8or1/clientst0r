"""Staff URLs for contract documents (/contracts/, MSP staff only)."""
from django.urls import path

from . import views

app_name = 'contracts'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('new/', views.contract_new, name='new'),
    path('notifications/read/', views.notifications_read, name='notifications_read'),
    path('<int:pk>/', views.contract_detail, name='detail'),
    path('<int:pk>/edit/', views.contract_edit, name='edit'),
    path('<int:pk>/autosave/', views.contract_autosave, name='autosave'),
    path('<int:pk>/preview/', views.contract_preview, name='preview'),
    path('<int:pk>/preview.pdf', views.contract_preview_pdf, name='preview_pdf'),
    path('<int:pk>/submit/', views.contract_submit, name='submit'),
    path('<int:pk>/approve/', views.contract_approve, name='approve'),
    path('<int:pk>/send/', views.contract_send, name='send'),
    path('<int:pk>/revise/', views.contract_revise, name='revise'),
    path('<int:pk>/void/', views.contract_void, name='void'),
    path('<int:pk>/delete/', views.contract_delete, name='delete'),
    path('<int:pk>/billing/', views.contract_billing, name='billing'),
    path('<int:pk>/attachments/', views.attachment_upload, name='attachment_upload'),
    path('<int:pk>/<str:how>/', views.contract_derive, name='derive'),
    path('attachments/<int:pk>/', views.attachment_download, name='attachment_download'),
    path('attachments/<int:pk>/remove/', views.attachment_remove, name='attachment_remove'),
    path('versions/<int:pk>/pdf/<str:kind>/', views.version_pdf, name='version_pdf'),
    path('versions/<int:pk>/snapshot/', views.version_snapshot, name='version_snapshot'),
    path('versions/<int:pk>/evidence/', views.version_evidence, name='version_evidence'),
    path('invitations/<int:pk>/resend/', views.invitation_resend, name='invitation_resend'),
    path('invitations/<int:pk>/link/', views.invitation_link, name='invitation_link'),
    path('invitations/<int:pk>/revoke/', views.invitation_revoke, name='invitation_revoke'),
    path('invitations/<int:pk>/replace/', views.invitation_replace, name='invitation_replace'),
    path('invitations/<int:pk>/countersign/', views.invitation_countersign, name='invitation_countersign'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/new/', views.template_edit, name='template_new'),
    path('templates/<int:pk>/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/versions/<int:number>/', views.template_version, name='template_version'),
    path('templates/<int:pk>/clone/', views.template_clone, name='template_clone'),
    path('templates/<int:pk>/toggle/', views.template_toggle, name='template_toggle'),
    path('clauses/', views.clause_list, name='clause_list'),
    path('clauses/new/', views.clause_edit, name='clause_new'),
    path('clauses/<int:pk>/', views.clause_edit, name='clause_edit'),
    path('settings/', views.settings_view, name='settings'),
]
