from django.urls import path

from . import views

app_name = 'api_access'

urlpatterns = [
    path('', views.index, name='index'),
    path('mode/', views.mode_update, name='mode_update'),
    path('limits/', views.limits_update, name='limits_update'),
    path('rules/new/', views.rule_create, name='rule_create'),
    path('rules/<int:pk>/edit/', views.rule_edit, name='rule_edit'),
    path('rules/<int:pk>/toggle/', views.rule_toggle, name='rule_toggle'),
    path('rules/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
    path('test/', views.test_address, name='test'),
    path('refused/', views.decisions, name='decisions'),
    path('diagnostics/', views.diagnostics, name='diagnostics'),
    path('export/', views.export_rules, name='export'),
    path('import/', views.import_rules, name='import'),
]
