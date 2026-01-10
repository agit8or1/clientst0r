"""
Docs URL configuration
"""
from django.urls import path
from . import views

app_name = 'docs'

urlpatterns = [
    path('', views.document_list, name='document_list'),
    path('create/', views.document_create, name='document_create'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/create/', views.template_create, name='template_create'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('kb/', views.global_kb_list, name='global_kb_list'),
    path('kb/create/', views.global_kb_create, name='global_kb_create'),
    path('kb/<slug:slug>/', views.global_kb_detail, name='global_kb_detail'),
    path('kb/<slug:slug>/edit/', views.global_kb_edit, name='global_kb_edit'),
    path('kb/<slug:slug>/delete/', views.global_kb_delete, name='global_kb_delete'),
    path('<slug:slug>/', views.document_detail, name='document_detail'),
    path('<slug:slug>/edit/', views.document_edit, name='document_edit'),
    path('<slug:slug>/delete/', views.document_delete, name='document_delete'),
]
