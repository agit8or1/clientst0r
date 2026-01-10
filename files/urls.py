"""
Files URL configuration
"""
from django.urls import path
from . import views

app_name = 'files'

urlpatterns = [
    path('serve/<int:pk>/', views.serve_attachment, name='serve_attachment'),
    path('upload/', views.upload_attachment, name='upload_attachment'),
]
