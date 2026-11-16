from django.urls import path

from . import views

app_name = 'executive'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('metric/<slug:key>/', views.metric, name='metric'),
    path('metric/<slug:key>/records/', views.records, name='records'),
]
