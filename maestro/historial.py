"""Historial automático de cambios: contratos, rentas, descuentos, garantías, locales asignados y configuración de sociedades.

Cada vez que se guarda o borra uno de esos registros (desde el panel, la administración de Django, el importador o una propuesta
de la IA) queda una fila en RegistroCambio con quién, cuándo, desde dónde y qué cambió (antes → después).
Quién y desde dónde lo fija `MiddlewareHistorial` en cada página, o `con_origen(...)` en comandos y tareas.
"""
import contextvars
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from django.db.models.signals import post_delete, post_save, pre_save

from . import models as m

_actual = contextvars.ContextVar('historial_origen', default=('', 'sistema'))

# modelo → (nombre legible, función que da el contrato, campos que no se registran)
SEGUIDOS = {
    m.Contrato: ('Contrato', lambda o: o, set()),
    m.TramoRenta: ('Tramo de renta', lambda o: o.contrato, set()),
    m.Descuento: ('Descuento', lambda o: o.contrato, set()),
    m.Garantia: ('Garantía', lambda o: o.contrato, set()),
    m.SaldoInformado: ('Saldo informado', lambda o: o.contrato, set()),
    m.ContratoLocal: ('Local del contrato', lambda o: o.contrato, set()),
    m.Sociedad: ('Sociedad', lambda o: None, set()),
    m.ActaEntrega: ('Acta de entrega', lambda o: o.contrato, {'datos'}),
}


@contextmanager
def con_origen(origen: str, usuario: str = ''):
    """Marca los cambios hechos dentro del bloque: with con_origen('importador'): ..."""
    tok = _actual.set((usuario, origen))
    try:
        yield
    finally:
        _actual.reset(tok)


class MiddlewareHistorial:
    """Registra el usuario de cada página; la administración de Django queda como origen «administración»."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = request.user.get_username() if getattr(request, 'user', None) and request.user.is_authenticated else ''
        origen = 'administración' if request.path.startswith('/admin/') else 'panel'
        with con_origen(origen, usuario):
            return self.get_response(request)


def _txt(v):
    if v is None:
        return ''
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v.normalize(), 'f') if v == v.to_integral() else str(v)
    return str(v)


def _valores(obj, excluir):
    out = {}
    for f in obj._meta.concrete_fields:
        if f.primary_key or f.name in excluir:
            continue
        out[f.verbose_name if f.name not in ('desde', 'hasta') else f.name] = _txt(getattr(obj, f.attname))
    return out


def _registrar(obj, accion, cambios, nota=''):
    nombre, fn_contrato, _ = SEGUIDOS[type(obj)]
    usuario, origen = _actual.get()
    contrato = fn_contrato(obj)
    if contrato is not None and not m.Contrato.objects.filter(pk=contrato.pk).exists():
        contrato = None
    m.RegistroCambio.objects.create(usuario=usuario, origen=origen, contrato=contrato, objeto=nombre, objeto_id=str(obj.pk or ''),
                                    descripcion=str(obj)[:200], accion=accion, cambios=cambios, nota=nota[:300])


def _antes(sender, instance, raw=False, **kw):
    if raw or sender not in SEGUIDOS:
        return
    previo = sender.objects.filter(pk=instance.pk).first() if instance.pk else None
    instance._historial_antes = _valores(previo, SEGUIDOS[sender][2]) if previo else None


def _despues(sender, instance, created, raw=False, **kw):
    if raw or sender not in SEGUIDOS:
        return
    ahora = _valores(instance, SEGUIDOS[sender][2])
    antes = getattr(instance, '_historial_antes', None)
    if created or antes is None:
        _registrar(instance, 'creado', {k: ['', v] for k, v in ahora.items() if v != ''})
        return
    cambios = {k: [antes.get(k, ''), v] for k, v in ahora.items() if antes.get(k, '') != v}
    if cambios:
        _registrar(instance, 'modificado', cambios)


def _borrado(sender, instance, **kw):
    if sender not in SEGUIDOS:
        return
    _registrar(instance, 'eliminado', {k: [v, ''] for k, v in _valores(instance, SEGUIDOS[sender][2]).items() if v != ''})


def conectar():
    for modelo in SEGUIDOS:
        pre_save.connect(_antes, sender=modelo, dispatch_uid=f'hist_pre_{modelo.__name__}')
        post_save.connect(_despues, sender=modelo, dispatch_uid=f'hist_post_{modelo.__name__}')
        post_delete.connect(_borrado, sender=modelo, dispatch_uid=f'hist_del_{modelo.__name__}')
