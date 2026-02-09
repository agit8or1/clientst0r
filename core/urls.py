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

app_name = 'core'

urlpatterns = [
    path('dashboard/', dashboard_views.dashboard, name='dashboard'),
    path('global-dashboard/', dashboard_views.global_dashboard, name='global_dashboard'),
    path('documentation/', views.documentation, name='documentation'),
    path('about/', views.about, name='about'),
    path('search/', search_views.global_search, name='search'),
    path('report-bug/', views.report_bug, name='report_bug'),
    path('download-mobile-app/<str:app_type>/', views.download_mobile_app, name='download_mobile_app'),

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

    # Firewall (superuser only)
    path('settings/firewall/', firewall_views.firewall_settings, name='firewall_settings'),
    path('settings/firewall/ip-rules/', firewall_views.firewall_ip_rules, name='firewall_ip_rules'),
    path('settings/firewall/ip-rules/<int:pk>/delete/', firewall_views.firewall_ip_rule_delete, name='firewall_ip_rule_delete'),
    path('settings/firewall/ip-rules/<int:pk>/toggle/', firewall_views.firewall_ip_rule_toggle, name='firewall_ip_rule_toggle'),
    path('settings/firewall/country-rules/', firewall_views.firewall_country_rules, name='firewall_country_rules'),
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

    # Admin Settings (superuser only)
    path('settings/general/', settings_views.settings_general, name='settings_general'),
    path('settings/security/', settings_views.settings_security, name='settings_security'),
    path('settings/features/', settings_views.settings_features, name='settings_features'),
    path('settings/smtp/', settings_views.settings_smtp, name='settings_smtp'),
    path('settings/smtp/test/', settings_views.test_smtp_email, name='test_smtp_email'),
    path('settings/sms/', settings_views.settings_sms, name='settings_sms'),
    path('settings/scheduler/', settings_views.settings_scheduler, name='settings_scheduler'),
    path('settings/directory/', settings_views.settings_directory, name='settings_directory'),
    path('settings/ai/', settings_views.settings_ai, name='settings_ai'),
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
    path('api/update-status/', views.update_status_api, name='update_status_api'),
    path('api/update-progress/', views.update_progress_api, name='update_progress_api'),
]
