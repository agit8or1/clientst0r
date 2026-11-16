"""Agit8or Connect API routes (all 404 unless AGIT8OR_CONNECT_ENABLED)."""
from django.urls import path

from . import views_api as v

app_name = 'connect_api'

urlpatterns = [
    path('.well-known/agit8or-connect', v.discovery, name='discovery'),
    path('connect/v1/health', v.health, name='health'),
    path('connect/v1/pairing/requests', v.pairing_submit, name='pairing_submit'),
    path('connect/v1/pairing/requests/<str:request_id>/status', v.pairing_status, name='pairing_status'),
    path('connect/v1/token', v.token, name='token'),
    path('connect/v1/connections/<uuid:connection_id>/jwks', v.jwks, name='jwks'),
    path('connect/v1/capabilities', v.capabilities, name='capabilities'),
    path('connect/v1/test', v.test, name='test'),
    path('connect/v1/customers', v.customers, name='customers'),
    path('connect/v1/customers/current', v.customer_current, name='customer_current'),
    path('connect/v1/events', v.events_inbound, name='events'),
]
