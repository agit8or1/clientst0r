"""
Accounts URL configuration
"""
from django.urls import path
from . import views
from . import roles_views

app_name = 'accounts'

urlpatterns = [
    path('switch/<int:org_id>/', views.switch_organization, name='switch_organization'),
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/password/', views.password_change, name='password_change'),
    path('profile/2fa/', views.two_factor_setup, name='two_factor_setup'),

    # Organization Management
    path('organizations/', views.organization_list, name='organization_list'),
    path('organizations/create/', views.organization_create, name='organization_create'),
    path('organizations/<int:org_id>/', views.organization_detail, name='organization_detail'),
    path('organizations/<int:org_id>/edit/', views.organization_edit, name='organization_edit'),

    # Member Management
    path('organizations/<int:org_id>/members/add/', views.member_add, name='member_add'),
    path('organizations/<int:org_id>/members/<int:member_id>/edit/', views.member_edit, name='member_edit'),
    path('organizations/<int:org_id>/members/<int:member_id>/remove/', views.member_remove, name='member_remove'),

    # User Management (Superuser Only)
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:user_id>/', views.user_detail, name='user_detail'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/add-membership/', views.user_add_membership, name='user_add_membership'),
    path('users/<int:user_id>/password/', views.user_password_reset, name='user_password_reset'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),

    # Role Management (RBAC)
    path('roles/', roles_views.role_list, name='role_list'),
    path('roles/create/', roles_views.role_create, name='role_create'),
    path('roles/<int:pk>/edit/', roles_views.role_edit, name='role_edit'),
    path('roles/<int:pk>/delete/', roles_views.role_delete, name='role_delete'),
    path('members/', views.member_list, name='member_list'),
    path('members/<int:user_id>/assign-role/', roles_views.member_role_assign, name='member_role_assign'),
    path('members/<int:member_id>/suspend/', views.member_suspend, name='member_suspend'),
    path('members/<int:member_id>/reactivate/', views.member_reactivate, name='member_reactivate'),
]
