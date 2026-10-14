"""Respaldo diario de toda la base en Google Drive (carpeta «Respaldos sistema Brisas» de Mi unidad, creada por el sistema).

Formato: JSON de Django comprimido (.json.gz), el mismo que usa la mudanza: se restaura en una base vacía con la pantalla
«Importar datos» (Carpetas y configuración). Se conservan las últimas CONSERVAR copias."""
import gzip
import io
from datetime import datetime

from django.core.management import call_command
from django.utils import timezone

from . import almacen

CONSERVAR = 60
EXCLUIR = ['contenttypes', 'auth.permission', 'sessions', 'admin.logentry']


def generar() -> bytes:
    buf = io.StringIO()
    call_command('dumpdata', '--natural-foreign', '--natural-primary', exclude=EXCLUIR, stdout=buf)
    return gzip.compress(buf.getvalue().encode('utf-8'))


def respaldar() -> dict:
    """Crea el respaldo y lo sube a Drive. Devuelve {fecha, nombre, kb, carpeta, borrados} y lo deja registrado."""
    ahora = timezone.localtime()
    try:
        if not almacen.puede_respaldar():
            raise RuntimeError('falta autorizar los respaldos: pulse «Volver a conectar Google Drive» en Carpetas y configuración')
        contenido = generar()
        carpeta = almacen.carpeta_respaldos()
        nombre = f'brisas_{ahora:%Y-%m-%d_%H%M}.json.gz'
        almacen.subir(carpeta, nombre, contenido)
        viejos = [f for f in almacen.archivos_de(carpeta) if f['name'].startswith('brisas_')][CONSERVAR:]
        for f in viejos:
            almacen.borrar(f['id'])
        r = {'fecha': ahora.isoformat(timespec='minutes'), 'nombre': nombre, 'kb': round(len(contenido) / 1024), 'carpeta': carpeta,
             'borrados': len(viejos), 'error': ''}
    except Exception as e:
        anterior = almacen.leer_dato('ultimo_respaldo') or {}
        r = dict(anterior, error=str(e)[:300], fecha_error=ahora.isoformat(timespec='minutes'))
        almacen.guardar_dato('ultimo_respaldo', r)
        raise
    almacen.guardar_dato('ultimo_respaldo', r)
    return r


def ultimo() -> dict:
    r = almacen.leer_dato('ultimo_respaldo') or {}
    if r.get('fecha'):
        r['fecha_dt'] = datetime.fromisoformat(r['fecha'])
    if r.get('fecha_error'):
        r['fecha_error_dt'] = datetime.fromisoformat(r['fecha_error'])
    return r
