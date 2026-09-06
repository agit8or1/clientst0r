from django.urls import path

from . import views

app_name = 'psa'

urlpatterns = [
    path('', views.ticket_list, name='ticket_list'),
    path('new/', views.ticket_create, name='ticket_create'),
    path('settings/', views.psa_global_settings_view, name='settings'),
    # Legacy per-client URL — redirects to the new global page.
    path('settings/client/', views.client_settings_view, name='client_settings'),
    # Canned replies (Phase 2b)
    path('canned/', views.canned_reply_list, name='canned_reply_list'),
    path('canned/new/', views.canned_reply_create, name='canned_reply_create'),
    path('canned/<int:pk>/edit/', views.canned_reply_edit, name='canned_reply_edit'),
    # Service catalog (Phase 2c)
    path('catalog/', views.service_catalog, name='service_catalog'),
    path('catalog/new/', views.service_catalog_form, name='service_catalog_create'),
    path('catalog/<int:pk>/edit/', views.service_catalog_form, name='service_catalog_edit'),
    # Time entries
    path('t/<str:ticket_number>/timer/start/', views.timer_start, name='timer_start'),
    path('t/<str:ticket_number>/timer/stop/', views.timer_stop, name='timer_stop'),
    path('t/<str:ticket_number>/time/manual/', views.time_entry_manual, name='time_entry_manual'),
    # Per-ticket
    path('t/<str:ticket_number>/context/', views.ticket_vault_context, name='ticket_vault_context'),
    path('t/<str:ticket_number>/comment/', views.ticket_post_comment, name='ticket_post_comment'),
    # Phase 21 v11 (v3.17.317): mobile dispatch routing — JSON helper
    path('t/<str:ticket_number>/route-urls/', views.ticket_route_urls,
         name='ticket_route_urls'),
    path('t/<str:ticket_number>/attach/', views.ticket_attach, name='ticket_attach'),
    path('t/<str:ticket_number>/action/', views.ticket_quick_action, name='ticket_quick_action'),
    path('t/<str:ticket_number>/watch/', views.ticket_watch_toggle, name='ticket_watch_toggle'),
    path('t/<str:ticket_number>/merge/', views.ticket_merge, name='ticket_merge'),
    path('t/<str:ticket_number>/kb-link/', views.ticket_kb_link, name='ticket_kb_link'),
    path('t/<str:ticket_number>/kb-unlink/<int:link_pk>/', views.ticket_kb_unlink, name='ticket_kb_unlink'),
    path('t/<str:ticket_number>/workflow/launch/', views.ticket_launch_workflow, name='ticket_launch_workflow'),
    # Phase 7: outsourcing
    path('t/<str:ticket_number>/share/', views.ticket_share, name='ticket_share'),
    path('partners/webhook/<int:share_pk>/', views.ticket_partner_webhook, name='ticket_partner_webhook'),
    path('t/<str:ticket_number>/', views.ticket_detail, name='ticket_detail'),
    # Phase 10.4: per-ticket email conversation panel.
    path('t/<str:ticket_number>/conversation/', views.ticket_conversation,
         name='ticket_conversation'),
    # Projects (Workstream 3)
    path('projects/', views.project_list, name='project_list'),
    path('projects/new/', views.project_form, name='project_create'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/edit/', views.project_form, name='project_edit'),
    path('projects/<int:pk>/task/add/', views.project_task_add, name='project_task_add'),
    # Phase 35.1 (v3.17.548) — project templates.
    path('project-templates/', views.project_template_list, name='project_template_list'),
    path('project-templates/new/', views.project_template_create, name='project_template_create'),
    path('project-templates/<int:pk>/', views.project_template_detail, name='project_template_detail'),
    path('projects/<int:pk>/apply-template/', views.project_apply_template, name='project_apply_template'),
    path('project-task/<int:task_pk>/update/', views.project_task_update, name='project_task_update'),
    path('project-task/<int:task_pk>/delete/', views.project_task_delete, name='project_task_delete'),
    # Phase 35.5 (v3.17.554) — timeline / Gantt.
    path('projects/<int:pk>/timeline/', views.project_timeline, name='project_timeline'),
    path('project-task/<int:task_pk>/reschedule/', views.project_task_reschedule, name='project_task_reschedule'),
    path('project-task/<int:task_pk>/dependency/', views.project_task_dependency, name='project_task_dependency'),
    # Phase 35.4 (v3.17.550) — spawn a ticket from a task.
    path('project-task/<int:task_pk>/to-ticket/', views.project_task_to_ticket, name='project_task_to_ticket'),
    # Recurring tickets (preventive maintenance)
    path('recurring/', views.recurring_list, name='recurring_list'),
    path('recurring/new/', views.recurring_form, name='recurring_create'),
    path('recurring/<int:pk>/edit/', views.recurring_form, name='recurring_edit'),
    # Knowledge Base browser
    path('kb/', views.kb_browse, name='kb_browse'),
    path('kb/move/', views.kb_move_articles, name='kb_move_articles'),
    # Approvals
    path('approvals/', views.approval_list, name='approval_list'),
    path('approvals/<int:pk>/decide/', views.approval_decide, name='approval_decide'),
    # Phase 20 v6 (v3.17.274): approval audit trail
    path('approvals/<int:pk>/history/', views.approval_history,
         name='approval_history'),
    # Contracts (Workstream 5)
    path('contracts/', views.contract_list, name='contract_list'),
    path('contracts/new/', views.contract_form, name='contract_create'),
    path('contracts/<int:pk>/', views.contract_detail, name='contract_detail'),
    path('contracts/<int:pk>/edit/', views.contract_form, name='contract_edit'),
    # Email ingestion
    path('email-configs/', views.email_config_list, name='email_config_list'),
    path('email-configs/new/', views.email_config_form, name='email_config_create'),
    path('email-configs/<int:pk>/edit/', views.email_config_form, name='email_config_edit'),
    # Issue #142 outbound — Graph readiness check + labeled test send.
    path('email-configs/<int:pk>/graph-readiness/', views.email_graph_readiness, name='email_graph_readiness'),
    path('email-configs/<int:pk>/graph-test-send/', views.email_graph_test_send, name='email_graph_test_send'),
    # Quotes / Estimates
    path('quotes/', views.quote_list, name='quote_list'),
    path('quotes/new/', views.quote_form, name='quote_create'),
    path('quotes/<int:pk>/', views.quote_detail, name='quote_detail'),
    path('quotes/<int:pk>/edit/', views.quote_form, name='quote_edit'),
    path('quotes/<int:pk>/accept/', views.quote_accept, name='quote_accept'),
    path('quotes/<int:pk>/to-po/', views.quote_to_po, name='quote_to_po'),
    # Phase 20 v4 (v3.17.270): quote approval routing.
    path('quotes/<int:pk>/send-for-approval/', views.quote_send_for_approval,
         name='quote_send_for_approval'),
    # Expenses (per-ticket)
    path('t/<str:ticket_number>/expense/add/', views.ticket_expense_add, name='ticket_expense_add'),
    # Workflow rules (Workstream 9)
    path('rules/', views.workflow_rule_list, name='workflow_rule_list'),
    path('rules/new/', views.workflow_rule_form, name='workflow_rule_create'),
    path('rules/<int:pk>/edit/', views.workflow_rule_form, name='workflow_rule_edit'),
    path('rules/<int:pk>/delete/', views.workflow_rule_delete, name='workflow_rule_delete'),
    # Phase 14 v9 (v3.17.288): workflow rule templates
    path('rules/templates/', views.workflow_template_list,
         name='workflow_template_list'),
    path('rules/templates/<int:pk>/instantiate/',
         views.workflow_template_instantiate,
         name='workflow_template_instantiate'),
    # Phase 14 v13 (v3.17.290): AI-assisted workflow suggestions
    path('rules/suggestions/', views.workflow_suggestion_list,
         name='workflow_suggestion_list'),
    path('rules/suggestions/<int:pk>/decide/',
         views.workflow_suggestion_decide,
         name='workflow_suggestion_decide'),
    # Dispatch board
    path('dispatch/', views.dispatch_board, name='dispatch_board'),
    path('dispatch/assign/', views.dispatch_assign, name='dispatch_assign'),
    path('dispatch/heatmap/', views.dispatch_heatmap, name='dispatch_heatmap'),
    # Invoices + payments (Workstream 5 billing)
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/new/', views.invoice_form, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.invoice_form, name='invoice_edit'),
    path('invoices/<int:pk>/payment/', views.payment_add, name='payment_add'),
    path('invoices/<int:pk>/push/', views.invoice_push_to_accounting, name='invoice_push_to_accounting'),
    # Phase 46 (v3.17.533) — job kit list on a ticket.
    path('t/<str:ticket_number>/kit/add/', views.ticket_kit_add,
         name='ticket_kit_add'),
    path('t/<str:ticket_number>/kit/<int:pk>/remove/', views.ticket_kit_remove,
         name='ticket_kit_remove'),
    path('t/<str:ticket_number>/kit/<int:pk>/packed/',
         views.ticket_kit_toggle_packed, name='ticket_kit_toggle_packed'),
    # Phase 36 v2: pre-invoice approval gate.
    path('invoices/<int:pk>/approve/', views.invoice_approve, name='invoice_approve'),
    path('invoices/<int:pk>/request-approval/', views.invoice_request_approval, name='invoice_request_approval'),
    # Phase 27 v3 (v3.17.264): credit-memo workflow.
    path('invoices/<int:pk>/credit-memo/', views.invoice_credit_memo,
         name='invoice_credit_memo'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('invoices/<int:pk>/email/', views.invoice_email, name='invoice_email'),
    path('invoices/from-ticket/<str:ticket_number>/', views.invoice_from_ticket, name='invoice_from_ticket'),
    # Quote PDF + email
    path('quotes/<int:pk>/pdf/', views.quote_pdf, name='quote_pdf'),
    path('quotes/<int:pk>/email/', views.quote_email, name='quote_email'),
    # Client account + charges + aging
    path('clients/<int:org_id>/account/', views.client_account, name='client_account'),
    path('clients/<int:org_id>/charge/', views.charge_add, name='charge_add'),
    path('clients/<int:org_id>/charge/invoice/', views.charge_invoice, name='charge_invoice'),
    path('clients/<int:org_id>/invite-portal/', views.portal_invite, name='portal_invite'),
    path('aging/', views.aging_report, name='aging_report'),
    # Phase 12 v1 — public CSAT response (token-authenticated, no login).
    path('csat/<str:token>/', views.csat_respond, name='csat_respond'),
    # Phase 25 v1 (v3.17.242) — Timesheet approval workflow.
    path('timesheet/', views.my_timesheet, name='my_timesheet'),
    path('timesheet/<int:year>/<int:week>/', views.my_timesheet, name='my_timesheet_iso'),
    path('timesheet-approvals/', views.timesheet_approval_queue, name='timesheet_approval_queue'),
    path('timesheet-approvals/<int:pk>/decide/', views.timesheet_decide, name='timesheet_decide'),
    # Phase 25 v2 (v3.17.249) — bulk decide + payroll CSV export.
    path('timesheet-approvals/bulk/', views.timesheet_bulk_decide, name='timesheet_bulk_decide'),
    path('timesheet-approvals/payroll-export/', views.timesheet_payroll_export, name='timesheet_payroll_export'),

    # Procurement (Phase 4.1) — Purchase Requisitions
    path('requisitions/', views.requisition_list, name='requisition_list'),
    path('requisitions/new/', views.requisition_form, name='requisition_create'),
    path('requisitions/<int:pk>/', views.requisition_detail, name='requisition_detail'),
    path('requisitions/<int:pk>/edit/', views.requisition_form, name='requisition_edit'),
    path('requisitions/<int:pk>/submit/', views.requisition_submit, name='requisition_submit'),
    path('requisitions/<int:pk>/decide/', views.requisition_decide, name='requisition_decide'),
    path('requisitions/<int:pk>/convert/', views.requisition_to_po, name='requisition_to_po'),

    # Procurement (Phase 4.1) — Purchase Orders
    path('purchase-orders/', views.po_list, name='po_list'),
    path('purchase-orders/new/', views.po_form, name='po_create'),
    path('purchase-orders/<int:pk>/', views.po_detail, name='po_detail'),
    path('purchase-orders/<int:pk>/edit/', views.po_form, name='po_edit'),
    path('purchase-orders/<int:pk>/pdf/', views.po_pdf, name='po_pdf'),
    path('purchase-orders/<int:pk>/send/', views.po_send, name='po_send'),

    # Procurement (Phase 4.2) — Receiving + back-orders
    path('purchase-orders/<int:pk>/receive/', views.po_receive, name='po_receive'),
    path('back-orders/', views.back_order_list, name='back_order_list'),
    path('back-orders/<int:pk>/cancel/', views.back_order_cancel, name='back_order_cancel'),

    # Procurement (Phase 4.3) — Vendors
    path('vendors/', views.vendor_list, name='vendor_list'),
    path('vendors/new/', views.vendor_form, name='vendor_create'),
    path('vendors/<int:pk>/', views.vendor_detail, name='vendor_detail'),
    path('vendors/<int:pk>/edit/', views.vendor_form, name='vendor_edit'),

    # Change management (Phase 6.1) — CAB approval workflow
    path('changes/', views.change_request_list, name='change_request_list'),
    path('t/<str:ticket_number>/change/', views.change_request_detail, name='change_request_detail'),
    path('t/<str:ticket_number>/change/edit/', views.change_request_form, name='change_request_form'),
    path('t/<str:ticket_number>/change/submit/', views.change_request_submit, name='change_request_submit'),
    path('t/<str:ticket_number>/change/vote/', views.change_request_vote, name='change_request_vote'),
    path('t/<str:ticket_number>/change/implement/', views.change_request_implement, name='change_request_implement'),
    path('t/<str:ticket_number>/change/verify/', views.change_request_verify, name='change_request_verify'),
    path('t/<str:ticket_number>/change/fail/', views.change_request_fail, name='change_request_fail'),

    # Problem management (Phase 6.2) — RCA + recurring incidents
    path('problems/', views.problem_list, name='problem_list'),
    path('problems/new/', views.problem_form, name='problem_create'),
    path('problems/<int:pk>/', views.problem_detail, name='problem_detail'),
    path('problems/<int:pk>/edit/', views.problem_form, name='problem_edit'),
    path('problems/<int:pk>/link-ticket/', views.problem_link_ticket, name='problem_link_ticket'),
    path('problems/<int:pk>/unlink-ticket/<int:ticket_pk>/', views.problem_unlink_ticket, name='problem_unlink_ticket'),
    path('problems/<int:pk>/notes/', views.problem_add_note, name='problem_add_note'),
    path('problems/<int:pk>/advance/', views.problem_advance_status, name='problem_advance_status'),

    # Release management (Phase 6.3)
    path('releases/', views.release_list, name='release_list'),
    path('releases/new/', views.release_form, name='release_create'),
    path('releases/<int:pk>/', views.release_detail, name='release_detail'),
    path('releases/<int:pk>/edit/', views.release_form, name='release_edit'),
    path('releases/<int:pk>/add-change/', views.release_add_change, name='release_add_change'),
    path('releases/<int:pk>/remove-change/<int:change_pk>/', views.release_remove_change, name='release_remove_change'),
    path('releases/<int:pk>/freeze/', views.release_freeze, name='release_freeze'),
    path('releases/<int:pk>/complete/', views.release_complete, name='release_complete'),
    path('releases/<int:pk>/rollback/', views.release_rollback, name='release_rollback'),

    # Service catalog governance (Phase 6.3)
    path('catalog/<int:pk>/propose/', views.catalog_propose_change, name='catalog_propose_change'),
    path('catalog-changes/', views.catalog_change_list, name='catalog_change_list'),
    path('catalog-changes/<int:pk>/decide/', views.catalog_change_decide, name='catalog_change_decide'),
]
