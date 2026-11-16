from django.urls import path

from . import views

app_name = 'tax'

urlpatterns = [
    path('settings/', views.settings_view, name='settings'),
    path('settings/test/', views.test_connection, name='test_connection'),
    path('rates/new/', views.rate_form, name='rate_create'),
    path('rates/<int:pk>/edit/', views.rate_form, name='rate_edit'),
    path('rates/<int:pk>/delete/', views.rate_delete, name='rate_delete'),
    path('categories/new/', views.category_form, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_form, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('clients/<int:org_id>/exemptions/', views.client_exemptions, name='client_exemptions'),
    path('clients/<int:org_id>/exemptions/<int:pk>/certificate/', views.exemption_certificate,
         name='exemption_certificate'),
    path('clients/<int:org_id>/exemptions/<int:pk>/<str:action>/', views.exemption_action,
         name='exemption_action'),
    path('<str:doc_type>/<int:pk>/preview/', views.preview, name='preview'),
    path('<str:doc_type>/<int:pk>/override/', views.override, name='override'),
    path('<str:doc_type>/<int:pk>/line-categories/', views.set_line_categories, name='line_categories'),
]
