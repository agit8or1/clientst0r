"""
URL patterns for locations app
"""
from django.urls import path
from . import views

app_name = 'locations'

urlpatterns = [
    # Location CRUD
    path('', views.location_list, name='location_list'),
    path('create/', views.location_create, name='location_create'),
    path('<int:location_id>/', views.location_detail, name='location_detail'),
    path('<int:location_id>/edit/', views.location_edit, name='location_edit'),
    path('<int:location_id>/delete/', views.location_delete, name='location_delete'),

    # Floor plan generation
    path('<int:location_id>/generate-floor-plan/', views.generate_floor_plan, name='generate_floor_plan'),

    # AJAX endpoints for data refresh
    path('<int:location_id>/refresh-geocoding/', views.refresh_geocoding, name='refresh_geocoding'),
    path('<int:location_id>/refresh-property-data/', views.refresh_property_data, name='refresh_property_data'),
    path('<int:location_id>/refresh-satellite-image/', views.refresh_satellite_image, name='refresh_satellite_image'),
]
