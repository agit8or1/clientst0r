from django.urls import path

from . import views

app_name = 'advisor'

urlpatterns = [
    path('', views.finding_list, name='finding_list'),
    path('findings/<int:pk>/', views.finding_detail, name='finding_detail'),
    path('findings/<int:pk>/explain/', views.finding_explain, name='finding_explain'),
    path('recommendations/<int:pk>/accept/', views.recommendation_accept, name='recommendation_accept'),
    path('recommendations/<int:pk>/dismiss/', views.recommendation_dismiss, name='recommendation_dismiss'),
    path('customers/<int:org_id>/', views.client_facts, name='client_facts'),
    path('settings/', views.settings_view, name='settings'),
]
