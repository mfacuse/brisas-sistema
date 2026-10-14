from django.core.management.base import BaseCommand
from django.utils import timezone

from indicadores import servicio


class Command(BaseCommand):
    help = 'Carga la UF diaria y el IPC mensual (Banco Central si hay token; si no, SII). Ejecutar a diario'

    def add_arguments(self, parser):
        parser.add_argument('--anio', type=int, nargs='*',
                            help='años a cargar (por defecto: el actual, más el anterior en enero y el siguiente en diciembre)')

    def handle(self, *a, **o):
        for año in o['anio'] or servicio.años_por_defecto(timezone.localdate()):
            for nombre, f in (('UF', servicio.cargar_uf_anio), ('IPC', servicio.cargar_ipc_anio)):
                try:
                    self.stdout.write(f'{nombre} {año}: {f(año)}')
                except servicio.AunNoPublicado:
                    self.stdout.write(f'{nombre} {año}: aún no publicado')
                except Exception as e:  # sin red o fuentes caídas
                    self.stderr.write(f'{nombre} {año}: no se pudo cargar ({e})')
