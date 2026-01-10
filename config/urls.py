"""
URL Configuration for HuduGlue
"""
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from two_factor.urls import urlpatterns as tf_urls

urlpatterns = [
    # Favicon
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/favicon.svg', permanent=True)),

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
    path('processes/', include('processes.urls')),
    path('files/', include('files.urls')),
    path('integrations/', include('integrations.urls')),
    path('audit/', include('audit.urls')),
    path('monitoring/', include('monitoring.urls')),

    # API
    path('api/', include('api.urls')),
]
