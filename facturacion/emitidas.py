"""Facturas emitidas por BSOFT en el SII: se leen los PDF de la carpeta de facturas de cada sociedad y se vinculan con los
documentos del sistema (número interno ↔ folio SII).

Cómo se vincula: mismo RUT del cliente y mismo total → vinculada (si hay varias, la del mes de emisión). Si el RUT calza pero el
monto no, queda «para revisar» y se vincula a mano en el panel. Un PDF puede traer una factura o varias (una por página o más).
El formato exacto del PDF de BSOFT se ajusta con el primer mes real; las reglas de lectura están en `leer_texto`.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from .models import Documento, FacturaEmitida

MESES = {m: i for i, m in enumerate(['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO', 'SEPTIEMBRE',
                                     'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'], 1)}
MESES['SETIEMBRE'] = 9
RE_RUT = re.compile(r'\b(\d{1,2}\.?\d{3}\.?\d{3}\s?-\s?[\dkK])\b')
RE_TIPO = re.compile(r'(NOTA\s+DE\s+CR[EÉ]DITO|FACTURA\s+(?:NO\s+AFECTA\s+O\s+)?EXENTA|FACTURA)\s+ELECTR[OÓ]NICA')
RE_FOLIO = re.compile(r'(?:N\s*[°º]|NRO\.?|N\.)\s*:?\s*0*(\d{1,10})\b')
RE_FOLIO2 = re.compile(r'FOLIO\s*:?\s*(?:N\s*[°º]\s*)?0*(\d{1,10})\b')
RE_MONTO = r'\s*:?\s*\$?\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?'


def rut_normal(rut: str) -> str:
    """'76.388.311-6' → '76388311-6' (para comparar)."""
    return re.sub(r'[.\s]', '', rut or '').upper()


def _monto(txt):
    return Decimal(txt.replace('.', '')) if txt else None


def _ultimo(patron, texto):
    ms = [m for m in re.finditer(patron, texto)]
    return ms[-1].group(1) if ms else None


@dataclass
class DatosFactura:
    tipo_dte: str = ''
    folio: str = ''
    rut_receptor: str = ''
    fecha_emision: date = None
    neto: Decimal = None
    exento: Decimal = None
    iva: Decimal = None
    total: Decimal = None
    paginas: list = field(default_factory=list)


def tipo_y_folio(texto: str):
    t = texto.upper()
    m = RE_TIPO.search(t)
    if not m:
        f = RE_FOLIO2.search(t)
        return ('', f.group(1)) if f else ('', '')
    palabra = m.group(1)
    tipo = '61' if palabra.startswith('NOTA') else ('34' if 'EXENTA' in palabra else '33')
    f = RE_FOLIO.search(t[m.end():m.end() + 160]) or RE_FOLIO2.search(t)
    return tipo, (f.group(1) if f else '')


def _fecha(t: str):
    m = re.search(r'FECHA\s*(?:DE\s*)?EMISI[OÓ]N\s*:?\s*(\d{1,2})\s*(?:DE\s+)?([A-ZÁÉÍÓÚ]+|\d{1,2})\s*(?:DE\s+|DEL\s+|/|-)?\s*(\d{4})', t)
    if not m:
        m = (re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', t)
             or re.search(r'\b(\d{1,2})\s+DE\s+([A-Z]+)\s+(?:DE|DEL)\s+(\d{4})\b', t))
    if not m:
        return None
    d, mes, a = m.groups()
    mes = int(mes) if mes.isdigit() else MESES.get(mes.replace('Á', 'A').replace('É', 'E'), 0)
    try:
        return date(int(a), mes, int(d))
    except ValueError:
        return None


def leer_texto(texto: str, rut_emisor: str) -> DatosFactura:
    """Extrae los datos de una factura desde el texto de su PDF."""
    t = re.sub(r'[ \t]+', ' ', texto.upper())
    r = DatosFactura()
    r.tipo_dte, r.folio = tipo_y_folio(t)
    emisor = rut_normal(rut_emisor)
    otros = [x for x in (rut_normal(m) for m in RE_RUT.findall(t)) if x != emisor]
    r.rut_receptor = otros[0] if otros else ''
    r.fecha_emision = _fecha(t)
    r.neto = _monto(_ultimo(r'(?:MONTO\s+)?NETO' + RE_MONTO, t))
    r.exento = _monto(_ultimo(r'(?:MONTO\s+)?EXENTO' + RE_MONTO, t))
    r.iva = _monto(_ultimo(r'I\.?\s?V\.?\s?A\.?\s*(?:\(?\s*19\s*%\s*\)?)?' + RE_MONTO, t))
    r.total = _monto(_ultimo(r'(?<!SUB)(?<!SUB )\bTOTAL\b' + RE_MONTO, t))
    return r


def leer_pdf(ruta: str, rut_emisor: str):
    """[DatosFactura] de un PDF: agrupa las páginas por folio (una página sin folio sigue a la factura anterior)."""
    from pypdf import PdfReader
    import io
    from maestro import almacen
    paginas = [(i + 1, (p.extract_text() or '')) for i, p in enumerate(PdfReader(io.BytesIO(almacen.leer(ruta))).pages)]
    grupos = []
    for n, texto in paginas:
        _, folio = tipo_y_folio(texto)
        if not grupos or (folio and folio != grupos[-1]['folio']):
            grupos.append(dict(folio=folio, paginas=[n], texto=texto))
        else:
            grupos[-1]['paginas'].append(n)
            grupos[-1]['texto'] += '\n' + texto
    out = []
    for g in grupos:
        d = leer_texto(g['texto'], rut_emisor)
        d.paginas = g['paginas']
        out.append(d)
    return out


# ------------------------------------------------------------------ vincular
def candidatos(fe: FacturaEmitida):
    qs = (Documento.objects.filter(contrato__sociedad=fe.sociedad, estado__in=('A', 'X')).exclude(tipo_documento='NC')
          .filter(emitida__isnull=True).select_related('contrato__arrendatario').order_by('-periodo'))
    return [d for d in qs if rut_normal(d.contrato.arrendatario.rut) == fe.rut_receptor]


def _cercania(d: Documento, fecha):
    if not fecha:
        return 0
    return abs((d.periodo.year - fecha.year) * 12 + d.periodo.month - fecha.month)


@transaction.atomic
def vincular(fe: FacturaEmitida):
    if fe.estado == FacturaEmitida.Estado.MANUAL or fe.estado == FacturaEmitida.Estado.ILEGIBLE:
        return fe
    if fe.documento_id:
        return fe
    if fe.tipo_dte == '61':
        fe.estado, fe.nota = FacturaEmitida.Estado.SIN, 'Nota de crédito: se registra, pero no se vincula sola.'
        fe.save()
        return fe
    mismos = candidatos(fe)
    exactos = [d for d in mismos if fe.total is not None and int(d.total) == int(fe.total)]
    if exactos:
        doc = sorted(exactos, key=lambda d: _cercania(d, fe.fecha_emision))[0]
        _unir(fe, doc, FacturaEmitida.Estado.VINCULADA, '')
    elif mismos:
        fe.estado = FacturaEmitida.Estado.DUDOSA
        fe.nota = 'Mismo RUT, otro monto. Posibles: ' + ', '.join(f'{d.contrato.codigo} {d.periodo:%m/%Y} ${int(d.total):,}'.replace(',', '.') for d in mismos[:4])
        fe.save()
    else:
        fe.estado, fe.nota = FacturaEmitida.Estado.SIN, 'Ningún documento aprobado del sistema con ese RUT (o ya vinculados).'
        fe.save()
    return fe


def _unir(fe, doc, estado, usuario):
    fe.documento, fe.estado, fe.vinculada_por, fe.nota = doc, estado, usuario, ''
    fe.save()
    doc.folio = fe.folio
    doc.save(update_fields=['folio'])


@transaction.atomic
def vincular_manual(fe: FacturaEmitida, doc: Documento, usuario: str):
    if hasattr(doc, 'emitida') and doc.emitida and doc.emitida.pk != fe.pk:
        raise ValueError(f'El documento {doc.numero_interno or doc} ya está vinculado al folio {doc.emitida.folio}.')
    if fe.documento_id and fe.documento_id != doc.pk:
        desvincular(fe, usuario)
    _unir(fe, doc, FacturaEmitida.Estado.MANUAL, usuario)


@transaction.atomic
def desvincular(fe: FacturaEmitida, usuario: str):
    if fe.documento_id:
        d = fe.documento
        d.folio = ''
        d.save(update_fields=['folio'])
    fe.documento, fe.estado, fe.vinculada_por, fe.nota = None, FacturaEmitida.Estado.SIN, usuario, 'Desvinculada a mano.'
    fe.save()


# ------------------------------------------------------------------ revisar la carpeta
@dataclass
class ResumenEmitidas:
    sociedad: str
    carpeta: str = ''
    archivos_leidos: int = 0
    facturas: int = 0
    vinculadas: int = 0
    dudosas: int = 0
    sin_documento: int = 0
    ilegibles: int = 0
    ya_no_estan: int = 0
    error: str = ''

    def __str__(self):
        if self.error:
            return f'{self.sociedad}: {self.error}'
        if not self.carpeta:
            return f'{self.sociedad}: sin carpeta de facturas emitidas configurada'
        quitadas = f' · {self.ya_no_estan} facturas ya no están en la carpeta (se quitaron y su folio se desvinculó)' if self.ya_no_estan else ''
        if not self.archivos_leidos:
            return f'{self.sociedad}: sin facturas nuevas{quitadas}'
        return (f'{self.sociedad}: {self.archivos_leidos} PDF nuevos o cambiados, {self.facturas} facturas · {self.vinculadas} vinculadas, '
                f'{self.dudosas} para revisar, {self.sin_documento} sin documento, {self.ilegibles} ilegibles{quitadas}')


def revisar(sociedad) -> ResumenEmitidas:
    res = ResumenEmitidas(sociedad.nombre, sociedad.carpeta_facturas)
    if not sociedad.carpeta_facturas:
        return res
    from maestro import almacen
    if not almacen.existe_carpeta(sociedad.carpeta_facturas):
        res.error = f'no se encuentra la carpeta «{sociedad.carpeta_facturas}»'
        return res
    try:
        entradas = sorted(almacen.listar(sociedad.carpeta_facturas, {'.pdf'}), key=lambda e: e.nombre)
    except Exception as e:
        res.error = f'no se pudo leer la carpeta ({e})'
        return res
    res.ya_no_estan = quitar_desaparecidas(sociedad, {e.ruta for e in entradas})
    for ent in entradas:
        previas = FacturaEmitida.objects.filter(sociedad=sociedad, ruta=ent.ruta)
        if previas.exists() and all(p.tamano == ent.tamano and p.modificado == ent.modificado for p in previas):
            continue
        res.archivos_leidos += 1
        _leer_archivo(sociedad, ent.ruta, ent.nombre, ent.tamano, ent.modificado, res)
    return res


@transaction.atomic
def quitar_desaparecidas(sociedad, rutas) -> int:
    """Facturas cuyo PDF se borró o se sacó de la carpeta: se desvincula su folio del documento y se quitan (si el PDF vuelve, se lee de nuevo)."""
    n = 0
    for fe in FacturaEmitida.objects.filter(sociedad=sociedad).exclude(ruta__in=rutas).select_related('documento'):
        if fe.documento_id:
            desvincular(fe, '')
        fe.delete()
        n += 1
    return n


@transaction.atomic
def _leer_archivo(sociedad, ruta, nombre, tamano, mod, res):
    try:
        facturas = leer_pdf(ruta, sociedad.rut)
    except Exception as e:  # PDF dañado o protegido
        facturas = []
        error = str(e)
    else:
        error = ''
    vistas = set()
    if not facturas:
        facturas = [DatosFactura(paginas=[1])]
    for d in facturas:
        pagina = d.paginas[0] if d.paginas else 1
        vistas.add(pagina)
        fe, _ = FacturaEmitida.objects.get_or_create(sociedad=sociedad, ruta=ruta, pagina=pagina, defaults={'nombre': nombre})
        fe.nombre, fe.tamano, fe.modificado = nombre, tamano, mod
        fe.tipo_dte, fe.folio, fe.rut_receptor, fe.fecha_emision = d.tipo_dte, d.folio, d.rut_receptor, d.fecha_emision
        fe.neto, fe.exento, fe.iva, fe.total = d.neto, d.exento, d.iva, d.total
        res.facturas += 1
        if not d.folio or not d.rut_receptor or d.total is None:
            if fe.estado != FacturaEmitida.Estado.MANUAL:
                fe.estado = FacturaEmitida.Estado.ILEGIBLE
                fe.nota = (f'No se pudo leer: {error}' if error else 'No se encontró el folio, el RUT o el total en el PDF (¿es un escaneo?).')[:300]
            fe.save()
            res.ilegibles += fe.estado == FacturaEmitida.Estado.ILEGIBLE
            continue
        if fe.estado == FacturaEmitida.Estado.ILEGIBLE:
            fe.estado = FacturaEmitida.Estado.SIN
        fe.save()
        if fe.documento_id and fe.estado == FacturaEmitida.Estado.VINCULADA and fe.documento.folio != fe.folio:
            desvincular(fe, '')   # el PDF cambió: se vuelve a vincular
        vincular(fe)
        res.vinculadas += fe.estado in ('V', 'M')
        res.dudosas += fe.estado == 'D'
        res.sin_documento += fe.estado == 'S'
    # páginas que ya no corresponden a una factura (el PDF cambió) y que no estaban vinculadas
    FacturaEmitida.objects.filter(sociedad=sociedad, ruta=ruta, documento__isnull=True).exclude(pagina__in=vistas).delete()


def revisar_todas():
    from maestro.models import Sociedad
    return [revisar(s) for s in Sociedad.objects.order_by('id')]
