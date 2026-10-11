from django.apps import AppConfig


class MasterdataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'masterdata'
    verbose_name = 'Мастер-данные'

    def ready(self):
        from . import signals  # noqa: F401
