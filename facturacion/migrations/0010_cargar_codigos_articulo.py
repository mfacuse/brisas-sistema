"""Carga los códigos de artículo entregados por Matías (2026-10-15), iguales para todas las sociedades.
Reemplaza los códigos provisorios que había."""
from django.db import migrations

POR_ORIGEN = {'RENTA': ('111', 'ARRIENDO'), 'DESC': ('111', 'ARRIENDO (descuento)'), 'RDIF': ('333', 'ARRIENDO VARIABLE'),
              'AGUA': ('444', 'CONSUMO AGUA'), 'ELEC': ('555', 'ENERGIA ELECTRICA'), 'GAS': ('666', 'CONSUMO GAS'),
              'GGCC': ('777', 'GASTOS ADMINISTRATIVOS (gastos comunes)'), 'OTRO': ('999', 'VARIOS (habilitacion 222, gastos adm. 777 y equipamiento 888 segun concepto)')}


def cargar(apps, schema_editor):
    Sociedad = apps.get_model('maestro', 'Sociedad')
    Codigo = apps.get_model('facturacion', 'CodigoServicioBsoft')
    for soc in Sociedad.objects.all():
        for origen, (cod, nota) in POR_ORIGEN.items():
            Codigo.objects.update_or_create(sociedad=soc, origen=origen, defaults={'codigo': cod, 'nota': nota})


class Migration(migrations.Migration):
    dependencies = [('facturacion', '0009_codigos_articulo'), ('maestro', '0014_condicion_pago')]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
