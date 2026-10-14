"""Copia de seguridad de la base de datos (SQLite) a una carpeta, p. ej. la de Google Drive.

Usa la copia segura de SQLite (no daña la base aunque el sistema esté en uso) y conserva solo las últimas copias."""
import os
import sqlite3
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, p):
        p.add_argument('--destino', default=os.path.join(settings.BASE_DIR, 'respaldos'), help='carpeta donde dejar las copias')
        p.add_argument('--conservar', type=int, default=60, help='cuántas copias dejar (las más antiguas se borran)')

    def handle(self, *a, **o):
        db = settings.DATABASES['default']
        if 'sqlite' not in db['ENGINE']:
            raise CommandError('El respaldo automático es solo para SQLite; con PostgreSQL use pg_dump.')
        destino = o['destino']
        os.makedirs(destino, exist_ok=True)
        ruta = os.path.join(destino, f'brisas_{datetime.now():%Y-%m-%d_%H%M}.sqlite3')
        origen = sqlite3.connect(str(db['NAME']))
        copia = sqlite3.connect(ruta)
        with copia:
            origen.backup(copia)
        copia.close()
        origen.close()
        previas = sorted(f for f in os.listdir(destino) if f.startswith('brisas_') and f.endswith('.sqlite3'))
        for f in previas[:-o['conservar']] if o['conservar'] > 0 else []:
            os.remove(os.path.join(destino, f))
        self.stdout.write(self.style.SUCCESS(f'Respaldo guardado: {ruta}'))
