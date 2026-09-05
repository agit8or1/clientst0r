"""Phase 34.1 (v3.17.544) — network config backup URLs."""
from django.urls import path

from . import views

app_name = 'netconfig'

urlpatterns = [
    path('', views.device_list, name='device_list'),
    path('device/<int:asset_id>/', views.device_detail, name='device_detail'),
    path('device/<int:asset_id>/capture/', views.capture, name='capture'),
    path('device/<int:asset_id>/compare/', views.compare, name='compare'),
    # Phase 34.2 (v3.17.545)
    path('device/<int:asset_id>/connection/', views.target_edit, name='target_edit'),
    path('device/<int:asset_id>/collect/', views.collect_now, name='collect_now'),
    path('backup/<int:backup_id>/', views.view_backup, name='view_backup'),
]
