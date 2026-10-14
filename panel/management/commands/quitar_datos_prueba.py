from django.core.management.base import BaseCommand

from facturacion.models import VentaMensual
from indicadores.models import IPC, UF


class Command(BaseCommand):
    help = 'Borra la UF, el IPC y las ventas marcados como PRUEBA (los datos reales no se tocan).'

    def handle(self, *a, **o):
        n1 = UF.objects.filter(origen='PRUEBA').delete()[0]
        n2 = IPC.objects.filter(origen='PRUEBA').delete()[0]
        n3 = VentaMensual.objects.filter(fuente='PRUEBA').delete()[0]
        self.stdout.write(self.style.SUCCESS(f'Borrados: {n1} UF, {n2} IPC, {n3} ventas de prueba.'))
