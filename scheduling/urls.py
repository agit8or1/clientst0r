from django.urls import path
from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.scheduling_dashboard, name='scheduling_dashboard'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/create/', views.task_create, name='task_create'),
    path('tasks/<int:pk>/', views.task_detail, name='task_detail'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/delete/', views.task_delete, name='task_delete'),
    path('tasks/<int:pk>/sign-off/', views.task_sign_off, name='task_sign_off'),
    path('tasks/<int:pk>/complete/', views.task_complete, name='task_complete'),
    path('tasks/<int:pk>/cancel/', views.task_cancel, name='task_cancel'),
    path('tasks/<int:pk>/spawn/', views.task_spawn_next, name='task_spawn_next'),
    path('my-tasks/', views.my_tasks, name='my_tasks'),
    path('overdue/', views.overdue_tasks, name='overdue_tasks'),
    path('calendar/', views.task_calendar, name='task_calendar'),
    # Phase 47 (v3.17.533) — wall-mounted schedule board.
    # The public route carries a random token instead of an org id, so boards
    # cannot be enumerated; it is unauthenticated by design.
    path('wallboard/', views.wallboard_settings, name='wallboard_settings'),
    path('wallboard/<str:token>/', views.wallboard_public, name='wallboard_public'),
]
