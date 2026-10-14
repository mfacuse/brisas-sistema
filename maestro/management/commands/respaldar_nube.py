from django.core.management.base import BaseCommand, CommandError

from maestro import respaldos


class Command(BaseCommand):
    help = 'Respaldo completo de la base en Google Drive (carpeta «Respaldos sistema Brisas»); conserva los últimos 60'

    def handle(self, *a, **o):
        try:
            r = respaldos.respaldar()
        except Exception as e:
            raise CommandError(f'No se pudo respaldar: {e}')
        self.stdout.write(self.style.SUCCESS(f'Respaldo {r["nombre"]} ({r["kb"]} KB) en Google Drive.'
                                             + (f' Se borraron {r["borrados"]} copias antiguas.' if r['borrados'] else '')))
