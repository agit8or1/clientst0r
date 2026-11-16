"""Staff payment pages and provider webhooks under /payments/. The customer
pages are in the portal namespace (portal/urls.py -> payments.portal_views)."""
from django.urls import path

from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.index, name='index'),
    path('connections/new/', views.connection_edit, name='connection_create'),
    path('connections/<int:pk>/', views.connection_edit, name='connection_edit'),
    path('connections/<int:pk>/verify/', views.connection_verify, name='connection_verify'),
    path('attempts/<int:pk>/', views.attempt_detail, name='attempt_detail'),
    path('attempts/<int:pk>/refund/', views.attempt_refund, name='attempt_refund'),
    # Signature-verified, no sign-in (accounts.middleware STAFF_ONLY_EXEMPT).
    path('webhooks/stripe/<int:pk>/', views.stripe_webhook, name='stripe_webhook'),
    path('webhooks/gocardless/<int:pk>/', views.gocardless_webhook, name='gocardless_webhook'),
]
