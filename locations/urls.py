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

    # Floor plan import
    path('floor-plan-import/', views.floor_plan_import, name='floor_plan_import'),

    # AJAX endpoints for data refresh
    path('<int:location_id>/refresh-geocoding/', views.refresh_geocoding, name='refresh_geocoding'),
    path('<int:location_id>/refresh-property-data/', views.refresh_property_data, name='refresh_property_data'),
    path('<int:location_id>/refresh-satellite-image/', views.refresh_satellite_image, name='refresh_satellite_image'),
    path('<int:location_id>/import-property-from-url/', views.import_property_from_url, name='import_property_from_url'),

    # Map data endpoints
    path('map-data/', views.location_map_data, name='location_map_data'),
    path('global-map-data/', views.global_location_map_data, name='global_location_map_data'),

    # Send navigation link
    path('<int:location_id>/send-navigation/', views.send_navigation_link, name='send_navigation_link'),
]
