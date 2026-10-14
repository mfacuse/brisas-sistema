from datetime import date

from django.core.management.base import BaseCommand

from facturacion import servicios


class Command(BaseCommand):
    help = 'Alertas de vencimiento, aviso de no renovación, fin de gracia y cambios de renta.'

    def add_arguments(self, p):
        p.add_argument('--horizonte', type=int, default=120, help='días hacia adelante (por defecto 120)')
        p.add_argument('--hoy', help='AAAA-MM-DD (para simular otra fecha)')

    def handle(self, *a, **o):
        hoy = date.fromisoformat(o['hoy']) if o['hoy'] else date.today()
        filas = servicios.alertas_vigentes(hoy, o['horizonte'])
        for cod, nombre, nivel, texto in filas:
            self.stdout.write(f'[{nivel:5}] {cod} {nombre}: {texto}')
        self.stdout.write(f'{len(filas)} alertas al {hoy:%d-%m-%Y}')
