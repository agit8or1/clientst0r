"""Customer portal sign-in URLs (portal/auth_views.py), mounted under
/portal/ next to portal/urls.py. Kept in their own module and namespace so
the portal pages' URLconf stays untouched."""
from django.urls import path

from . import auth_views

app_name = 'portal_auth'

urlpatterns = [
    path('login/', auth_views.portal_login, name='login'),
    path('logout/', auth_views.PortalLogoutView.as_view(), name='logout'),
    path('locked/', auth_views.portal_locked, name='locked'),
    path('password-reset/', auth_views.PortalPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/sent/', auth_views.PortalPasswordResetDoneView.as_view(),
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PortalPasswordResetConfirmView.as_view(),
         name='password_reset_confirm'),
    path('reset/done/', auth_views.PortalPasswordResetCompleteView.as_view(),
         name='password_reset_complete'),
    path('set-password/<uidb64>/<token>/', auth_views.portal_set_password, name='set_password'),
    path('account/two-factor/setup/', auth_views.PortalTwoFactorSetupView.as_view(),
         name='two_factor_setup'),
    path('account/two-factor/qrcode/', auth_views.PortalQRGeneratorView.as_view(),
         name='two_factor_qr'),
    path('account/two-factor/setup/complete/', auth_views.PortalTwoFactorSetupCompleteView.as_view(),
         name='two_factor_setup_complete'),
    path('account/two-factor/backup-codes/', auth_views.PortalBackupTokensView.as_view(),
         name='two_factor_backup_tokens'),
]
