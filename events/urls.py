from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_list, name='list'),
    path('<int:pk>/', views.event_detail, name='detail'),
    path('<int:pk>/link/', views.event_link, name='link'),
    path('<int:pk>/unlink/<int:link_pk>/', views.event_unlink, name='unlink'),
    path('ingestion/', views.ingestion_health, name='health'),
    path('sources/', views.source_health, name='source_health'),
    path('sources.json', views.source_health_json, name='source_health_json'),
]
