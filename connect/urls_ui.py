from django.urls import path

from . import views_ui as v

app_name = 'connect'

urlpatterns = [
    path('', v.index, name='index'),
    path('new/<slug:app_type>/', v.connect_app, name='connect_app'),
    path('invite/', v.invite, name='invite'),
    path('requests/<uuid:pk>/', v.request_review, name='request_review'),
    path('kill-switch/', v.kill_switch, name='kill_switch'),
    path('<uuid:pk>/', v.detail, name='detail'),
]
