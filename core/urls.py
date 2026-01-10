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

app_name = 'core'

urlpatterns = [
    path('dashboard/', dashboard_views.dashboard, name='dashboard'),
    path('documentation/', views.documentation, name='documentation'),
    path('about/', views.about, name='about'),
    path('search/', search_views.global_search, name='search'),

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
    path('settings/system-status/', settings_views.system_status, name='system_status'),
    path('settings/maintenance/', settings_views.maintenance, name='maintenance'),
]
