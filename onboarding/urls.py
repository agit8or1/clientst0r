from django.urls import path

from . import views

app_name = 'onboarding'

urlpatterns = [
    path('', views.start, name='start'),
    path('session/<int:pk>/', views.session_detail, name='session'),
    path('session/<int:pk>/step/<slug:key>/', views.step_view, name='step'),
    path('session/<int:pk>/step/<slug:key>/skip/', views.step_skip, name='skip'),
    path('session/<int:pk>/step/<slug:key>/reopen/', views.step_reopen, name='reopen'),
    path('session/<int:pk>/cancel/', views.session_cancel, name='cancel'),
]
