"""
URL Configuration for Reports and Analytics
"""
from django.urls import path

from core.feature_gates import gate_patterns

from . import views

app_name = 'reports'

urlpatterns = [
    # Dashboard and Analytics
    path('', views.reports_home, name='home'),
    path('dashboards/', views.dashboard_list, name='dashboard_list'),
    path('dashboards/<int:pk>/', views.dashboard_detail, name='dashboard_detail'),
    path('dashboards/create/', views.dashboard_create, name='dashboard_create'),
    path('dashboards/<int:pk>/edit/', views.dashboard_edit, name='dashboard_edit'),
    path('dashboards/<int:pk>/delete/', views.dashboard_delete, name='dashboard_delete'),

    # Dashboard widgets (v3.17.142)
    path('dashboards/<int:dashboard_pk>/widgets/add/',
         views.dashboard_widget_add, name='dashboard_widget_add'),
    path('widgets/<int:pk>/edit/',
         views.dashboard_widget_edit, name='dashboard_widget_edit'),
    path('widgets/<int:pk>/delete/',
         views.dashboard_widget_delete, name='dashboard_widget_delete'),

    # Report Templates
    path('templates/', views.template_list, name='template_list'),
    path('templates/<int:pk>/', views.template_detail, name='template_detail'),
    path('templates/create/', views.template_create, name='template_create'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('templates/<int:pk>/generate/', views.generate_report, name='generate_report'),

    # Generated Reports
    path('generated/', views.generated_list, name='generated_list'),
    path('generated/<int:pk>/', views.generated_detail, name='generated_detail'),
    path('generated/<int:pk>/download/', views.generated_download, name='generated_download'),
    path('generated/<int:pk>/delete/', views.generated_delete, name='generated_delete'),

    # Scheduled Reports
    path('scheduled/', views.scheduled_list, name='scheduled_list'),
    path('scheduled/create/', views.scheduled_create, name='scheduled_create'),
    path('scheduled/<int:pk>/edit/', views.scheduled_edit, name='scheduled_edit'),
    path('scheduled/<int:pk>/delete/', views.scheduled_delete, name='scheduled_delete'),
    path('scheduled/<int:pk>/toggle/', views.scheduled_toggle, name='scheduled_toggle'),

    # Analytics
    path('analytics/', views.analytics_overview, name='analytics_overview'),
    path('analytics/events/', views.analytics_events, name='analytics_events'),

    # PSA reports (Workstream 6)
    path('psa/', views.psa_reports_list, name='psa_reports_list'),
    # Phase 3.1 — canonical profitability report. Must come BEFORE the
    # catch-all `<str:report_type>/` so the literal slug routes here.
    path('psa/profitability-by-client/', views.psa_profitability_by_client,
         name='psa_profitability_by_client'),
    # Phase 3.2 — Profitability pivots (tech / contract / project)
    path('psa/profitability-by-tech/', views.psa_profitability_by_tech,
         name='psa_profitability_by_tech'),
    path('psa/profitability-by-contract/', views.psa_profitability_by_contract,
         name='psa_profitability_by_contract'),
    path('psa/profitability-by-project/', views.psa_profitability_by_project,
         name='psa_profitability_by_project'),
    # Phase 3.3 — Effective hourly rate + Revenue leakage
    path('psa/effective-hourly-rate/', views.psa_effective_hourly_rate,
         name='psa_effective_hourly_rate'),
    path('psa/revenue-leakage/', views.psa_revenue_leakage,
         name='psa_revenue_leakage'),
    # Phase 3.4 — SLA trends + Margin analytics by service line
    path('psa/sla-trends/', views.psa_sla_trends, name='psa_sla_trends'),
    path('psa/margin-analytics/', views.psa_margin_analytics,
         name='psa_margin_analytics'),
    # Phase 3.6 wave A — Wallboard + Executive scorecard
    path('wallboard/', views.wallboard, name='wallboard'),
    path('wallboard/data/', views.wallboard_data, name='wallboard_data'),
    path('exec-scorecard/', views.exec_scorecard, name='exec_scorecard'),
    # Phase 3.6 wave B — Client-health score (v3.17.147)
    path('psa/client-health/', views.psa_client_health, name='psa_client_health'),
    # Phase 5.2 — CRM sales funnel
    path('crm/sales-funnel/', views.crm_sales_funnel, name='crm_sales_funnel'),
    # Phase 9.4 — Security alert MTTA
    path('security/mtta/', views.security_alert_mtta_report,
         name='security_alert_mtta'),
    # v3.17.211 — Configurable wallboards (multi-named, draggable widgets,
    # rotation mode for NOC TVs). Distinct from the v3.17.146 fixed-tile
    # `/wallboard/` (singular) — these are at `/wallboards/` (plural).
    path('wallboards/', views.wallboard_list, name='wallboard_list'),
    path('wallboards/new/', views.wallboard_form, name='wallboard_create'),
    path('wallboards/<int:pk>/', views.wallboard_view, name='wallboard_view'),
    path('wallboards/<int:pk>/edit/', views.wallboard_form, name='wallboard_edit'),
    path('wallboards/<int:pk>/rotate/', views.wallboard_rotate,
         name='wallboard_rotate'),
    # v3.17.215 — drag-to-reorder. POST { order: [pk1, pk2, ...] } as JSON.
    path('wallboards/<int:pk>/widgets/reorder/',
         views.wallboard_widget_reorder, name='wallboard_widget_reorder'),
    # v3.17.217 — per-widget category re-fetch. GET ?category=<value>.
    path('wallboards/widgets/<int:pk>/data/',
         views.wallboard_widget_data, name='wallboard_widget_data'),
    # v3.17.220 — in-form widget add/delete (no Django admin trip).
    path('wallboards/<int:pk>/widgets/add/',
         views.wallboard_widget_add, name='wallboard_widget_add'),
    path('wallboards/widgets/<int:pk>/delete/',
         views.wallboard_widget_delete, name='wallboard_widget_delete'),
    # v3.17.225 — Phase 36 Agreement Reconciliation
    path('agreement-reconciliation/',
         views.agreement_reconciliation, name='agreement_reconciliation'),
    # v3.17.248 — Phase 36 v3 included-vs-billable drill-down per contract.
    path('agreement-reconciliation/<int:pk>/',
         views.agreement_reconciliation_detail,
         name='agreement_reconciliation_detail'),
    # v3.17.255 — Phase 27 v1 accounting reconciliation.
    path('accounting-reconciliation/',
         views.accounting_reconciliation, name='accounting_reconciliation'),
    # v3.17.269 — Phase 27 v5 AR aging tied to QBO.
    path('ar-aging/',
         views.ar_aging_report, name='ar_aging_report'),
    # v3.17.281 — Phase 27 v9 bank deposit reconciliation.
    path('bank-reconciliation/',
         views.bank_reconciliation_report, name='bank_reconciliation_report'),
    path('bank-reconciliation/mark/',
         views.bank_reconciliation_mark, name='bank_reconciliation_mark'),
    # v3.17.295 — Phase 15 v6/v9 billing reconciliation + MRR forecasting
    path('billing-reconciliation/',
         views.billing_reconciliation_report,
         name='billing_reconciliation_report'),
    path('mrr-forecast/',
         views.mrr_forecast_report, name='mrr_forecast_report'),
    # v3.17.305 — Phase 17 v3 software compliance report
    path('software-compliance/',
         views.software_compliance_report,
         name='software_compliance_report'),
    # v3.17.283 — Phase 18 v8/v9/v10 multi-location report.
    path('multi-location/',
         views.multi_location_report, name='multi_location_report'),
    # v3.17.257 — Phase 19 v1 ticket aging analytics.
    path('ticket-aging/',
         views.ticket_aging_report, name='ticket_aging_report'),
    # v3.17.320 — Phase 19 v2 SLA forecasting (predict breach risk).
    path('sla-forecast/',
         views.sla_forecast_report, name='sla_forecast_report'),
    # v3.17.321 — Phase 19 v3 quote conversion tracking.
    path('quote-conversion/',
         views.quote_conversion_report, name='quote_conversion_report'),
    # v3.17.322 — Phase 19 v4 KPI dashboard (composable widget grid).
    path('kpi/',
         views.kpi_dashboard, name='kpi_dashboard'),
    # v3.17.323 — Phase 19 v5 operational metrics (MTTR / FTR / queue depth).
    path('operational-metrics/',
         views.operational_metrics_report, name='operational_metrics_report'),
    # v3.17.324 — Phase 19 v6 workflow performance analytics.
    path('workflow-performance/',
         views.workflow_performance_report, name='workflow_performance_report'),
    # v3.17.325 — Phase 19 v7 trends + capacity forecasting.
    path('trends/',
         views.trends_report, name='trends_report'),
    # v3.17.258 — Phase 13 v3 procurement summary report.
    path('procurement-summary/',
         views.procurement_summary, name='procurement_summary'),
    # v3.17.262 — Phase 13 v5 vendor cost history report.
    path('vendor-cost-history/',
         views.vendor_cost_history, name='vendor_cost_history'),
    # v3.17.263 — Phase 13 v6 asset lifecycle scoring report.
    path('asset-lifecycle/',
         views.asset_lifecycle_report, name='asset_lifecycle_report'),
    # v3.17.268 — Phase 13 v8 procurement forecasting report.
    path('procurement-forecasting/',
         views.procurement_forecasting, name='procurement_forecasting'),
    # v3.17.271 — Phase 13 v9 hardware-resale margin analytics.
    path('hardware-margin/',
         views.hardware_margin_report, name='hardware_margin_report'),
    # Phase 26 v1 (v3.17.246) — Saved Queries / Custom Report Writer.
    path('saved-queries/', views.saved_query_list, name='saved_query_list'),
    path('saved-queries/new/', views.saved_query_form, name='saved_query_create'),
    path('saved-queries/<int:pk>/edit/', views.saved_query_form, name='saved_query_edit'),
    path('saved-queries/<int:pk>/run/', views.saved_query_run, name='saved_query_run'),
    path('saved-queries/<int:pk>/delete/', views.saved_query_delete, name='saved_query_delete'),
    path('psa/<str:report_type>/', views.psa_report_run, name='psa_report_run'),
]

# Settings → Features → Reports & Analytics: every route 404s while it is off.
urlpatterns = gate_patterns(urlpatterns, 'reports_enabled')
