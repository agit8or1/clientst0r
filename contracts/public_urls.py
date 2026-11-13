"""Public signing URLs. Everything lives under the single prefix /sign/
(customer-facing, no account): /sign/t/<token>/ opens a link and
/sign/i/<public id>/... are the session-bound signing pages."""
from django.urls import path

from . import public_views as v

app_name = 'contract_sign'

urlpatterns = [
    path('t/<str:token>/', v.open_link, name='open'),
    path('i/<uuid:public_id>/', v.page, name='page'),
    path('i/<uuid:public_id>/seen/', v.seen, name='seen'),
    path('i/<uuid:public_id>/code/', v.request_code, name='code'),
    path('i/<uuid:public_id>/verify/', v.verify_code, name='verify'),
    path('i/<uuid:public_id>/sign/', v.sign, name='sign'),
    path('i/<uuid:public_id>/decline/', v.decline, name='decline'),
    path('i/<uuid:public_id>/document.pdf', v.download, name='download'),
    path('i/<uuid:public_id>/attachments/<int:pk>/', v.attachment, name='attachment'),
]
