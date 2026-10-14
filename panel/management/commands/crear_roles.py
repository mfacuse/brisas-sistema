from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from panel.permisos import ROLES


class Command(BaseCommand):
    help = 'Crea los grupos de roles (Administrador, Operación, Contabilidad). Asigne usuarios a ellos en Admin → Usuarios.'

    def handle(self, *a, **o):
        for r in ROLES:
            _, nuevo = Group.objects.get_or_create(name=r)
            self.stdout.write(f'{"creado" if nuevo else "ya existía"}: {r}')
