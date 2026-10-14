"""Datos de prueba para ensayar el flujo completo sin esperar a tener todos los datos reales.

Crea valores FICTICIOS de UF diaria e IPC (solo donde no hay datos reales) y ventas ficticias para los locales con renta
variable. Todo queda marcado como PRUEBA y se borra con `quitar_datos_prueba`; no pisa datos reales ni manuales."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.core.management.base import BaseCommand

from facturacion.models import VentaMensual
from indicadores.models import IPC, UF
from maestro.models import Contrato


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, p):
        p.add_argument('--hasta', default='2027-06-30', help='última fecha de UF de prueba (AAAA-MM-DD)')

    def handle(self, *a, **o):
        hasta = date.fromisoformat(o['hasta'])
        # UF: continúa desde el último valor real con +0,012 % diario (≈ 0,36 % mensual)
        ult = UF.objects.exclude(origen='PRUEBA').order_by('-fecha').first()
        if not ult:
            self.stderr.write('No hay ninguna UF real cargada; cargue una primero (UF / IPC).')
            return
        v, d, n = ult.valor, ult.fecha, 0
        while d < hasta:
            d += timedelta(days=1)
            v = (v * D('1.00012')).quantize(D('0.01'))
            if not UF.objects.filter(fecha=d).exists():
                UF.objects.create(fecha=d, valor=v, origen='PRUEBA')
                n += 1
        # IPC mensual de prueba para los meses sin dato real
        ni = 0
        for año in (2026, 2027):
            for mes in range(1, 13):
                if not IPC.objects.filter(anio=año, mes=mes).exists():
                    IPC.objects.create(anio=año, mes=mes, variacion_pct=D('0.30'), origen='PRUEBA')
                    ni += 1
        # Ventas ficticias para los locales con renta variable (ago–dic 2026)
        base = {'B-21': D('62000000'), 'B-36': D('690000000'), 'B-40': D('4500000')}
        nv = 0
        for cod, monto in base.items():
            c = Contrato.objects.filter(codigo=cod).first()
            if not c:
                continue
            for k, (a, m) in enumerate([(2026, 8), (2026, 9), (2026, 10), (2026, 11), (2026, 12)]):
                _, nuevo = VentaMensual.objects.get_or_create(
                    contrato=c, periodo=date(a, m, 1),
                    defaults={'monto_neto': (monto * (D(1) + D(k) * D('0.04'))).quantize(D('1')), 'fuente': 'PRUEBA'})
                nv += nuevo
        self.stdout.write(self.style.SUCCESS(f'Datos de prueba: {n} valores de UF, {ni} de IPC y {nv} ventas (todo marcado PRUEBA).'))
