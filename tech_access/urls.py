from django.urls import path

from . import views

app_name = 'tech_access'

urlpatterns = [
    path('', views.index, name='index'),
    path('superusers/', views.superuser_policy, name='superuser_policy'),
    path('why/', views.why, name='why'),
    path('assignments/<int:pk>/', views.assignment_detail, name='assignment_detail'),
    path('changes/<int:pk>/', views.change_detail, name='change_detail'),
]
