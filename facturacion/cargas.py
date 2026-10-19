"""Carga de cargos adicionales (luz, gas, otros) a la base: asigna cada fila a un contrato y la deja lista para facturar."""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

from django.db import transaction

from maestro.models import Contrato

from . import lectores as L
from .medidores_iniciales import ELEC, GAS
from .models import CargaPlanilla, ConsumoServicio, MedidorServicio


def mes_siguiente(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@dataclass
class ResultadoCarga:
    cargados: int = 0
    total: D = D(0)
    sin_medidor: list = field(default_factory=list)   # filas que no se pudieron asignar
    en_cero: list = field(default_factory=list)       # filas sin cobro ($0) que se ignoraron
    por_confirmar: list = field(default_factory=list)  # medidores usados que aún no están confirmados
    reemplazados: int = 0
    anteriores: list = field(default_factory=list)    # cargos reemplazados, como foto_cargo()


def sembrar_medidores():
    """Crea los medidores iniciales de los contratos que existen (idempotente; no pisa lo confirmado ni lo editado).
    Los de contratos que aún no están en el sistema se crean en una carga posterior, cuando el contrato exista."""
    n = 0
    contratos = {c.codigo: c for c in Contrato.objects.all()}
    for servicio, tabla in (('ELEC', ELEC), ('GAS', GAS)):
        for etiqueta, nombre, tarifa, cod, nota in tabla:
            c = contratos.get(cod)
            if c is None:
                continue
            _, nuevo = MedidorServicio.objects.get_or_create(
                servicio=servicio, etiqueta_local=etiqueta, nombre_planilla=nombre,
                defaults=dict(contrato=c, tarifa=tarifa, nota=nota, confirmado=False))
            n += nuevo
    return n


def _buscar_medidor(fila: L.FilaCargo):
    qs = MedidorServicio.objects.filter(servicio=fila.servicio).select_related('contrato')
    nombre, etiqueta = L.norm(fila.nombre[:80]), L.norm(fila.etiqueta_local[:60])   # el medidor guarda los textos recortados al largo del campo
    for m in qs:
        if L.norm(m.nombre_planilla) == nombre and L.norm(m.etiqueta_local) == etiqueta:
            return m
    por_nombre = [m for m in qs if L.norm(m.nombre_planilla) == nombre]
    return por_nombre[0] if len(por_nombre) == 1 else None


def cargar_filas(filas, periodo_consumo: date, periodo_cobro: date, origen: str, reemplazar=True, carga=None) -> ResultadoCarga:
    """Guarda las filas de luz o gas. Si ya había cargas del mismo servicio, consumo y cobro, las reemplaza
    (así se puede volver a cargar una planilla corregida). Los reemplazados quedan en `res.anteriores` (para deshacer)."""
    res = ResultadoCarga()
    if reemplazar and filas:
        servicio = filas[0].servicio
        viejos = ConsumoServicio.objects.filter(servicio=servicio, periodo_consumo=periodo_consumo,
                                                periodo_cobro=periodo_cobro).exclude(origen_archivo__startswith='manual')
        res.anteriores = [foto_cargo(x) for x in viejos]
        res.reemplazados = viejos.delete()[0]
    for f in filas:
        neto = int(f.neto.quantize(D('1'), rounding=ROUND_HALF_UP))
        if neto == 0:
            res.en_cero.append(f.nombre)
            continue
        m = _buscar_medidor(f)
        if m is None:
            res.sin_medidor.append((f.nombre, f.etiqueta_local, neto, f.fila))
            continue
        ConsumoServicio.objects.create(
            contrato=m.contrato, servicio=f.servicio, medidor=(f.etiqueta_local or f.nombre)[:60], medidor_ref=m,
            periodo_consumo=periodo_consumo, periodo_cobro=periodo_cobro, lectura_anterior=f.lectura_anterior,
            lectura_actual=f.lectura_actual, factor=f.factor, cantidad=f.cantidad, unidad_consumo=(f.unidad or '')[:6], tarifa=(f.tarifa or '')[:40],
            neto=neto, origen_archivo=f'{origen} fila {f.fila}'[:120], carga=carga)
        res.cargados += 1
        res.total += neto
        if not m.confirmado and m.nombre_planilla not in res.por_confirmar:
            res.por_confirmar.append(m.nombre_planilla)
    return res


def cargar_otros(filas, origen: str, carga=None) -> ResultadoCarga:
    res = ResultadoCarga()
    for nfila, cod, concepto, detalle, neto, mes in filas:
        c = Contrato.objects.filter(codigo=cod).first()
        try:
            a, m = mes.split('-')
            cobro = date(int(a), int(m), 1)
        except Exception:
            res.sin_medidor.append((cod, f'fila {nfila}: mes de cobro «{mes}» inválido', 0, nfila))
            continue
        if c is None:
            res.sin_medidor.append((cod, f'fila {nfila}: contrato inexistente', 0, nfila))
            continue
        ConsumoServicio.objects.create(contrato=c, servicio='OTRO', concepto=concepto or 'OTRO CARGO', detalle=detalle,
                                       periodo_consumo=cobro, periodo_cobro=cobro, neto=int(neto.quantize(D('1'), rounding=ROUND_HALF_UP)),
                                       origen_archivo=f'{origen} fila {nfila}'[:120], carga=carga)
        res.cargados += 1
        res.total += neto
    return res


# ------------------------------------------------------------------ deshacer una carga
CAMPOS_CARGO = ('servicio', 'medidor', 'concepto', 'lectura_anterior', 'lectura_actual', 'factor', 'cantidad', 'unidad_consumo',
                'tarifa', 'detalle', 'neto', 'origen_archivo')


def foto_cargo(x: ConsumoServicio) -> dict:
    d = {k: (str(getattr(x, k)) if getattr(x, k) is not None else None) for k in CAMPOS_CARGO}
    d.update(contrato_id=x.contrato_id, medidor_ref_id=x.medidor_ref_id, carga_id=x.carga_id,
             periodo_consumo=x.periodo_consumo.isoformat(), periodo_cobro=x.periodo_cobro.isoformat())
    return d


def _cargos_de(carga):
    """Cargos que salieron de esta carga. Las anteriores a este cambio no guardaban el vínculo: se reconocen por archivo y mes."""
    qs = ConsumoServicio.objects.filter(carga=carga)
    if qs.exists() or carga.cargada_en:
        return qs
    viejos = ConsumoServicio.objects.filter(carga__isnull=True, contrato__sociedad=carga.sociedad, origen_archivo__startswith=f'{carga.archivo} fila ')
    if carga.servicio != 'OTRO':
        viejos = viejos.filter(servicio=carga.servicio, periodo_consumo=carga.periodo_consumo, periodo_cobro=carga.periodo_cobro)
    return viejos


def posterior(carga):
    """Otra carga confirmada después, del mismo servicio y meses, que ya reemplazó a esta (hay que deshacer esa primero)."""
    if carga.servicio == 'OTRO':
        return None
    return (CargaPlanilla.objects.filter(sociedad=carga.sociedad, servicio=carga.servicio, periodo_consumo=carga.periodo_consumo,
                                         periodo_cobro=carga.periodo_cobro, estado=CargaPlanilla.Estado.CARGADA, creada__gt=carga.creada)
            .exclude(pk=carga.pk).first())


def plan_deshacer(carga) -> dict:
    """{error} o {quitar: [cargos], vuelven: [fotos], aprobados: n.º de documentos ya aprobados o exportados que cambiarían}."""
    from .models import Documento
    if carga.estado != CargaPlanilla.Estado.CARGADA:
        return {'error': 'Esta carga no está confirmada: no hay nada que deshacer.'}
    otra = posterior(carga)
    if otra:
        return {'error': f'Después se cargó «{otra.archivo}» para el mismo servicio y mes, y reemplazó a esta. Deshaga primero esa.'}
    quitar = list(_cargos_de(carga).select_related('contrato'))
    vuelven = carga.antes or []
    contratos = {x.contrato_id for x in quitar} | {d['contrato_id'] for d in vuelven}
    periodos = {x.periodo_cobro for x in quitar} | {date.fromisoformat(d['periodo_cobro']) for d in vuelven}
    aprobados = Documento.objects.filter(contrato_id__in=contratos, periodo__in=periodos, estado__in=('A', 'X')).count()
    nombres = {c.pk: c for c in Contrato.objects.filter(pk__in={d['contrato_id'] for d in vuelven})}
    return {'quitar': quitar, 'vuelven': [dict(d, contrato=nombres.get(d['contrato_id']), cobro=date.fromisoformat(d['periodo_cobro'])) for d in vuelven], 'aprobados': aprobados,
            'total_quitar': sum(x.neto for x in quitar), 'total_vuelven': sum(int(d['neto']) for d in vuelven)}


@transaction.atomic
def deshacer(carga, usuario: str) -> dict:
    """Quita los cargos que dejó esta carga y devuelve los que había reemplazado. Los medidores confirmados se conservan."""
    plan = plan_deshacer(carga)
    if plan.get('error'):
        raise ValueError(plan['error'])
    for x in plan['quitar']:
        x.delete()
    existen = set(Contrato.objects.filter(pk__in={d['contrato_id'] for d in carga.antes or []}).values_list('pk', flat=True))
    vueltos = 0
    for d in carga.antes or []:
        if d['contrato_id'] not in existen:
            continue
        datos = {k: d[k] for k in CAMPOS_CARGO}
        for k in ('lectura_anterior', 'lectura_actual', 'factor', 'cantidad', 'neto'):
            datos[k] = D(datos[k]) if datos[k] is not None else None
        for k in ('medidor', 'concepto', 'unidad_consumo', 'tarifa', 'detalle', 'origen_archivo'):
            datos[k] = datos[k] or ''
        ConsumoServicio.objects.create(contrato_id=d['contrato_id'], periodo_consumo=date.fromisoformat(d['periodo_consumo']),
                                       periodo_cobro=date.fromisoformat(d['periodo_cobro']),
                                       medidor_ref=MedidorServicio.objects.filter(pk=d['medidor_ref_id']).first(),
                                       carga=CargaPlanilla.objects.filter(pk=d.get('carga_id')).first(), **datos)
        vueltos += 1
    carga.estado = CargaPlanilla.Estado.DESHECHA
    carga.resultado = f'{carga.resultado} · deshecha por {usuario or "sistema"}: se quitaron {len(plan["quitar"])} cargos' + (
        f' y volvieron {vueltos} de la carga anterior' if vueltos else '')
    carga.save()
    return dict(plan, vueltos=vueltos)
