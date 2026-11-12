"""Collabora URL patterns, included from office/provider_urls.py (/office/api/).

The WOPI paths have no trailing slash: Collabora appends ``/contents`` to
the WOPISrc it was given, and a POST must never be redirected.
"""
from django.urls import path

from . import views, wopi

urlpatterns = [
    path('wopi/files/<str:file_id>', wopi.wopi_file, name='collabora_wopi_file'),
    path('wopi/files/<str:file_id>/contents', wopi.wopi_contents, name='collabora_wopi_contents'),
    path('collabora/s/<uuid:session_id>/renew/', views.renew, name='collabora_renew'),
    path('collabora/s/<uuid:session_id>/event/', views.event, name='collabora_event'),
]
