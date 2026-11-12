"""ONLYOFFICE URL patterns, included by office/provider_urls.py at /office/api/onlyoffice/."""
from django.urls import path

from . import views

urlpatterns = [
    path('callback/<uuid:session_id>/', views.callback, name='onlyoffice_callback'),
    path('file/<uuid:session_id>/', views.document_file, name='onlyoffice_file'),
    path('source/<str:signed>/', views.source, name='onlyoffice_source'),
    path('session/<uuid:session_id>/status/', views.session_status, name='onlyoffice_status'),
    path('session/<uuid:session_id>/forcesave/', views.forcesave, name='onlyoffice_forcesave'),
    path('session/<uuid:session_id>/save-as/', views.save_as, name='onlyoffice_save_as'),
    path('instances/<int:pk>/browser-probe/', views.browser_probe, name='onlyoffice_browser_probe'),
    path('instances/<int:pk>/browser-probe/result/', views.browser_probe_result,
         name='onlyoffice_browser_probe_result'),
]
