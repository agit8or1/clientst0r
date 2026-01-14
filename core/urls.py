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

app_name = 'core'

urlpatterns = [
    path('dashboard/', dashboard_views.dashboard, name='dashboard'),
    path('global-dashboard/', dashboard_views.global_dashboard, name='global_dashboard'),
    path('documentation/', views.documentation, name='documentation'),
    path('about/', views.about, name='about'),
    path('search/', search_views.global_search, name='search'),

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

    # Admin Settings (superuser only)
    path('settings/general/', settings_views.settings_general, name='settings_general'),
    path('settings/security/', settings_views.settings_security, name='settings_security'),
    path('settings/smtp/', settings_views.settings_smtp, name='settings_smtp'),
    path('settings/scheduler/', settings_views.settings_scheduler, name='settings_scheduler'),
    path('settings/directory/', settings_views.settings_directory, name='settings_directory'),
    path('settings/ai/', settings_views.settings_ai, name='settings_ai'),
    path('settings/snyk/', settings_views.settings_snyk, name='settings_snyk'),
    path('settings/snyk/test/', settings_views.test_snyk_connection, name='test_snyk_connection'),
    path('settings/system-status/', settings_views.system_status, name='system_status'),
    path('settings/maintenance/', settings_views.maintenance, name='maintenance'),

    # System Updates (staff only)
    path('settings/updates/', views.system_updates, name='system_updates'),
    path('settings/updates/check/', views.check_updates_now, name='check_updates_now'),
    path('settings/updates/apply/', views.apply_update, name='apply_update'),
    path('api/update-status/', views.update_status_api, name='update_status_api'),
    path('api/update-progress/', views.update_progress_api, name='update_progress_api'),
]
