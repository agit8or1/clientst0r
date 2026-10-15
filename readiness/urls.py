from django.urls import path

from . import views

app_name = 'readiness'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('customer/<int:org_id>/', views.org_readiness, name='org_readiness'),
    path('customer/<int:org_id>/exceptions/add/', views.exception_add, name='exception_add'),
    path('exceptions/<int:pk>/delete/', views.exception_delete, name='exception_delete'),
    path('repair/', views.repair_queue, name='repair_queue'),
    path('standards/', views.standard_list, name='standard_list'),
    path('standards/new/', views.standard_edit, name='standard_create'),
    path('standards/<int:pk>/edit/', views.standard_edit, name='standard_edit'),
    path('standards/<int:pk>/delete/', views.standard_delete, name='standard_delete'),
    path('relationships/broken/', views.broken_relationships, name='broken_relationships'),
]
