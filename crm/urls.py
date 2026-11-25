from django.urls import path
from . import views

app_name = 'crm'

urlpatterns = [
    path('', views.crm_home, name='home'),

    # Leads
    path('leads/', views.lead_list, name='lead_list'),
    path('leads/new/', views.lead_form, name='lead_create'),
    path('leads/<int:pk>/', views.lead_detail, name='lead_detail'),
    path('leads/<int:pk>/edit/', views.lead_form, name='lead_edit'),
    path('leads/<int:pk>/convert/', views.lead_convert, name='lead_convert'),
    path('leads/<int:pk>/disqualify/', views.lead_disqualify, name='lead_disqualify'),

    # Pipeline (Kanban)
    path('pipeline/', views.pipeline_kanban, name='pipeline'),
    path('opportunities/', views.opportunity_list, name='opportunity_list'),
    path('opportunities/new/', views.opportunity_form, name='opportunity_create'),
    path('opportunities/<int:pk>/', views.opportunity_detail, name='opportunity_detail'),
    path('opportunities/<int:pk>/edit/', views.opportunity_form, name='opportunity_edit'),
    path('opportunities/<int:pk>/stage/', views.opportunity_set_stage, name='opportunity_set_stage'),
    path('opportunities/<int:pk>/to-quote/', views.opportunity_to_quote, name='opportunity_to_quote'),

    # Campaigns
    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/new/', views.campaign_form, name='campaign_create'),
    path('campaigns/<int:pk>/', views.campaign_detail, name='campaign_detail'),
    path('campaigns/<int:pk>/edit/', views.campaign_form, name='campaign_edit'),

    # Phase 5.2 — Commissions + Commission Rules
    path('commissions/', views.commission_list, name='commission_list'),
    path('commissions/<int:pk>/decide/', views.commission_decide, name='commission_decide'),
    path('commission-rules/', views.commission_rule_list, name='commission_rule_list'),
    path('commission-rules/new/', views.commission_rule_form, name='commission_rule_create'),
    path('commission-rules/<int:pk>/edit/', views.commission_rule_form, name='commission_rule_edit'),

    # Phase 5.3 — Sales-activity timeline + lead capture
    path('activities/<str:scope>/<int:pk>/add/', views.activity_add, name='activity_add'),
    path('leads/capture/', views.lead_capture_web, name='lead_capture_web'),
    path('api/leads/capture/', views.lead_capture_api, name='lead_capture_api'),
]

# Settings → Modules: every route 404s while the module is off
# (core/feature_gates.py).
from core.feature_gates import gate_patterns  # noqa: E402

gate_patterns(urlpatterns, 'crm_enabled')
