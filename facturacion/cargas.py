"""Carga de cargos adicionales (luz, gas, otros) a la base: asigna cada fila a un contrato y la deja lista para facturar."""
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

from maestro.models import Contrato

from . import lectores as L
from .medidores_iniciales import ELEC, GAS
from .models import ConsumoServicio, MedidorServicio


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
    for m in qs:
        if L.norm(m.nombre_planilla) == L.norm(fila.nombre) and L.norm(m.etiqueta_local) == L.norm(fila.etiqueta_local):
            return m
    por_nombre = [m for m in qs if L.norm(m.nombre_planilla) == L.norm(fila.nombre)]
    return por_nombre[0] if len(por_nombre) == 1 else None


def cargar_filas(filas, periodo_consumo: date, periodo_cobro: date, origen: str, reemplazar=True) -> ResultadoCarga:
    """Guarda las filas de luz o gas. Si ya había cargas del mismo servicio, consumo y cobro, las reemplaza
    (así se puede volver a cargar una planilla corregida)."""
    res = ResultadoCarga()
    if reemplazar and filas:
        servicio = filas[0].servicio
        res.reemplazados = ConsumoServicio.objects.filter(servicio=servicio, periodo_consumo=periodo_consumo,
                                                          periodo_cobro=periodo_cobro).exclude(origen_archivo__startswith='manual').delete()[0]
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
            neto=neto, origen_archivo=f'{origen} fila {f.fila}'[:120])
        res.cargados += 1
        res.total += neto
        if not m.confirmado and m.nombre_planilla not in res.por_confirmar:
            res.por_confirmar.append(m.nombre_planilla)
    return res


def cargar_otros(filas, origen: str) -> ResultadoCarga:
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
                                       origen_archivo=f'{origen} fila {nfila}'[:120])
        res.cargados += 1
        res.total += neto
    return res
