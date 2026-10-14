"""Roles: administrador (todo), operación (facturación, cargas, contratos), contabilidad (solo ver y descargar)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ROLES = ('Administrador', 'Operación', 'Contabilidad')


def rol(user) -> str:
    if user.is_superuser:
        return 'Administrador'
    nombres = set(user.groups.values_list('name', flat=True))
    for r in ROLES:
        if r in nombres:
            return r
    return 'Contabilidad'  # sin rol asignado: solo lectura


def puede_operar(user) -> bool:
    return rol(user) in ('Administrador', 'Operación')


def puede_forzar(user) -> bool:
    return rol(user) == 'Administrador'


def requiere_operacion(vista):
    @wraps(vista)
    @login_required
    def envuelta(request, *a, **k):
        if not puede_operar(request.user):
            raise PermissionDenied('Su rol solo permite consultar y descargar.')
        return vista(request, *a, **k)
    return envuelta
