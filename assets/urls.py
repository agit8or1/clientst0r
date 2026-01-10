"""
Assets URL configuration
"""
from django.urls import path
from . import views
from . import relationship_views
from . import quick_views

app_name = 'assets'

urlpatterns = [
    path('', views.asset_list, name='asset_list'),
    path('create/', views.asset_create, name='asset_create'),
    path('quick/pc/', quick_views.quick_pc_add, name='quick_pc_add'),
    path('<int:pk>/', views.asset_detail, name='asset_detail'),
    path('<int:pk>/edit/', views.asset_edit, name='asset_edit'),
    path('contacts/', views.contact_list, name='contact_list'),
    path('contacts/create/', views.contact_create, name='contact_create'),
    path('contacts/<int:pk>/', views.contact_detail, name='contact_detail'),
    path('contacts/<int:pk>/edit/', views.contact_edit, name='contact_edit'),
    path('contacts/<int:pk>/delete/', views.contact_delete, name='contact_delete'),

    # Relationships
    path('relationships/map/', relationship_views.relationship_map, name='relationship_map'),
    path('relationships/create/', relationship_views.relationship_create, name='relationship_create'),
    path('relationships/<int:pk>/delete/', relationship_views.relationship_delete, name='relationship_delete'),
]
