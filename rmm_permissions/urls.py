from django.urls import path

from . import views

app_name = 'rmm_permissions'

urlpatterns = [
    path('', views.index, name='index'),
    path('technician/<int:user_id>/', views.technician, name='technician'),
    path('customer/<int:org_id>/', views.customer, name='customer'),
    path('approvals/', views.approvals, name='approvals'),
]
