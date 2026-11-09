from django.urls import path

from . import views

app_name = 'tech_access'

urlpatterns = [
    path('', views.index, name='index'),
]
