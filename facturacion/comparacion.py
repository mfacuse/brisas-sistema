"""Comparación de los cargos de luz, gas y otros de cada local con los 3 meses anteriores, con semáforo (propietario, 13-10-2026):
verde si la variación del mes contra el anterior es de hasta 10 %, amarillo hasta 20 %, rojo sobre 20 %.
Luz y gas se comparan por consumo (kWh o litros) cuando ambos meses lo tienen; si no, y en «otros», por monto neto."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .models import ConsumoServicio

SERVICIOS = [('ELEC', 'Electricidad'), ('GAS', 'Gas'), ('OTRO', 'Otros')]


def mes_menos(p: date, n: int) -> date:
    m = p.month - n
    return date(p.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def semaforo(variacion):
    """None → sin comparación; |var| ≤ 10 % verde; ≤ 20 % amarillo; > 20 % rojo."""
    if variacion is None:
        return ''
    v = abs(variacion)
    return 'verde' if v <= 10 else ('amarillo' if v <= 20 else 'rojo')


@dataclass
class Mes:
    neto: int = 0
    cantidad: Decimal = None
    unidad: str = ''
    hay: bool = False


@dataclass
class Fila:
    contrato: object
    servicio: str
    nombre: str
    meses: list = field(default_factory=list)   # [M-3, M-2, M-1, M]
    variacion: Decimal = None
    base: str = ''                               # 'consumo' o 'monto'
    luz: str = ''


def comparar(sociedad, periodo: date):
    meses = [mes_menos(periodo, n) for n in (3, 2, 1, 0)]
    datos = {}
    for cs in ConsumoServicio.objects.filter(contrato__sociedad=sociedad, periodo_cobro__in=meses).select_related('contrato'):
        m = datos.setdefault((cs.contrato_id, cs.servicio), {'contrato': cs.contrato, 'meses': {p: Mes() for p in meses}})['meses'][cs.periodo_cobro]
        m.neto += int(cs.neto)
        m.hay = True
        if cs.cantidad is not None:
            m.cantidad = (m.cantidad or Decimal(0)) + cs.cantidad
            m.unidad = cs.unidad_consumo
    filas = []
    nombres = dict(SERVICIOS)
    for (_, serv), d in datos.items():
        f = Fila(d['contrato'], serv, nombres[serv], [d['meses'][p] for p in meses])
        ant, act = f.meses[2], f.meses[3]
        if act.hay and ant.hay:
            if serv != 'OTRO' and act.cantidad is not None and ant.cantidad:
                f.variacion, f.base = (act.cantidad - ant.cantidad) / ant.cantidad * 100, 'consumo'
            elif ant.neto:
                f.variacion, f.base = Decimal(act.neto - ant.neto) / Decimal(abs(ant.neto)) * 100, 'monto'
        f.variacion = f.variacion.quantize(Decimal('0.1')) if f.variacion is not None else None
        f.luz = semaforo(f.variacion)
        filas.append(f)
    orden = {s: i for i, (s, _) in enumerate(SERVICIOS)}
    filas.sort(key=lambda f: (f.contrato.codigo, orden[f.servicio]))
    return meses, filas
