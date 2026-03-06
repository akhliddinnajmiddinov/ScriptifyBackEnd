from django.apps import AppConfig


class ScriptsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scripts'

    def ready(self):
        import scripts.signals  # noqa
