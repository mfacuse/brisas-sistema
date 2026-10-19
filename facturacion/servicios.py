"""Conecta el motor de rentas con la base de datos: borradores, aprobación y alertas."""
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from indicadores import servicio as ind
from maestro import largos
from maestro.models import CondicionPago, Contrato

from . import motor
from .models import ConsumoServicio, Correlativo, Documento, FechaUFMes, LineaDocumento, VentaMensual

D = Decimal


def a_contrato_d(c: Contrato) -> motor.ContratoD:
    return motor.ContratoD(
        codigo=c.codigo, inicio=c.inicio_vigencia, fin=c.fecha_termino_real,
        tramos=[motor.TramoD(t.desde, t.hasta, t.monto, t.unidad) for t in c.tramos.all()],
        descuentos=[motor.DescuentoD(d.desde, d.hasta, d.tipo, d.valor, d.motivo) for d in c.descuentos.all()],
        periodicidad=c.periodicidad, meses_cobro=c.meses_cobro_lista, reajuste_ipc=c.reajuste_ipc,
        pct_variable=c.pct_variable, base_variable=c.base_variable, variable_desde=c.variable_desde, modo_cambio=c.modo_cambio_tramo,
        regla_uf=c.regla_uf, tipo_documento=c.tipo_documento, inicio_cobro=c.fecha_inicio_cobro,
        renovacion_automatica=bool(c.prorroga_meses),
        fechas_uf={(f.periodo.year, f.periodo.month): f.fecha for f in FechaUFMes.objects.filter(sociedad_id=c.sociedad_id)})


def _ventas_mes_anterior(c: Contrato, año: int, mes: int):
    a, m = motor.mes_anterior(año, mes)
    v = VentaMensual.objects.filter(contrato=c, periodo=date(a, m, 1)).first()
    return v.monto_neto if v else None


def _num(x, dec=2):
    """Formato chileno: 12.345,67 (sin decimales sobrantes)."""
    t = f'{D(x):,.{dec}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return t.rstrip('0').rstrip(',') if dec and ',' in t else t


CONCEPTOS = {'ELEC': 'ENERGIA ELECTRICA', 'GAS': 'GAS', 'AGUA': 'AGUA', 'GGCC': 'GASTOS COMUNES'}


def linea_consumo(cs: ConsumoServicio) -> motor.LineaCalc:
    """Línea de factura para un cargo de luz, gas u otro (siempre a costo, en pesos netos)."""
    mes = f'{motor.MESES[cs.periodo_consumo.month]} {cs.periodo_consumo.year}'
    if cs.servicio == 'OTRO':
        return motor.LineaCalc('OTRO', (cs.concepto or 'OTRO CARGO').upper(), cs.detalle or '', 'CLP', D(cs.neto), None, int(cs.neto))
    concepto = CONCEPTOS[cs.servicio]
    partes = [f'{"Gastos comunes" if cs.servicio == "GGCC" else "Consumo"} de {mes}']
    if cs.medidor and cs.servicio != 'GGCC':   # gastos comunes no tienen medidor (lo de la planilla es el n.º de local)
        partes.append(f'medidor {cs.medidor}')
    if cs.lectura_anterior is not None and cs.lectura_actual is not None:
        txt = f'lectura {_num(cs.lectura_anterior, 0)} → {_num(cs.lectura_actual, 0)}'
        if cs.factor and cs.factor != 1:
            txt += f' × {_num(cs.factor, 3)}'
        partes.append(txt)
    if cs.cantidad is not None:
        partes.append(f'{_num(cs.cantidad)} {cs.unidad_consumo}'.strip())
    if cs.detalle:
        partes.append(cs.detalle)
    if cs.servicio != 'GGCC':
        partes.append('a costo')
    return motor.LineaCalc(cs.servicio, concepto, ' · '.join(partes), 'CLP', D(cs.neto), None, int(cs.neto))


@dataclass
class ResumenGeneracion:
    creados: list = field(default_factory=list)
    reemplazados: list = field(default_factory=list)
    omitidos: list = field(default_factory=list)  # (codigo, motivo)
    con_advertencias: list = field(default_factory=list)  # (codigo, [textos])


def contratos_del_mes(sociedad, año: int, mes: int):
    primero, ultimo = date(año, mes, 1), date(año, mes, calendar.monthrange(año, mes)[1])
    return (Contrato.objects.filter(sociedad=sociedad, activo=True, inicio_vigencia__lte=ultimo)
            .filter(Q(fecha_termino_real__isnull=True) | Q(fecha_termino_real__gte=primero))
            .prefetch_related('tramos', 'descuentos').order_by('codigo'))


def calcular_contrato(c: Contrato, año: int, mes: int, feriados=()):
    """Calcula (sin guardar) todas las líneas de la factura de un contrato para un mes: renta, diferencia variable,
    descuentos y los cargos adicionales (luz, gas, otros). Devuelve (ResultadoMes, [LineaCalc])."""
    periodo = date(año, mes, 1)
    r = motor.calcular_mes(a_contrato_d(c), año, mes, ind.valor_uf, _ventas_mes_anterior(c, año, mes), ind.variacion_ipc, feriados)
    lineas = list(r.lineas)
    if c.regla_inicio_cobro and not c.fecha_inicio_cobro:
        r.advertencias.append('Falta el inicio de cobro de la renta: registre la fecha de entrega o de apertura (o el inicio de cobro a mano).')
    elif c.fecha_inicio_cobro and c.fecha_inicio_cobro > date(año, mes, calendar.monthrange(año, mes)[1]):
        r.notas.append(f'La renta se cobra desde el {c.fecha_inicio_cobro:%d-%m-%Y}.')
    for cs in ConsumoServicio.objects.filter(contrato=c, periodo_cobro=periodo).select_related('medidor_ref').order_by('servicio', 'medidor', 'id'):
        if not c.cobra_inmobiliaria(cs.servicio):
            # cargado antes de marcar el contrato como «lo cobra Megaservicios»: no se incluye
            quien = 'lo cobra Megaservicios' if c.quien_cobra(cs.servicio) == 'MEGA' else 'el contrato dice que no se cobra'
            r.notas.append(f'{cs.get_servicio_display()} cargado pero {quien}: no va en esta factura.')
            continue
        lineas.append(linea_consumo(cs))
        if cs.medidor_ref and not cs.medidor_ref.confirmado:
            r.advertencias.append(f'Medidor «{cs.medidor_ref.nombre_planilla}» ({cs.get_servicio_display().lower()}) asignado a este contrato por confirmar.')
    return r, lineas


@transaction.atomic
def generar_borradores(sociedad, año: int, mes: int, codigos=None, feriados=()) -> ResumenGeneracion:
    res = ResumenGeneracion()
    periodo = date(año, mes, 1)
    tasa = D(str(getattr(settings, 'TASA_IVA', '0.19')))
    qs = contratos_del_mes(sociedad, año, mes)
    if codigos:
        qs = qs.filter(codigo__in=codigos)
    for c in qs:
        previo = Documento.objects.filter(contrato=c, periodo=periodo).exclude(estado=Documento.Estado.ANULADO).first()
        if previo and previo.estado != Documento.Estado.BORRADOR:
            res.omitidos.append((c.codigo, f'ya existe un documento {previo.get_estado_display().lower()}'))
            continue
        r, lineas = calcular_contrato(c, año, mes, feriados)
        numero_previo = (previo.numero_interno, previo.tipo_documento) if previo else ('', '')
        if previo:
            previo.delete()
            res.reemplazados.append(c.codigo)
        if not lineas:
            motivo = '; '.join(r.notas + r.advertencias) or 'sin cargos en el mes'
            res.omitidos.append((c.codigo, motivo))
            if r.advertencias:
                res.con_advertencias.append((c.codigo, r.advertencias))
            continue
        neto = sum(l.neto for l in lineas)
        afecto, exento, iva, total = motor.totales(neto, c.tipo_documento, tasa)
        doc = Documento.objects.create(
            contrato=c, periodo=periodo, tipo_documento=c.tipo_documento, valor_uf=r.valor_uf, fecha_uf=r.fecha_uf,
            condicion_pago=str(c.condicion_pago or CondicionPago.POR_DEFECTO),
            glosa=motor.glosa(año, mes, r.valor_uf, r.fecha_uf), neto=afecto, exento=exento, iva=iva, total=total,
            advertencias=r.advertencias + [f'Nota: {n}' for n in r.notas if 'diferencia de renta variable' in n.lower()],
            # un número ya asignado (aprobado y vuelto a borrador) se conserva para no dejar saltos en la numeración
            numero_interno=numero_previo[0] if serie(numero_previo[1]) == serie(c.tipo_documento) else '')
        orig = {k: k for k in ('RENTA', 'RDIF', 'DESC', 'ELEC', 'GAS', 'AGUA', 'GGCC', 'OTRO')}
        LineaDocumento.objects.bulk_create([largos.ajustar(x) for x in [
            LineaDocumento(documento=doc, orden=i + 1, origen=orig[l.origen], concepto=l.concepto, detalle=l.detalle, unidad=l.unidad,
                           cantidad_unidad=l.monto, valor_uf=l.valor_uf, neto=l.neto, exento=(c.tipo_documento != 'FA'))
            for i, l in enumerate(lineas)]])
        res.creados.append(c.codigo)
        if r.advertencias:
            res.con_advertencias.append((c.codigo, r.advertencias))
    return res


def aprobar(sociedad, año: int, mes: int, usuario: str, codigos=None, forzar=False):
    """Aprueba los borradores del mes. Los que tienen advertencias exigen `forzar`."""
    periodo = date(año, mes, 1)
    qs = Documento.objects.filter(contrato__sociedad=sociedad, periodo=periodo, estado=Documento.Estado.BORRADOR)
    if codigos:
        qs = qs.filter(contrato__codigo__in=codigos)
    ok, bloqueados = [], []
    for d in qs:
        graves = [a for a in d.advertencias if not a.startswith('Nota:')]
        if graves and not forzar:
            bloqueados.append((d.contrato.codigo, graves))
            continue
        marcar_aprobado(d, usuario)
        ok.append(d.contrato.codigo)
    return ok, bloqueados


# ------------------------------------------------------------------ numeración interna
def serie(tipo_documento: str) -> str:
    """F = facturas (afectas y exentas, el folio oficial lo da el SII); NC = notas de cobro (su número es el oficial)."""
    return 'NC' if tipo_documento == 'NC' else ('F' if tipo_documento else '')


def sigla(sociedad) -> str:
    if sociedad.sigla:
        return sociedad.sigla.upper()
    comunes = {'inmobiliaria', 'inversiones', 'spa', 'ltda', 'ltda.', 's.a.', 'sa', 'de', 'del', 'la', 'y'}
    letras = ''.join(p[0] for p in sociedad.nombre.split() if p.lower() not in comunes and p[0].isalnum())
    return (letras[:4] or f'S{sociedad.pk}').upper()


@transaction.atomic
def asignar_numero(doc: Documento) -> str:
    """Número interno correlativo por sociedad y serie (BT-F-0001, BT-NC-0001). Se asigna una vez y no se reutiliza."""
    if doc.numero_interno:
        return doc.numero_interno
    soc = doc.contrato.sociedad
    s = serie(doc.tipo_documento)
    corr, _ = Correlativo.objects.select_for_update().get_or_create(sociedad=soc, serie=s)
    corr.ultimo += 1
    corr.save()
    doc.numero_interno = f'{sigla(soc)}-{s}-{corr.ultimo:04d}'
    return doc.numero_interno


@transaction.atomic
def marcar_aprobado(doc: Documento, usuario: str):
    doc.estado = Documento.Estado.APROBADO
    doc.aprobado_por, doc.aprobado_en = usuario, datetime.now(timezone.utc)
    asignar_numero(doc)
    doc.save()


def alertas_vigentes(hoy: date, horizonte=120, sociedad=None):
    """[(codigo, fantasia, nivel, texto)] para todos los contratos vigentes."""
    out = []
    qs = Contrato.objects.filter(activo=True).prefetch_related('tramos', 'descuentos').select_related('arrendatario')
    if sociedad:
        qs = qs.filter(sociedad=sociedad)
    for c in qs:
        for nivel, texto in motor.alertas(a_contrato_d(c), c.plazo_meses, c.prorroga_meses, c.fin_pactado, c.aviso_dias, hoy, horizonte):
            out.append((c.codigo, c.nombre_fantasia, nivel, texto))
    out += archivos_borrados_con_cambios(sociedad)
    orden = {'ALTA': 0, 'MEDIA': 1, 'INFO': 2}
    return sorted(out, key=lambda x: (orden[x[2]], x[0]))


def archivos_borrados_con_cambios(sociedad=None):
    """PDF de contratos y actas que ya no están en su carpeta, pero lo que se aplicó desde ellos sigue en el contrato."""
    from maestro.models import ActaEntrega, PropuestaIA
    props = PropuestaIA.objects.filter(estado='A', archivo__estado='E', contrato__isnull=False).select_related('archivo', 'contrato')
    actas = ActaEntrega.objects.filter(estado='R', ya_no_esta=True, contrato__isnull=False).select_related('contrato')
    if sociedad:
        props, actas = props.filter(contrato__sociedad=sociedad), actas.filter(contrato__sociedad=sociedad)
    out = [(p.contrato.codigo, p.contrato.nombre_fantasia, 'ALTA',
            f'«{p.archivo.nombre}» ya no está en la carpeta, pero sus cambios siguen en el contrato. Si no corresponde: '
            'Contratos › Archivos de contratos › «Deshacer sus cambios».') for p in props]
    out += [(a.contrato.codigo, a.contrato.nombre_fantasia, 'ALTA',
             f'El acta «{a.nombre}» ya no está en la carpeta, pero su fecha de entrega sigue en el contrato. Si no corresponde: '
             'ábrala en Actas de entrega › «Deshacer el registro».') for a in actas]
    return out
