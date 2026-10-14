"""Protección contra textos más largos que su campo.

La base de la nube (PostgreSQL) rechaza un texto más largo que el máximo del campo y la pantalla termina en «Server Error 500»;
la base del Mac (SQLite) no lo controla, por eso esos errores no se veían al probar (caso real: n.º de cliente en la luz de Plaza
Motor, 2026-10-14). Antes de guardar cualquier registro del sistema, un texto demasiado largo se recorta (y queda anotado en el
registro del servidor). En las pruebas automáticas, en cambio, se lanza un error para descubrir el campo y agrandarlo."""
import logging

from django.conf import settings
from django.db import models
from django.db.models.signals import pre_save

APPS = {'maestro', 'facturacion', 'panel', 'indicadores'}
log = logging.getLogger(__name__)


class TextoMuyLargo(ValueError):
    pass


def ajustar(obj):
    for campo in obj._meta.concrete_fields:
        if not isinstance(campo, models.CharField) or not campo.max_length:
            continue
        v = getattr(obj, campo.attname)
        if isinstance(v, str) and len(v) > campo.max_length:
            msg = f'{obj._meta.label}.{campo.name}: {len(v)} caracteres (máximo {campo.max_length}): {v[:60]!r}…'
            if getattr(settings, 'PRUEBAS', False):
                raise TextoMuyLargo(msg)
            log.warning('Texto recortado en %s', msg)
            setattr(obj, campo.attname, v[:campo.max_length])
    return obj


def _antes_de_guardar(sender, instance, raw=False, **kwargs):
    if not raw and sender._meta.app_label in APPS:
        ajustar(instance)


def conectar():
    pre_save.connect(_antes_de_guardar, dispatch_uid='largos_antes_de_guardar')
