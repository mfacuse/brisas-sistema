from django.core.management.base import BaseCommand

from facturacion import servicios

from ._comun import agregar_args, leer_periodo, sociedades


class Command(BaseCommand):
    help = 'Aprueba los borradores del mes. Los que tienen advertencias requieren --forzar.'

    def add_arguments(self, p):
        agregar_args(p)
        p.add_argument('--usuario', default='consola')
        p.add_argument('--forzar', action='store_true')

    def handle(self, *a, **o):
        año, mes = leer_periodo(o['periodo'])
        for soc in sociedades(o['sociedad']):
            ok, bloq = servicios.aprobar(soc, año, mes, o['usuario'], o['contratos'], o['forzar'])
            self.stdout.write(self.style.SUCCESS(f'{soc.nombre}: {len(ok)} aprobados'))
            for cod, adv in bloq:
                self.stdout.write(self.style.WARNING(f'   NO aprobado {cod}: ' + ' | '.join(adv)))
