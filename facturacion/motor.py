"""Motor de cálculo de rentas (puro: no toca la base de datos, para poder probarlo a fondo).

Reglas implementadas (confirmadas con el propietario, 07 a 09-10-2026):
  * Renta mensual por adelantado; UF del día 1 del mes (o del primer día hábil si el contrato lo dice).
  * El calendario de renta son tramos con fecha de inicio y término. Los períodos de gracia se
    modelan como tramos de 0. Cuando un tramo cambia a mitad de mes, la renta del mes se prorratea por días
    (modo PR; en modo IM se aplica la renta vigente el día 1 de cada mes).
  * El primer mes (y el último, si el contrato termina) se prorratea por días corridos.
  * Renta variable: en el mes M se factura el mínimo de M más la diferencia, si la hay, entre el variable
    del mes M-1 (% × ventas netas de M-1) y el mínimo facturado en M-1.
  * Renta en pesos semestral reajustada cada enero por el IPC acumulado del año anterior (Bimedia).
  * La fecha de la UF de un mes se puede fijar a mano en Facturación para toda la sociedad (incluso contratos «primer día hábil»).
  * Renovación automática: terminado el último tramo, se sigue cobrando esa misma renta (13-10-2026).
  * Descuentos por período (porcentaje, UF o pesos).
  * IVA 19% sobre el neto, redondeado al peso; facturas exentas y notas de cobro no llevan IVA.
Todo redondeo es «mitad hacia arriba» al peso.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Optional

D = Decimal
CUATRO = D('0.0001')
MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre',
         'Octubre', 'Noviembre', 'Diciembre']


class UFNoDisponible(Exception):
    pass


def peso(x) -> int:
    """Redondeo comercial al peso (mitad hacia arriba)."""
    return int(D(x).quantize(D('1'), rounding=ROUND_HALF_UP))


def q4(x) -> Decimal:
    return D(x).quantize(CUATRO, rounding=ROUND_HALF_UP)


def edate(d: date, meses: int) -> date:
    y = d.year + (d.month - 1 + meses) // 12
    m = (d.month - 1 + meses) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def mes_anterior(año: int, mes: int):
    return (año - 1, 12) if mes == 1 else (año, mes - 1)


def fmt_fecha(d: date) -> str:
    return d.strftime('%d-%m-%Y')


def fmt_clp(n) -> str:
    return '$' + f'{int(n):,}'.replace(',', '.')


def fmt_uf(x, dec=None) -> str:
    """Formato chileno (1.234,56). Sin `dec`: 2 decimales, o 4 si el valor los necesita."""
    x = D(x)
    if dec is None:
        dec = 2 if x == x.quantize(D('0.01')) else 4
    s = f'{x:,.{dec}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


# ----------------------------------------------------------------------------- datos de entrada
@dataclass(frozen=True)
class TramoD:
    desde: date
    hasta: Optional[date]
    monto: Optional[Decimal]
    unidad: str  # 'UF' | 'CLP'


@dataclass(frozen=True)
class DescuentoD:
    desde: date
    hasta: date
    tipo: str  # 'PCT' | 'UF' | 'CLP'
    valor: Decimal
    motivo: str = ''


@dataclass
class ContratoD:
    codigo: str
    inicio: date
    fin: Optional[date] = None  # término efectivo (anticipado)
    tramos: list = field(default_factory=list)
    descuentos: list = field(default_factory=list)
    periodicidad: str = 'M'  # 'M' mensual | 'S' semestral
    meses_cobro: list = field(default_factory=list)
    reajuste_ipc: bool = False
    pct_variable: Optional[Decimal] = None
    base_variable: str = ''  # 'V' ventas | 'I' ingresos
    variable_desde: Optional[date] = None  # la renta variable rige desde este día (None = siempre)
    modo_cambio: str = 'PR'  # 'PR' prorrata | 'IM' inicio de mes
    regla_uf: str = 'D1'  # 'D1' | 'PH'
    tipo_documento: str = 'FA'  # 'FA' | 'FE' | 'NC'
    renovacion_automatica: bool = False  # con prórroga: al terminar el último tramo se sigue cobrando esa renta
    inicio_cobro: Optional[date] = None
    fechas_uf: dict = field(default_factory=dict)  # {(año, mes): fecha} fecha de la UF elegida a mano para ese mes (manda sobre la regla)  # la renta se cobra desde este día (antes: no se cobra); None = según tramos


@dataclass
class LineaCalc:
    origen: str  # RENTA | RDIF | DESC
    concepto: str
    detalle: str
    unidad: str
    monto: Decimal  # en UF o en pesos antes de convertir
    valor_uf: Optional[Decimal]
    neto: int


@dataclass
class ResultadoMes:
    año: int
    mes: int
    lineas: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    notas: list = field(default_factory=list)
    valor_uf: Optional[Decimal] = None
    fecha_uf: Optional[date] = None

    @property
    def neto(self) -> int:
        return sum(l.neto for l in self.lineas)


# ----------------------------------------------------------------------------- utilidades de calendario
def fecha_uf_del_mes(c: ContratoD, año: int, mes: int, feriados=()) -> date:
    if (año, mes) in c.fechas_uf:   # fecha elegida en Facturación para toda la sociedad ese mes (decisión del propietario, 14-10-2026)
        return c.fechas_uf[(año, mes)]
    d = date(año, mes, 1)
    if c.regla_uf == 'PH':
        while d.weekday() >= 5 or d in feriados:
            d += timedelta(days=1)
    return d


def activo_en(c: ContratoD, d: date) -> bool:
    return d >= c.inicio and (c.fin is None or d <= c.fin)


def tramo_en(c: ContratoD, d: date) -> Optional[TramoD]:
    cand = [t for t in c.tramos if t.desde <= d and (t.hasta is None or d <= t.hasta)]
    if cand:
        return max(cand, key=lambda t: t.desde)
    if c.renovacion_automatica and c.tramos:
        # renovación automática (confirmado por el propietario, 13-10-2026): rige la renta del último tramo hasta que se cambie
        ultimo = max(c.tramos, key=lambda t: (t.hasta or date.max, t.desde))
        if ultimo.hasta and d > ultimo.hasta:
            return ultimo
    return None


def tramos_superpuestos(c: ContratoD, año: int, mes: int) -> list:
    """Advertencia si en el mes rigen a la vez dos tramos con montos distintos y la misma fecha «desde» (la más reciente):
    el sistema no puede saber cuál cobrar y no debe elegir uno en silencio."""
    for d in (date(año, mes, 1), date(año, mes, calendar.monthrange(año, mes)[1])):
        cand = [t for t in c.tramos if t.desde <= d and (t.hasta is None or d <= t.hasta)]
        if cand:   # rige el de «desde» más reciente (p. ej. un anexo que fija la renta de 2026); solo hay duda si empatan
            ultimo = max(t.desde for t in cand)
            cand = [t for t in cand if t.desde == ultimo]
        if len({(t.monto, t.unidad) for t in cand}) > 1:
            montos = ', '.join(f'{fmt_uf(t.monto)} UF' if t.unidad == 'UF' else fmt_clp(t.monto) for t in sorted(cand, key=lambda t: t.desde))
            return [f'Hay {len(cand)} tramos de renta vigentes a la vez el {fmt_fecha(d)} ({montos}): '
                    'corrija las fechas «desde/hasta» de los tramos del contrato antes de aprobar.']
    return []


def _rangos(dias: list) -> str:
    """Convierte [d1, d2, d3, d7] en '01-10-2026 a 03-10-2026 y 07-10-2026'."""
    if not dias:
        return ''
    bloques, ini, prev = [], dias[0], dias[0]
    for d in dias[1:]:
        if d == prev + timedelta(days=1):
            prev = d
            continue
        bloques.append((ini, prev))
        ini = prev = d
    bloques.append((ini, prev))
    return ' y '.join(fmt_fecha(a) if a == b else f'{fmt_fecha(a)} a {fmt_fecha(b)}' for a, b in bloques)


# ----------------------------------------------------------------------------- renta fija / mínimo del mes
def _monto_mes(c: ContratoD, año: int, mes: int):
    """Devuelve ({unidad: monto}, detalles{unidad: [texto]}, advertencias)."""
    n = calendar.monthrange(año, mes)[1]
    dias = [date(año, mes, i) for i in range(1, n + 1) if activo_en(c, date(año, mes, i))
            and (c.inicio_cobro is None or date(año, mes, i) >= c.inicio_cobro)]
    total, det, adv = {}, {}, []
    if not dias:
        return total, det, adv
    completo = len(dias) == n
    if c.modo_cambio == 'IM' and completo:
        t = tramo_en(c, date(año, mes, 1))
        grupos = [(t, dias)] if t else [(None, dias)]
        fraccion = lambda dd: D(1)  # mes completo con la renta del día 1
    else:
        grupos_d = {}
        for d in dias:
            grupos_d.setdefault(tramo_en(c, d), []).append(d)
        grupos = sorted(grupos_d.items(), key=lambda kv: kv[1][0])
        fraccion = lambda dd: D(len(dd)) / D(n)
    for t, dd in grupos:
        if t is None:
            adv.append(f'Sin tramo de renta vigente para {_rangos(dd)}: revisar el calendario de renta.')
            continue
        if t.monto is None:
            adv.append(f'Renta sin definir en el contrato para {_rangos(dd)}: completar el calendario de renta.')
            continue
        f = fraccion(dd)
        parte = q4(t.monto * f)
        total[t.unidad] = total.get(t.unidad, D(0)) + parte
        base = f'{fmt_uf(t.monto)} UF' if t.unidad == 'UF' else fmt_clp(t.monto)
        if f == 1:
            txt = f'{base} mes completo'
        else:
            txt = f'{base} × {len(dd)}/{n} días ({_rangos(dd)})'
        if t.monto != 0:
            det.setdefault(t.unidad, []).append(txt)
    return total, det, adv


def renta_base(c: ContratoD, año: int, mes: int, uf_fn: Callable[[date], Decimal], feriados=(),
               ipc_fn=None) -> ResultadoMes:
    """Líneas de renta (fija o mínimo) del mes `mes`, sin diferencia variable ni descuentos."""
    r = ResultadoMes(año, mes)
    if c.periodicidad == 'S':
        _renta_semestral(c, año, mes, r, ipc_fn)
        return r
    total, det, adv = _monto_mes(c, año, mes)
    r.advertencias += adv + tramos_superpuestos(c, año, mes)
    for unidad, monto in total.items():
        if monto == 0:
            r.notas.append('Renta del mes en 0: período de gracia o devengo aún no iniciado.')
            continue
        if unidad == 'UF':
            f_uf = fecha_uf_del_mes(c, año, mes, feriados)
            try:
                v = uf_fn(f_uf)
            except UFNoDisponible:
                r.advertencias.append(f'UF del {fmt_fecha(f_uf)} no disponible: no se puede calcular la renta en pesos.')
                continue
            r.valor_uf, r.fecha_uf = v, f_uf
            neto = peso(monto * v)
            r.lineas.append(LineaCalc('RENTA', 'ARRIENDO', f'{fmt_uf(monto)} UF ({"; ".join(det[unidad])}) × UF {fmt_uf(v)} del {fmt_fecha(f_uf)}',
                                      'UF', monto, v, neto))
        else:
            neto = peso(monto)
            r.lineas.append(LineaCalc('RENTA', 'ARRIENDO', f'{fmt_clp(neto)} ({"; ".join(det[unidad])})', 'CLP', monto, None, neto))
    return r


def _factor_ipc(c: ContratoD, año: int, mes: int, ipc_fn):
    """Factor acumulado de reajuste para el mes (año, mes): cada enero se aplica el IPC acumulado del año
    anterior. En el primer año de vigencia solo cuentan los meses desde el inicio del contrato."""
    faltan, factor = [], D(1)
    for y in range(c.inicio.year + 1, año + 1):
        acum = D(1)
        for m in range(1, 13):
            if y - 1 == c.inicio.year and m < c.inicio.month:
                continue
            v = ipc_fn(y - 1, m) if ipc_fn else None
            if v is None:
                faltan.append(f'{MESES[m]} {y - 1}')
            else:
                acum *= (1 + D(v) / 100)
        factor *= acum
    return factor, faltan


def _renta_semestral(c: ContratoD, año: int, mes: int, r: ResultadoMes, ipc_fn):
    n = calendar.monthrange(año, mes)[1]
    if mes not in c.meses_cobro:
        return
    if not any(activo_en(c, date(año, mes, i)) for i in range(1, n + 1)):
        return
    if c.inicio_cobro and c.inicio_cobro > date(año, mes, n):
        return
    t = tramo_en(c, date(año, mes, 1))
    if t is None or t.monto is None:
        r.advertencias.append('Renta semestral sin tramo definido para este mes.')
        return
    monto, txt = t.monto, f'{fmt_clp(t.monto)} por semestre'
    if c.reajuste_ipc:
        factor, faltan = _factor_ipc(c, año, mes, ipc_fn)
        if faltan:
            r.advertencias.append('IPC pendiente (' + ', '.join(faltan) + '): la renta se calculó sin ese reajuste; actualizar IPC y regenerar.')
        if factor != 1:
            monto = monto * factor
            txt += f' × factor IPC acumulado {factor:.6f}'
    neto = peso(monto)
    r.lineas.append(LineaCalc('RENTA', 'ARRIENDO', f'{txt} = {fmt_clp(neto)}', 'CLP', q4(monto), None, neto))


# ----------------------------------------------------------------------------- diferencia de renta variable
def diferencia_variable(c: ContratoD, año: int, mes: int, uf_fn, ventas_ant: Optional[Decimal], r: ResultadoMes, feriados=()):
    if not c.pct_variable or not c.base_variable:
        return
    a, m = mes_anterior(año, mes)
    if c.variable_desde and date(a, m, 1) < date(c.variable_desde.year, c.variable_desde.month, 1):
        return  # el mes anterior aún no tenía renta variable
    etiqueta = f'{MESES[m]} {a}'
    ant = renta_base(c, a, m, uf_fn, feriados)
    if not ant.lineas and not any(activo_en(c, date(a, m, i)) for i in range(1, calendar.monthrange(a, m)[1] + 1)):
        return  # el contrato aún no estaba vigente el mes anterior
    if ant.advertencias and not ant.lineas:
        r.advertencias.append(f'No se pudo calcular el mínimo de {etiqueta} para la diferencia variable: ' + ant.advertencias[0])
        return
    if ventas_ant is None:
        r.advertencias.append(f'Faltan las {"ventas" if c.base_variable == "V" else "ingresos"} netas de {etiqueta}: no se calculó la diferencia de renta variable.')
        return
    minimo = ant.neto
    variable = peso(D(ventas_ant) * c.pct_variable)
    pct_txt = f'{c.pct_variable * 100:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
    base = 'ventas netas' if c.base_variable == 'V' else 'ingresos netos'
    diff = variable - minimo
    texto = f'{pct_txt}% × {base} de {etiqueta} {fmt_clp(ventas_ant)} = {fmt_clp(variable)}; mínimo facturado en {etiqueta} {fmt_clp(minimo)}'
    if diff > 0:
        r.lineas.append(LineaCalc('RDIF', f'DIFERENCIA RENTA VARIABLE {etiqueta.upper()}', f'{texto}; diferencia {fmt_clp(diff)}',
                                  'CLP', D(diff), None, diff))
    else:
        r.notas.append(f'Sin diferencia de renta variable ({texto}: el variable no supera el mínimo).')


# ----------------------------------------------------------------------------- descuentos
def aplicar_descuentos(c: ContratoD, año: int, mes: int, r: ResultadoMes, uf_fn, feriados=()):
    n = calendar.monthrange(año, mes)[1]
    base_renta = sum(l.neto for l in r.lineas if l.origen == 'RENTA')
    for ds in c.descuentos:
        dias = sum(1 for i in range(1, n + 1) if ds.desde <= date(año, mes, i) <= ds.hasta)
        if not dias:
            continue
        frac = D(dias) / D(n)
        if ds.tipo == 'PCT':
            neto = -peso(D(base_renta) * ds.valor / 100 * (frac if dias < n else 1))
            det = f'{ds.valor}% de la renta del mes' + ('' if dias == n else f' por {dias}/{n} días')
        elif ds.tipo == 'UF':
            f_uf = fecha_uf_del_mes(c, año, mes, feriados)
            try:
                v = uf_fn(f_uf)
            except UFNoDisponible:
                r.advertencias.append('UF no disponible para calcular un descuento en UF.')
                continue
            neto = -peso(ds.valor * v * frac)
            det = f'{fmt_uf(ds.valor)} UF × UF {fmt_uf(v)}' + ('' if dias == n else f' por {dias}/{n} días')
        else:
            neto = -peso(ds.valor * frac)
            det = f'{fmt_clp(ds.valor)}' + ('' if dias == n else f' por {dias}/{n} días')
        if neto:
            r.lineas.append(LineaCalc('DESC', f'DESCUENTO {ds.motivo}'.strip(), det, 'CLP', D(neto), None, neto))


# ----------------------------------------------------------------------------- cálculo completo del mes
def calcular_mes(c: ContratoD, año: int, mes: int, uf_fn, ventas_ant=None, ipc_fn=None, feriados=()) -> ResultadoMes:
    r = renta_base(c, año, mes, uf_fn, feriados, ipc_fn)
    diferencia_variable(c, año, mes, uf_fn, ventas_ant, r, feriados)
    aplicar_descuentos(c, año, mes, r, uf_fn, feriados)
    return r


def totales(neto: int, tipo_documento: str, tasa=D('0.19')):
    """(neto_afecto, exento, iva, total)."""
    if tipo_documento == 'FA':
        iva = peso(D(neto) * tasa)
        return neto, 0, iva, neto + iva
    return 0, neto, 0, neto


def glosa(año: int, mes: int, valor_uf, fecha_uf) -> str:
    base = f'{MESES[mes]} {año}'
    if valor_uf and fecha_uf:
        base += f' · Valor de la UF {fmt_uf(valor_uf)} del {fecha_uf.strftime("%d/%m/%Y")}'
    return base


# ----------------------------------------------------------------------------- vencimientos y alertas
def vencimiento(c: ContratoD, plazo_meses: int, prorroga_meses: int, fin_pactado: Optional[date], hoy: date):
    """Fin del período vigente (plazo inicial o prórroga automática en curso)."""
    fin0 = fin_pactado or (edate(c.inicio, plazo_meses) - timedelta(days=1))
    if fin0 >= hoy or prorroga_meses == 0:
        return fin0, fin0, 0
    k = 0
    while True:
        e = edate(fin0 + timedelta(days=1), prorroga_meses * k) - timedelta(days=1)
        if e >= hoy:
            return fin0, e, k
        k += 1


def alertas(c: ContratoD, plazo_meses, prorroga_meses, fin_pactado, aviso_dias, hoy: date, horizonte=120):
    """Lista de (nivel, texto). nivel: ALTA | MEDIA | INFO."""
    out = []
    if c.fin and c.fin < hoy:
        return out
    fin0, vig, k = vencimiento(c, plazo_meses, prorroga_meses, fin_pactado, hoy)
    dias = (vig - hoy).days
    if aviso_dias is not None and prorroga_meses:
        limite = vig - timedelta(days=aviso_dias)
        if hoy > limite and dias >= 0:
            out.append(('ALTA' if dias <= 30 else 'MEDIA',
                        f'Vence el {fmt_fecha(vig)} (en {dias} días); el plazo de aviso de {aviso_dias} días venció el {fmt_fecha(limite)}: se renueva solo por {prorroga_meses} meses.'))
        elif 0 <= (limite - hoy).days <= horizonte:
            out.append(('ALTA' if (limite - hoy).days <= 30 else 'MEDIA',
                        f'Último día para avisar no renovación: {fmt_fecha(limite)} (en {(limite - hoy).days} días); vence el {fmt_fecha(vig)}.'))
    elif dias <= horizonte and dias >= 0:
        out.append(('ALTA' if dias <= 30 else 'MEDIA', f'Plazo fijo: vence el {fmt_fecha(vig)} (en {dias} días); sin renovación automática.'))
    for t in c.tramos:
        if t.monto is None and (t.hasta is None or t.hasta >= hoy):
            out.append(('MEDIA', f'Renta sin definir desde {fmt_fecha(t.desde)}.'))
        if hoy < t.desde <= hoy + timedelta(days=45) and t.monto is not None:
            out.append(('INFO', f'Cambio de renta el {fmt_fecha(t.desde)}: {fmt_uf(t.monto) if t.unidad == "UF" else fmt_clp(t.monto)} {"UF" if t.unidad == "UF" else ""}'.strip()))
    return out
