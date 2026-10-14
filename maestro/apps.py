from django.apps import AppConfig


class MaestroConfig(AppConfig):
    name = "maestro"

    def ready(self):
        from . import historial
        historial.conectar()
