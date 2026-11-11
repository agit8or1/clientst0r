from django.urls import path

from . import views

app_name = 'support_workflows'

urlpatterns = [
    path('t/<str:ticket_number>/', views.ticket_workflows, name='ticket'),
    path('runs/<uuid:run_id>/', views.run_detail, name='run'),
    path('manage/', views.admin_list, name='admin'),
    path('manage/new/', views.admin_edit, name='admin_new'),
    path('manage/<slug:slug>/', views.admin_edit, name='admin_edit'),
]
