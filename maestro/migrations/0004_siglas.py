from django.db import migrations

SIGLAS = {'76.388.311-6': 'BT', '76.602.726-1': 'QO', '76363525-2': 'IC', '76.363.525-2': 'IC'}  # Boulevard Talca, 15 (Quince) Oriente, Camarico


def poner_siglas(apps, schema_editor):
    Sociedad = apps.get_model('maestro', 'Sociedad')
    for rut, sigla in SIGLAS.items():
        Sociedad.objects.filter(rut=rut, sigla='').update(sigla=sigla)


class Migration(migrations.Migration):
    dependencies = [('maestro', '0003_archivos_historial_ia')]
    operations = [migrations.RunPython(poner_siglas, migrations.RunPython.noop)]
