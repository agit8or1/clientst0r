from django.urls import path

from . import admin_views, views

app_name = 'oidc_sso'

urlpatterns = [
    # The signed-in user's own page: linked accounts, link / unlink.
    path('account/', views.account, name='account'),
    path('account/confirm/', views.reauth, name='reauth'),
    path('verify/', views.verify, name='verify'),

    # Administration -> Security -> Single sign-on (OIDC)
    path('settings/', admin_views.settings_index, name='settings'),
    path('settings/<int:pk>/', admin_views.provider_detail, name='provider_detail'),

    # Per provider (404 while the provider is disabled)
    path('<slug:slug>/login/', views.login_start, name='login'),
    path('<slug:slug>/callback/', views.callback, name='callback'),
    path('<slug:slug>/link/', views.link_start, name='link'),
    path('<slug:slug>/unlink/', views.unlink_self, name='unlink'),
    path('<slug:slug>/step-up/', views.stepup_start, name='stepup'),
    path('<slug:slug>/backchannel-logout/', views.backchannel_logout, name='backchannel_logout'),
    path('<slug:slug>/jwks.json', views.jwks, name='jwks'),
]
