from django.core.management.base import BaseCommand, CommandError

from facturacion import exportar

from ._comun import agregar_args, leer_periodo, sociedades


class Command(BaseCommand):
    help = 'Genera el Excel de facturación del mes por sociedad (documentos aprobados). Con --borradores incluye también borradores.'

    def add_arguments(self, p):
        agregar_args(p, con_codigos=False)
        p.add_argument('--borradores', action='store_true', help='incluir borradores (solo para revisar)')

    def handle(self, *a, **o):
        año, mes = leer_periodo(o['periodo'])
        estados = ('B', 'A', 'X') if o['borradores'] else ('A', 'X')
        for soc in sociedades(o['sociedad']):
            try:
                ruta = exportar.exportar_excel(soc, año, mes, estados=estados)
            except ValueError as e:
                raise CommandError(str(e))
            self.stdout.write(self.style.SUCCESS(f'{soc.nombre}: {ruta}'))
