"""Condiciones de pago como maestro (Matías, 2026-10-15): CONTADO, CRÉDITO, CRÉDITO 30 DÍAS, CRÉDITO 60 DÍAS.
Todos los contratos actuales quedan con CRÉDITO (el texto libre anterior se reemplaza)."""
import django.db.models.deletion
from django.db import migrations, models

INICIALES = [('CONTADO', 1), ('CRÉDITO', 2), ('CRÉDITO 30 DÍAS', 3), ('CRÉDITO 60 DÍAS', 4)]


def cargar(apps, schema_editor):
    Condicion = apps.get_model('maestro', 'CondicionPago')
    Contrato = apps.get_model('maestro', 'Contrato')
    for nombre, orden in INICIALES:
        Condicion.objects.get_or_create(nombre=nombre, defaults={'orden': orden})
    Contrato.objects.update(condicion_pago=Condicion.objects.get(nombre='CRÉDITO'))


class Migration(migrations.Migration):
    dependencies = [('maestro', '0014_condicion_pago')]
    operations = [
        migrations.CreateModel(
            name='CondicionPago',
            fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ('nombre', models.CharField(max_length=40, unique=True)),
                    ('orden', models.PositiveSmallIntegerField(default=0)),
                    ('activa', models.BooleanField(default=True))],
            options={'ordering': ['orden', 'nombre'], 'verbose_name': 'condición de pago', 'verbose_name_plural': 'condiciones de pago'}),
        migrations.RemoveField(model_name='contrato', name='condicion_pago'),
        migrations.AddField(model_name='contrato', name='condicion_pago', field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contratos', to='maestro.condicionpago',
            verbose_name='condición de pago', help_text='Va en la factura y en el Excel (por defecto CRÉDITO).')),
        migrations.RunPython(cargar, migrations.RunPython.noop),
    ]
