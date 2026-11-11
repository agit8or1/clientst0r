from django.urls import path

from . import assist_views, profile_views, troubleshoot_views, views

app_name = 'psa_ai'

urlpatterns = [
    path('inbox/', views.ai_inbox, name='inbox'),
    path('generate-reply/<str:ticket_number>/', views.generate_reply, name='generate_reply'),
    path('generate-actions/<str:ticket_number>/', views.generate_actions, name='generate_actions'),
    path('triage/<str:ticket_number>/', views.generate_triage, name='generate_triage'),
    path('suggestion/<int:pk>/', views.suggestion_detail, name='suggestion_detail'),
    path('suggestion/<int:pk>/reject/', views.suggestion_reject, name='suggestion_reject'),
    path('suggestion/<int:pk>/triage-feedback/', views.triage_feedback, name='triage_feedback'),
    path('suggestion/<int:pk>/request-approval/', views.suggestion_request_approval, name='suggestion_request_approval'),
    path('suggestion/<int:pk>/apply/', views.suggestion_approve_and_apply, name='suggestion_apply'),
    # Ticket AI Assist (v3.17.646): preview → submit → status.
    path('assist/<str:ticket_number>/preview/', assist_views.preview, name='assist_preview'),
    path('assist/<str:ticket_number>/submit/', assist_views.submit, name='assist_submit'),
    path('assist/<str:ticket_number>/history/', assist_views.ticket_history, name='assist_history'),
    path('assist/job/<uuid:job_id>/', assist_views.job_status, name='assist_job'),
    # AI Troubleshoot (OPTIONAL AI): tickets and devices.
    path('troubleshoot/ticket/<str:ticket_number>/', troubleshoot_views.start_ticket,
         name='troubleshoot_ticket'),
    path('troubleshoot/device/<int:device_id>/', troubleshoot_views.start_device, name='troubleshoot_device'),
    path('troubleshoot/<uuid:session_id>/', troubleshoot_views.session_detail, name='troubleshoot_session'),
    path('troubleshoot/<uuid:session_id>/action/<str:ref>/', troubleshoot_views.request_action,
         name='troubleshoot_action'),
    path('profiles/', profile_views.profiles, name='profiles'),
    path('profiles/policy/<int:org_id>/', profile_views.policy, name='policy'),
    path('my-keys/', profile_views.own_keys, name='own_keys'),
]
