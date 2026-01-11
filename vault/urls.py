"""
Vault URL configuration
"""
from django.urls import path
from . import views

app_name = 'vault'

urlpatterns = [
    path('', views.password_list, name='password_list'),
    path('create/', views.password_create, name='password_create'),
    path('<int:pk>/', views.password_detail, name='password_detail'),
    path('<int:pk>/edit/', views.password_edit, name='password_edit'),
    path('<int:pk>/delete/', views.password_delete, name='password_delete'),
    path('<int:pk>/reveal/', views.password_reveal, name='password_reveal'),
    path('<int:pk>/test-breach/', views.password_test_breach, name='password_test_breach'),
    path('<int:pk>/otp/', views.generate_otp_api, name='generate_otp'),
    path('<int:pk>/qrcode/', views.password_qrcode, name='password_qrcode'),

    # Utility APIs
    path('api/generate/', views.generate_password_api, name='generate_password_api'),
    path('api/strength/', views.check_password_strength_api, name='check_strength_api'),

    # Personal Vault (encrypted notes)
    path('personal/', views.personal_vault_list, name='personal_vault_list'),
    path('personal/create/', views.personal_vault_create, name='personal_vault_create'),
    path('personal/<int:pk>/', views.personal_vault_detail, name='personal_vault_detail'),
    path('personal/<int:pk>/edit/', views.personal_vault_edit, name='personal_vault_edit'),
    path('personal/<int:pk>/delete/', views.personal_vault_delete, name='personal_vault_delete'),
]
