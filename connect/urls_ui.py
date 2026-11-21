from django.urls import path

from . import views_qc as q
from . import views_ui as v

app_name = 'connect'

urlpatterns = [
    path('', v.index, name='index'),
    path('new/<slug:app_type>/', v.connect_app, name='connect_app'),
    path('invite/', v.invite, name='invite'),
    path('requests/<uuid:pk>/', v.request_review, name='request_review'),
    path('kill-switch/', v.kill_switch, name='kill_switch'),
    path('network/', v.network, name='network'),
    path('changes/<int:pk>/', v.change, name='change'),
    # Quick Connect (protocol 1.1). The callback has no trailing slash: it is
    # the signed redirect_uri, which must be a canonical URL (PROTOCOL-1.1.md §4.3).
    path('quick-connect/', q.qc_start, name='qc_start'),
    path('quick-connect/callback', q.qc_callback, name='qc_callback'),
    path('quick-connect/<uuid:pk>/', q.qc_attempt, name='qc_attempt'),
    path('confirm/', q.reauth, name='reauth'),
    path('<uuid:pk>/', v.detail, name='detail'),
]
