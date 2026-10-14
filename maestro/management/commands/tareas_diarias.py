from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Tareas de cada día en la nube: UF e IPC, y revisión de carpetas de contratos, actas, planos y facturas emitidas'

    def handle(self, *a, **o):
        for comando in ('cargar_indicadores', 'revisar_carpetas'):
            try:
                call_command(comando, stdout=self.stdout, stderr=self.stderr)
            except Exception as e:   # una tarea que falla no detiene la otra
                self.stderr.write(f'{comando}: {e}')
