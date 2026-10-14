from django.db import migrations


def prefijos(apps, schema_editor):
    Propiedad = apps.get_model('maestro', 'Propiedad')
    for codigo, letra in (('boulevard', 'B'), ('plaza-motor', 'O')):  # la serie que ya usaban los contratos (B-01…, O-01…)
        Propiedad.objects.filter(codigo=codigo, prefijo='').update(prefijo=letra)


class Migration(migrations.Migration):
    dependencies = [('maestro', '0006_codigos_automaticos')]
    operations = [migrations.RunPython(prefijos, migrations.RunPython.noop)]
