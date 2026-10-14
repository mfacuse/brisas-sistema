from django.core.management.base import BaseCommand, CommandError

from facturacion import bsoft

from ._comun import agregar_args, leer_periodo, sociedades


class Command(BaseCommand):
    help = 'Genera los XML de importación de BSOFT (uno por factura) de los documentos aprobados del mes.'

    def add_arguments(self, p):
        agregar_args(p, con_codigos=False)
        p.add_argument('--borradores', action='store_true', help='incluir borradores (solo para probar)')

    def handle(self, *a, **o):
        año, mes = leer_periodo(o['periodo'])
        estados = ('B', 'A', 'X') if o['borradores'] else ('A', 'X')
        for soc in sociedades(o['sociedad']):
            try:
                carpeta, z, archivos = bsoft.exportar_xml(soc, año, mes, estados)
            except (ValueError, bsoft.FaltanCodigos) as e:
                self.stderr.write(self.style.ERROR(f'{soc.nombre}: {e}'))
                continue
            self.stdout.write(self.style.SUCCESS(f'{soc.nombre}: {len(archivos)} XML en {carpeta}\n   zip: {z}'))
