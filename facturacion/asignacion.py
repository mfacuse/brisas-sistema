"""Asignación de las filas de las planillas de luz y gas a los contratos, con ayuda de la IA.

Los montos, lecturas y consumos los lee el sistema desde la planilla (lectores.py): la IA nunca calcula dinero.
La IA solo propone a qué contrato corresponde cada fila que no tiene un medidor confirmado; una persona revisa y confirma.
Lo confirmado queda como medidor confirmado y el mes siguiente se asigna solo."""
import json
import threading
from datetime import date
from decimal import Decimal as D

from django.conf import settings
from django.db import close_old_connections, transaction

from maestro import ia
from maestro.models import Contrato

from . import cargas, lectores as L
from .models import CargaPlanilla, MedidorServicio

NO_SE_COBRA = 'NO'


def _fila_json(f: L.FilaCargo) -> dict:
    s = lambda v: None if v is None else str(v)
    return dict(servicio=f.servicio, etiqueta=f.etiqueta_local or '', nombre=f.nombre or '', tarifa=f.tarifa or '',
                lectura_anterior=s(f.lectura_anterior), lectura_actual=s(f.lectura_actual), factor=s(f.factor), cantidad=s(f.cantidad),
                unidad=f.unidad or '', neto=str(f.neto), fila=f.fila, contrato='', fuente='', confianza='', motivo='')


def _fila_obj(d: dict) -> L.FilaCargo:
    n = lambda v: None if v in (None, '') else D(v)
    return L.FilaCargo(d['servicio'], d['etiqueta'], d['nombre'], d['tarifa'], n(d['lectura_anterior']), n(d['lectura_actual']),
                       n(d['factor']), n(d['cantidad']), d['unidad'], D(d['neto']), d['fila'])


def preparar(sociedad, servicio: str, filas, periodo_consumo: date, periodo_cobro: date, archivo: str, usuario: str) -> CargaPlanilla:
    """Guarda la planilla leída; asigna sola cada fila que calza con un medidor confirmado y pide a la IA el resto."""
    datos = []
    for f in filas:
        d = _fila_json(f)
        m = cargas._buscar_medidor(f)
        if m and m.confirmado:
            d.update(contrato=m.contrato.codigo, fuente='medidor confirmado', confianza='alta')
        elif m:
            d.update(contrato=m.contrato.codigo, fuente='medidor por confirmar', confianza='media')
        datos.append(d)
    carga = CargaPlanilla.objects.create(sociedad=sociedad, servicio=servicio, archivo=archivo[:255], periodo_consumo=periodo_consumo,
                                         periodo_cobro=periodo_cobro, filas=datos, subida_por=usuario)
    pendientes = [d for d in datos if not d['contrato'] and D(d['neto']) != 0]
    if pendientes and ia.clave_api():
        carga.estado = CargaPlanilla.Estado.ASIGNANDO
        carga.save()
        if ia.EN_SEGUNDO_PLANO:
            threading.Thread(target=asignar_con_ia, args=(carga.pk,), daemon=True).start()
        else:
            asignar_con_ia(carga.pk)
    return carga


ESQUEMA = ia._obj({'asignaciones': {'type': 'array', 'items': ia._obj({
    'fila': {'type': 'integer'},
    'contrato': {'type': 'string', 'description': 'código del contrato (de la lista), "NO" si la fila no se cobra a un arrendatario (área común, local vacío) o "" si no se puede saber'},
    'confianza': ia._enum('alta', 'media', 'baja'),
    'motivo': {'type': 'string', 'description': 'por qué, en una frase (número de local, nombre, ocupante anterior…)'},
})}})

INSTRUCCIONES = """Asignas las filas de la planilla mensual de electricidad, gas, agua o gastos comunes de un centro comercial en Talca (Chile) a los contratos de arriendo.
Cada fila trae el «Nº Local» (puede ser el número municipal, la designación del plano como L12, o el número de calle como 1225) y el nombre que
usa el proveedor (a veces es el nombre de fantasía, a veces el arrendatario, a veces un ocupante anterior del local).
Compara con los locales de cada contrato (código de plano, número municipal y designación), el nombre de fantasía y la razón social.
Si una fila corresponde a un área común, a la administración o a un local sin contrato, responde "NO". Si no se puede saber, deja "".
Usa «baja» cuando dudes: una persona revisará todo antes de cobrar."""


def _contratos_txt(sociedad):
    out = []
    for c in Contrato.objects.filter(sociedad=sociedad, activo=True).select_related('arrendatario').prefetch_related('locales'):
        out.append(dict(codigo=c.codigo, fantasia=c.nombre_fantasia, arrendatario=c.arrendatario.razon_social,
                        locales=[dict(plano=l.codigo_plano, municipal=l.numero_municipal, designacion=l.designacion) for l in c.locales.all()],
                        direccion=c.direccion_contrato))
    confirmados = [dict(local=m.etiqueta_local, nombre=m.nombre_planilla, contrato=m.contrato.codigo)
                   for m in MedidorServicio.objects.filter(confirmado=True, contrato__sociedad=sociedad).select_related('contrato')]
    return out, confirmados


def asignar_con_ia(carga_id: int, cliente=None):
    close_old_connections()
    carga = CargaPlanilla.objects.select_related('sociedad').get(pk=carga_id)
    try:
        contratos, confirmados = _contratos_txt(carga.sociedad)
        pendientes = [dict(fila=d['fila'], local=d['etiqueta'], nombre=d['nombre'], tarifa=d['tarifa'], consumo=d['cantidad'], neto=d['neto'])
                      for d in carga.filas if not d['contrato'] and D(d['neto']) != 0]
        nombres = {'ELEC': 'electricidad', 'GAS': 'gas', 'AGUA': 'agua', 'GGCC': 'gastos comunes'}
        texto = (f'Servicio: {nombres.get(carga.servicio, carga.servicio)}. Sociedad: {carga.sociedad.nombre}.\n'
                 f'Contratos: {json.dumps(contratos, ensure_ascii=False)}\n'
                 f'Medidores ya confirmados en meses anteriores (referencia): {json.dumps(confirmados, ensure_ascii=False)}\n'
                 f'Filas por asignar: {json.dumps(pendientes, ensure_ascii=False)}')
        datos, _, _, costo = ia._llamar_texto(cliente or ia._cliente(), settings.IA_MODELO, texto, ESQUEMA, INSTRUCCIONES)
        por_fila = {a['fila']: a for a in datos.get('asignaciones', [])}
        validos = set(Contrato.objects.filter(sociedad=carga.sociedad).values_list('codigo', flat=True))
        filas = carga.filas
        for d in filas:
            a = por_fila.get(d['fila'])
            if d['contrato'] or not a:
                continue
            cod = a.get('contrato', '')
            if cod == NO_SE_COBRA or cod in validos:
                d.update(contrato=cod, fuente='IA', confianza=a.get('confianza', ''), motivo=a.get('motivo', '')[:200])
            else:
                d.update(fuente='IA', confianza='baja', motivo=(a.get('motivo') or 'La IA no pudo asignarla')[:200])
        carga.filas, carga.costo_usd = filas, costo
    except Exception as e:
        carga.error_ia = ia._mensaje_error(e)
    carga.estado = CargaPlanilla.Estado.REVISAR
    carga.save()
    close_old_connections()
    return carga


@transaction.atomic
def confirmar(carga: CargaPlanilla, asignacion: dict, usuario: str):
    """asignacion = {fila: código de contrato | 'NO' | ''}. Guarda los medidores como confirmados y carga los cargos."""
    if carga.estado != CargaPlanilla.Estado.REVISAR:
        raise ValueError('Esta planilla ya no está pendiente.')
    contratos = {c.codigo: c for c in Contrato.objects.filter(sociedad=carga.sociedad)}
    a_cargar, sin_asignar, no_cobra = [], [], []
    for d in carga.filas:
        cod = asignacion.get(d['fila'], d['contrato'])
        f = _fila_obj(d)
        if f.neto == 0:
            a_cargar.append(f)   # cargar_filas las informa como «sin cobro»
            continue
        if cod == NO_SE_COBRA:
            no_cobra.append(d['nombre'])
            continue
        c = contratos.get(cod)
        if not c:
            sin_asignar.append(d)
            continue
        m, _ = MedidorServicio.objects.get_or_create(servicio=carga.servicio, etiqueta_local=d['etiqueta'][:60], nombre_planilla=d['nombre'][:80],
                                                     defaults=dict(contrato=c, tarifa=d['tarifa'][:10]))
        m.contrato, m.confirmado = c, True
        m.nota = (f'Confirmado por {usuario}' + (f' (propuesta de la IA: {d["motivo"]})' if d.get('fuente') == 'IA' else ''))[:200]
        m.save()
        a_cargar.append(f)
    if sin_asignar:
        raise ValueError('Faltan por asignar: ' + ', '.join(f'{d["etiqueta"]} {d["nombre"]}' for d in sin_asignar[:8])
                         + '. Elija el contrato o marque «no se cobra».')
    res = cargas.cargar_filas(a_cargar, carga.periodo_consumo, carga.periodo_cobro, carga.archivo)
    carga.estado = CargaPlanilla.Estado.CARGADA
    carga.resultado = (f'{res.cargados} cargos por ${int(res.total):,}'.replace(',', '.') + (f' · no se cobran: {", ".join(no_cobra)}' if no_cobra else '')
                       + (f' · sin cobro ($0): {", ".join(res.en_cero)}' if res.en_cero else '') + f' · confirmado por {usuario}')
    carga.save()
    return res
