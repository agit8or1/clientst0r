from django.urls import path

from . import views

app_name = 'health_score'

urlpatterns = [
    path('', views.client_list, name='list'),
    path('settings/', views.settings_view, name='settings'),
    path('<int:client_id>/', views.client_detail, name='detail'),
    path('<int:client_id>/recompute/', views.recompute, name='recompute'),
]
