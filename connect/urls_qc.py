"""Quick Connect browser entry point (PROTOCOL-1.1.md §5.2): the
conventional responder page /agit8or-connect/qc-authorize. A web page of the
admin UI (login, 2FA, site firewall), deliberately outside the Connect API
prefixes, so the Connect source policy does not apply to it."""
from django.urls import path

from . import views_qc as q

app_name = 'connect_qc'

urlpatterns = [
    path('qc-authorize', q.qc_authorize, name='authorize'),
]
