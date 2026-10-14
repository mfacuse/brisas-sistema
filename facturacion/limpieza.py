"""Borrado de la facturación para volver a probar desde cero (pedido por Matías, 2026-10-14).

Borra documentos y sus líneas, numeración interna, facturas emitidas vinculadas, fechas de UF fijadas a mano, consumos de luz, gas,
agua, gastos comunes y «otros», y las planillas cargadas. Conserva contratos, medidores confirmados, ventas, UF/IPC y códigos BSOFT."""
from django.db import transaction

from maestro.historial import con_origen

from .models import CargaPlanilla, ConsumoServicio, Correlativo, Documento, FacturaEmitida, FechaUFMes, LineaDocumento


@transaction.atomic
def borrar_facturacion() -> dict:
    with con_origen('borrado de facturación'):
        cuenta = {'documentos': Documento.objects.count(), 'consumos y otros cargos': ConsumoServicio.objects.count(),
                  'planillas cargadas': CargaPlanilla.objects.count(), 'facturas emitidas': FacturaEmitida.objects.count()}
        FacturaEmitida.objects.all().delete()
        LineaDocumento.objects.all().delete()
        Documento.objects.all().delete()
        ConsumoServicio.objects.all().delete()
        CargaPlanilla.objects.all().delete()
        FechaUFMes.objects.all().delete()
        Correlativo.objects.all().delete()
    return cuenta
