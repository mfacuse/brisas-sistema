"""Utilidades comunes de los comandos de facturación."""
from django.core.management.base import CommandError

from maestro.models import Sociedad


def agregar_args(p, con_codigos=True):
    p.add_argument('periodo', help='mes a facturar, formato AAAA-MM (ej.: 2026-11)')
    p.add_argument('--sociedad', default='todas', help='parte del nombre o RUT de la sociedad (por defecto: todas)')
    if con_codigos:
        p.add_argument('--contratos', nargs='*', help='solo estos códigos (ej.: B-07 B-11)')


def leer_periodo(txt):
    try:
        a, m = txt.split('-')
        a, m = int(a), int(m)
        assert 2000 < a < 2100 and 1 <= m <= 12
        return a, m
    except Exception:
        raise CommandError(f'Período inválido «{txt}»; use AAAA-MM, por ejemplo 2026-11.')


def sociedades(filtro):
    qs = Sociedad.objects.all()
    if filtro and filtro.lower() != 'todas':
        qs = [s for s in qs if filtro.lower() in s.nombre.lower() or filtro in s.rut]
        if not qs:
            raise CommandError(f'No hay sociedad que coincida con «{filtro}».')
    return list(qs)
