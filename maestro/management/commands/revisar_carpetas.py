from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from facturacion import emitidas
from maestro import carpetas
from maestro.models import PropuestaIA, Sociedad


class Command(BaseCommand):
    help = 'Revisa las carpetas de contratos (PDF nuevos, cambiados o eliminados) y de facturas emitidas de cada sociedad'

    def handle(self, *a, **o):
        # lecturas de la IA que quedaron a medias porque se apagó el sistema
        PropuestaIA.objects.filter(estado='P', creada__lt=timezone.now() - timedelta(minutes=20)).update(
            estado='E', error='Se interrumpió (el sistema se apagó mientras la IA leía). Vuelva a pedir la lectura.')
        from maestro import ia
        for r in carpetas.revisar_todas():
            self.stdout.write(f'Contratos · {r}')
        for s in Sociedad.objects.order_by('id'):
            # todos los PDF nuevos o cambiados se leen con la IA (aquí sin hilos: la tarea diaria termina al salir)
            n = ia.leer_pendientes(s, 'tarea diaria', segundo_plano=False)
            if n:
                self.stdout.write(f'IA · {s.nombre}: {n} archivo(s) leído(s); propuestas listas para revisar')
        from maestro.models import Sociedad
        for s in Sociedad.objects.order_by('id'):
            self.stdout.write(f'Actas · {carpetas.revisar_actas(s)}')
        from maestro import planos
        from maestro.models import Propiedad
        for p in Propiedad.objects.exclude(carpeta_planos=''):
            self.stdout.write(f'Planos · {planos.importar_propiedad(p)}')
        for r in emitidas.revisar_todas():
            self.stdout.write(f'Facturas emitidas · {r}')
