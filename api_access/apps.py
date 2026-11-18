from django.apps import AppConfig


class ApiAccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_access'
    verbose_name = 'API access control'
