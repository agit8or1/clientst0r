"""Customer portal URLs — kept off the main staff /psa/ path for clarity."""
from django.urls import path

from . import views

app_name = 'portal'

# Phase 40.5 (v3.17.543) — the client-facing status page. The view lives in
# `statuspage` with the models it reads; `portal_required` is applied here so
# it inherits the portal's rules rather than reimplementing them.
from statuspage.views import portal_status as _status_view  # noqa: E402

urlpatterns = [
    path('', views.ticket_list, name='ticket_list'),
    path('status/', views.portal_required(_status_view), name='status'),
    # v3.17.232 — Phase 12 portal announcements (per-session dismissal).
    path('announcement/<int:pk>/dismiss/',
         views.announcement_dismiss, name='announcement_dismiss'),
    path('new/', views.ticket_create, name='ticket_create'),
    path('t/<str:ticket_number>/', views.ticket_detail, name='ticket_detail'),
    path('t/<str:ticket_number>/reply/', views.post_reply, name='post_reply'),
    # v3.17.235 — Phase 12: portal user "I care about this too" vote.
    path('t/<str:ticket_number>/vote/', views.ticket_vote, name='ticket_vote'),
    # v3.17.236 — Phase 12: portal user escalation.
    path('t/<str:ticket_number>/escalate/', views.ticket_escalate, name='ticket_escalate'),
    # Customer-facing quote signing — public, opaque token, no login required.
    path('quote/<str:token>/sign/', views.quote_sign, name='quote_sign'),
    # Knowledge base for portal users
    path('kb/', views.kb_list, name='kb_list'),
    path('kb/<slug:slug>/', views.kb_detail, name='kb_detail'),
    # Vault access for portal users
    path('vault/', views.vault_list, name='vault_list'),
    path('vault/<int:pk>/reveal/', views.vault_reveal, name='vault_reveal'),
    # Org admin — manage which users in this org see which org-admin-managed items
    path('vault/admin/', views.org_admin_vault, name='org_admin_vault'),
    path('vault/admin/<int:pk>/', views.org_admin_vault_item, name='org_admin_vault_item'),
    # v3.17.233 — portal user notification preferences.
    path('preferences/', views.preferences, name='preferences'),
    # v3.17.239 — Phase 12 customer approval workflows.
    path('approvals/', views.approvals_list, name='approvals_list'),
    path('approvals/<int:pk>/decide/', views.approval_decide, name='approval_decide'),
]
