"""
Core URL configuration
"""
from django.urls import path
from . import views
from . import search_views
from . import favorites_views
from . import securenotes_views
from . import dashboard_views
from . import settings_views
from . import tag_views
from . import firewall_views
from . import fail2ban_views
from . import webhook_views
from . import security_views
from . import help_views

app_name = 'core'

urlpatterns = [
    path('dashboard/', dashboard_views.dashboard, name='dashboard'),
    path('global-dashboard/', dashboard_views.global_dashboard, name='global_dashboard'),
    path('documentation/', views.documentation, name='documentation'),
    path('about/', views.about, name='about'),
    path('roadmap/', views.roadmap, name='roadmap'),
    path('roadmap.json', views.roadmap_status_json, name='roadmap_status_json'),
    path('free-consult/', views.free_consult, name='free_consult'),
    path('free-consult/requests/', views.consult_requests, name='consult_requests'),
    path('install/', views.install_app, name='install_app'),
    # v3.17.473 — beta-tester sign-up + admin
    path('beta-test/', views.beta_test_signup, name='beta_test_signup'),
    path('beta-testers/', views.beta_test_admin, name='beta_test_admin'),
    # v3.17.488 — cross-origin upstream endpoint. Remote installs of
    # Client St0r POST signup data here so it lands on the canonical
    # agit8or1 server (the one hosting the Play Console listing).
    path('beta-test/upstream/', views.beta_test_upstream, name='beta_test_upstream'),

    # Help & Documentation
    path('help/', help_views.help_index, name='help_index'),
    path('help/getting-started/', help_views.help_getting_started, name='help_getting_started'),
    path('help/features/', help_views.help_features, name='help_features'),
    path('help/assets/', help_views.help_assets, name='help_assets'),
    path('help/vehicles/', help_views.help_vehicles, name='help_vehicles'),
    path('help/vault/', help_views.help_vault, name='help_vault'),
    path('help/monitoring/', help_views.help_monitoring, name='help_monitoring'),
    path('help/security/', help_views.help_security, name='help_security'),
    path('help/api/', help_views.help_api, name='help_api'),
    path('help/reports/', help_views.help_reports, name='help_reports'),
    path('help/workflows/', help_views.help_workflows, name='help_workflows'),
    path('help/documentation/', help_views.help_documentation, name='help_documentation'),
    path('help/locations/', help_views.help_locations, name='help_locations'),
    path('help/search/', help_views.help_search, name='help_search'),

    path('search/', search_views.global_search, name='search'),
    path('report-bug/', views.report_bug, name='report_bug'),
    path('download-mobile-app/<str:app_type>/', views.download_mobile_app, name='download_mobile_app'),
    path('mobile-apps/', views.mobile_apps_admin, name='mobile_apps_admin'),
    path('mobile-apps/build-progress/<str:app_type>/', views.mobile_app_build_progress, name='mobile_app_build_progress'),
    path('download-browser-extension/', views.download_browser_extension, name='download_browser_extension'),

    # Tags (admin only)
    path('tags/', tag_views.tag_list, name='tag_list'),
    path('tags/create/', tag_views.tag_create, name='tag_create'),
    path('tags/<int:pk>/edit/', tag_views.tag_edit, name='tag_edit'),
    path('tags/<int:pk>/delete/', tag_views.tag_delete, name='tag_delete'),

    # Favorites
    path('favorites/', favorites_views.favorite_list, name='favorite_list'),
    path('favorites/toggle/<int:content_type_id>/<int:object_id>/', favorites_views.favorite_toggle, name='favorite_toggle'),
    path('favorites/check/<int:content_type_id>/<int:object_id>/', favorites_views.favorite_check, name='favorite_check'),

    # Secure Notes
    path('secure-notes/', securenotes_views.secure_note_inbox, name='secure_note_inbox'),
    path('secure-notes/sent/', securenotes_views.secure_note_sent, name='secure_note_sent'),
    path('secure-notes/create/', securenotes_views.secure_note_create, name='secure_note_create'),
    path('secure-notes/<int:pk>/', securenotes_views.secure_note_detail, name='secure_note_detail'),
    path('secure-notes/<int:pk>/delete/', securenotes_views.secure_note_delete, name='secure_note_delete'),
    path('secure-notes/<int:pk>/link/', securenotes_views.secure_note_link_created, name='secure_note_link_created'),
    path('secure-notes/<int:pk>/analytics/', securenotes_views.secure_note_analytics, name='secure_note_analytics'),
    path('secure-notes/links-dashboard/', securenotes_views.secure_note_links_dashboard, name='secure_note_links_dashboard'),
    path('secret/<str:token>/', securenotes_views.secure_note_view_link, name='secure_note_view_link'),

    # Security (superuser only)
    path('security/', settings_views.security_dashboard, name='security_dashboard'),

    # Package Scanner (staff only)
    path('security/package-scanner/', security_views.package_scanner_dashboard, name='package_scanner_dashboard'),
    path('security/package-scanner/run/', security_views.run_package_scan, name='run_package_scan'),
    path('security/package-scanner/update/', security_views.update_packages, name='update_packages'),
    path('security/package-scanner/scan/<int:pk>/', security_views.scan_detail, name='scan_detail'),
    path('api/security/package-scanner/widget/', security_views.get_dashboard_widget_data, name='package_scanner_widget_data'),

    # Python Dependency Scanner (staff only)
    path('security/python-scanner/', security_views.python_scanner_dashboard, name='python_scanner_dashboard'),
    path('security/python-scanner/run/', security_views.run_python_scan, name='run_python_scan'),
    path('security/python-scanner/remediate/', security_views.remediate_python_package, name='remediate_python_package'),
    path('security/python-scanner/scan/<int:pk>/', security_views.python_scan_detail, name='python_scan_detail'),
    path('api/security/python-scanner/widget/', security_views.get_python_scanner_widget_data, name='python_scanner_widget_data'),

    # Firewall (superuser only)
    path('settings/firewall/', firewall_views.firewall_settings, name='firewall_settings'),
    path('settings/firewall/ip-rules/', firewall_views.firewall_ip_rules, name='firewall_ip_rules'),
    path('settings/firewall/ip-rules/<int:pk>/delete/', firewall_views.firewall_ip_rule_delete, name='firewall_ip_rule_delete'),
    path('settings/firewall/ip-rules/<int:pk>/toggle/', firewall_views.firewall_ip_rule_toggle, name='firewall_ip_rule_toggle'),
    path('settings/firewall/country-rules/', firewall_views.firewall_country_rules, name='firewall_country_rules'),
    # v3.17.522 — GeoIP map backdrop (cosmetic; separate endpoint so it can never touch rules).
    path('settings/firewall/geoip-map-background/', firewall_views.geoip_map_background, name='geoip_map_background'),
    path('settings/firewall/country-rules/<int:pk>/delete/', firewall_views.firewall_country_rule_delete, name='firewall_country_rule_delete'),
    path('settings/firewall/country-rules/<int:pk>/toggle/', firewall_views.firewall_country_rule_toggle, name='firewall_country_rule_toggle'),
    path('settings/firewall/logs/', firewall_views.firewall_logs, name='firewall_logs'),
    path('settings/firewall/logs/clear/', firewall_views.firewall_logs_clear, name='firewall_logs_clear'),

    # Fail2ban (superuser only)
    path('settings/fail2ban/', fail2ban_views.fail2ban_status, name='fail2ban_status'),
    path('settings/fail2ban/install/', fail2ban_views.fail2ban_install, name='fail2ban_install'),
    path('settings/fail2ban/install-sudoers/', fail2ban_views.fail2ban_install_sudoers, name='fail2ban_install_sudoers'),
    path('settings/fail2ban/start/', fail2ban_views.fail2ban_start, name='fail2ban_start'),
    path('settings/fail2ban/unban/', fail2ban_views.fail2ban_unban_ip, name='fail2ban_unban_ip'),
    path('settings/fail2ban/unban-all/', fail2ban_views.fail2ban_unban_all, name='fail2ban_unban_all'),
    path('settings/fail2ban/check-ip/', fail2ban_views.fail2ban_check_ip, name='fail2ban_check_ip'),

    # Webhooks
    path('webhooks/', webhook_views.webhook_list, name='webhook_list'),
    path('webhooks/create/', webhook_views.webhook_create, name='webhook_create'),
    path('webhooks/<int:webhook_id>/edit/', webhook_views.webhook_edit, name='webhook_edit'),
    path('webhooks/<int:webhook_id>/delete/', webhook_views.webhook_delete, name='webhook_delete'),
    path('webhooks/<int:webhook_id>/test/', webhook_views.webhook_test, name='webhook_test'),
    path('webhooks/<int:webhook_id>/toggle/', webhook_views.webhook_toggle, name='webhook_toggle'),
    path('webhooks/<int:webhook_id>/deliveries/', webhook_views.webhook_deliveries, name='webhook_deliveries'),
    path('webhooks/deliveries/<int:delivery_id>/', webhook_views.webhook_delivery_detail, name='webhook_delivery_detail'),

    # Admin Settings (superuser only)
    path('settings/general/', settings_views.settings_general, name='settings_general'),
    path('settings/security/', settings_views.settings_security, name='settings_security'),
    path('settings/features/', settings_views.settings_features, name='settings_features'),
    # PSA settings — view lives in psa.views; aliased here so it appears
    # under the same /core/settings/ tree as the rest of admin settings.
    path('settings/psa/', __import__('psa.views', fromlist=['psa_global_settings_view']).psa_global_settings_view, name='settings_psa'),
    path('settings/smtp/', settings_views.settings_smtp, name='settings_smtp'),
    path('settings/smtp/test/', settings_views.test_smtp_email, name='test_smtp_email'),
    path('settings/sms/', settings_views.settings_sms, name='settings_sms'),
    path('settings/scheduler/', settings_views.settings_scheduler, name='settings_scheduler'),
    path('settings/directory/', settings_views.settings_directory, name='settings_directory'),
    path('settings/ai/', settings_views.settings_ai, name='settings_ai'),
    path('settings/ai/test/', settings_views.test_llm_connection, name='test_llm_connection'),
    path('settings/snyk/', settings_views.settings_snyk, name='settings_snyk'),
    path('settings/snyk/test/', settings_views.test_snyk_connection, name='test_snyk_connection'),
    path('settings/snyk/check-version/', settings_views.check_snyk_version, name='check_snyk_version'),
    path('settings/snyk/upgrade/', settings_views.upgrade_snyk_cli, name='upgrade_snyk_cli'),
    path('settings/snyk/install-nodejs/', settings_views.install_nodejs_npm, name='install_nodejs_npm'),
    path('settings/snyk/scans/', settings_views.snyk_scans, name='snyk_scans'),
    path('settings/snyk/scans/<int:scan_id>/', settings_views.snyk_scan_detail, name='snyk_scan_detail'),
    path('settings/snyk/scan/run/', settings_views.run_snyk_scan, name='run_snyk_scan'),
    path('settings/snyk/scan/status/<str:scan_id>/', settings_views.snyk_scan_status, name='snyk_scan_status'),
    path('settings/snyk/scan/cancel/<str:scan_id>/', settings_views.cancel_snyk_scan, name='cancel_snyk_scan'),
    path('security/scan/full/', settings_views.run_full_scan, name='run_full_scan'),
    path('security/scan/full/status/', settings_views.full_scan_status, name='full_scan_status'),
    path('security/scan/toggle-auto/', settings_views.toggle_security_scan, name='toggle_security_scan'),
    path('settings/snyk/remediate/', settings_views.apply_snyk_remediation, name='apply_snyk_remediation'),
    path('settings/snyk/fix-all/', settings_views.fix_all_snyk_vulnerabilities, name='fix_all_snyk_vulnerabilities'),
    path('settings/snyk/scans/cleanup/', settings_views.cleanup_old_snyk_scans, name='cleanup_old_snyk_scans'),
    path('settings/kb-import/', settings_views.settings_kb_import, name='settings_kb_import'),
    path('settings/kb-import/import/', settings_views.import_kb_articles, name='import_kb_articles'),
    path('settings/kb-import/delete/', settings_views.delete_global_kb_articles, name='delete_global_kb_articles'),
    path('settings/data-export/', settings_views.settings_data_export, name='settings_data_export'),
    path('settings/data-export/export/', settings_views.export_data, name='export_data'),
    path('settings/vault-import/', settings_views.vault_import, name='vault_import'),

    # API Key Validation
    path('settings/validate/anthropic/', settings_views.validate_anthropic_key, name='validate_anthropic_key'),
    path('settings/validate/google-maps/', settings_views.validate_google_maps_key, name='validate_google_maps_key'),
    path('settings/validate/twilio/', settings_views.validate_twilio_credentials, name='validate_twilio_credentials'),
    path('settings/validate/vonage/', settings_views.validate_vonage_credentials, name='validate_vonage_credentials'),

    path('settings/restart-app/', settings_views.restart_application, name='restart_application'),
    path('settings/system-status/', settings_views.system_status, name='system_status'),
    path('settings/maintenance/', settings_views.maintenance, name='maintenance'),

    # Demo Data Import (superuser only)
    path('settings/demo-data/import/', settings_views.import_demo_data, name='import_demo_data'),

    # System Updates (staff only)
    path('settings/updates/', views.system_updates, name='system_updates'),
    path('settings/updates/check/', views.check_updates_now, name='check_updates_now'),
    path('settings/updates/apply/', views.apply_update, name='apply_update'),
    path('settings/updates/force-restart/', views.force_restart_services, name='force_restart_services'),
    path('api/version-diagnostic/', views.version_diagnostic, name='version_diagnostic'),
    path('emergency-restart/', views.emergency_restart_webhook, name='emergency_restart_webhook'),
    path('api/update-status/', views.update_status_api, name='update_status_api'),
    path('api/update-progress/', views.update_progress_api, name='update_progress_api'),
]

# Test endpoint for database connection
from core.test_db_view import test_database_connection
urlpatterns.append(path('test-db/', test_database_connection, name='test_database'))

# Debug version endpoint
from core.debug_version_view import debug_version
urlpatterns.append(path('debug-version/', debug_version, name='debug_version'))
