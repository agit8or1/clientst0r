"""
API URL Configuration for Client St0r REST API
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AssetViewSet, ContactViewSet, DocumentViewSet,
    PasswordViewSet, TagViewSet, OrganizationViewSet
)
from .key_views import apikey_list, apikey_create, apikey_delete, apikey_toggle

# Create router and register viewsets
router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'documents', DocumentViewSet, basename='document')
router.register(r'passwords', PasswordViewSet, basename='password')
router.register(r'tags', TagViewSet, basename='tag')
router.register(r'organizations', OrganizationViewSet, basename='organization')

app_name = 'api'

urlpatterns = [
    # No password-only token endpoint: DRF's obtain_auth_token issued the same
    # token the mobile API accepts without a 2FA step. Use API keys here, or
    # /api/mobile/v1/auth/login/ (which enforces MFA) for mobile tokens.

    # API Key Management (Web UI)
    path('keys/', apikey_list, name='apikey_list'),
    path('keys/create/', apikey_create, name='apikey_create'),
    path('keys/<int:pk>/delete/', apikey_delete, name='apikey_delete'),
    path('keys/<int:pk>/toggle/', apikey_toggle, name='apikey_toggle'),

    # Browsable API root
    path('', include(router.urls)),
]
