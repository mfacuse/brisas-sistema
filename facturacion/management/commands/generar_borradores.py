from django.core.management.base import BaseCommand

from facturacion import servicios

from ._comun import agregar_args, leer_periodo, sociedades


class Command(BaseCommand):
    help = 'Calcula los borradores de factura del mes (reemplaza los borradores anteriores; no toca los aprobados).'

    def add_arguments(self, p):
        agregar_args(p)

    def handle(self, *a, **o):
        año, mes = leer_periodo(o['periodo'])
        for soc in sociedades(o['sociedad']):
            try:
                r = servicios.generar_borradores(soc, año, mes, o['contratos'])
            except Exception as e:  # UF no disponible, etc.
                self.stderr.write(self.style.ERROR(f'{soc.nombre}: {e}'))
                continue
            self.stdout.write(self.style.SUCCESS(f'{soc.nombre}: {len(r.creados)} borradores'
                                                 + (f' ({len(r.reemplazados)} reemplazados)' if r.reemplazados else '')))
            for cod, motivo in r.omitidos:
                self.stdout.write(f'   sin documento · {cod}: {motivo}')
            for cod, adv in r.con_advertencias:
                for t in adv:
                    self.stdout.write(self.style.WARNING(f'   ADVERTENCIA {cod}: {t}'))
