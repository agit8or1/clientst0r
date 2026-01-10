"""
URL Configuration for HuduGlue
"""
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.views.generic import RedirectView
from two_factor.urls import urlpatterns as tf_urls

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Two-Factor Auth
    path('', include(tf_urls)),

    # Legacy logout alias (for compatibility)
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),

    # Home - redirect to dashboard
    path('', RedirectView.as_view(url='/core/dashboard/', permanent=False), name='home'),

    # Apps
    path('core/', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('assets/', include('assets.urls')),
    path('vault/', include('vault.urls')),
    path('docs/', include('docs.urls')),
    path('files/', include('files.urls')),
    path('integrations/', include('integrations.urls')),
    path('audit/', include('audit.urls')),
    path('monitoring/', include('monitoring.urls')),

    # API
    path('api/', include('api.urls')),
]
