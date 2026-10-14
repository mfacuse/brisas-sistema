"""Prepara los datos para la nube: en una COPIA de la base, cambia las rutas del Mac por los identificadores de Google Drive
y exporta todo a un archivo .json que luego se carga en la base PostgreSQL de Render con `loaddata`.

Uso (nunca sobre la base de trabajo):
    sqlite3 db.sqlite3 ".backup '/tmp/copia.sqlite3'"
    DATABASE_URL=sqlite:////tmp/copia.sqlite3 python manage.py preparar_nube --salida /tmp/brisas_nube.json
"""
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from maestro import almacen


def id_drive(ruta: str) -> str:
    try:
        r = subprocess.run(['xattr', '-p', 'com.google.drivefs.item-id#S', ruta], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, p):
        p.add_argument('--salida', required=True, help='archivo .json a crear')

    def handle(self, *a, **o):
        nombre = Path(str(settings.DATABASES['default']['NAME'])).resolve()
        if nombre == (Path(settings.BASE_DIR) / 'db.sqlite3').resolve():
            raise CommandError('Esto modifica rutas: úselo solo sobre una COPIA de la base (DATABASE_URL=sqlite:////ruta/copia.sqlite3).')
        from facturacion.models import FacturaEmitida
        from maestro.models import ActaEntrega, ArchivoContrato, PlanoPiso, Propiedad, Sociedad
        faltan = []
        with transaction.atomic():
            def a_drive(ruta, quien):
                if not ruta or almacen.es_drive(ruta):
                    return ruta
                i = id_drive(ruta)
                if not i:
                    faltan.append(f'{quien}: {ruta}')
                    return ruta
                return almacen.PREFIJO + i
            for s in Sociedad.objects.all():
                for campo in ('carpeta_contratos', 'carpeta_actas', 'carpeta_facturas'):
                    setattr(s, campo, a_drive(getattr(s, campo), f'{s.nombre} · {campo}'))
                s.save()
            for p in Propiedad.objects.all():
                p.carpeta_planos = a_drive(p.carpeta_planos, f'{p.nombre} · planos')
                p.save()
            n = 0
            for modelo in (ArchivoContrato, ActaEntrega):
                for x in modelo.objects.exclude(ruta=''):
                    if not almacen.es_drive(x.ruta):
                        x.ruta = almacen.PREFIJO + x.drive_id if x.drive_id else a_drive(x.ruta, x.nombre)
                        x.save(update_fields=['ruta'])
                        n += 1
            for f in FacturaEmitida.objects.all():
                f.ruta = a_drive(f.ruta, f.nombre)
                f.save(update_fields=['ruta'])
            PlanoPiso.objects.all().delete()   # en la nube se vuelven a leer desde Drive
        if faltan:
            raise CommandError('Sin identificador de Drive (¿están fuera de Google Drive?):\n' + '\n'.join(faltan[:20]))
        with open(o['salida'], 'w', encoding='utf-8') as fh:
            call_command('dumpdata', '--natural-foreign', '--natural-primary', '--indent', '1',
                         exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'], stdout=fh)
        self.stdout.write(self.style.SUCCESS(f'{n} rutas de archivos pasadas a Google Drive. Datos exportados en {o["salida"]}.'))
