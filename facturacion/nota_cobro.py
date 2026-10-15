"""Nota de cobro en PDF: para los contratos que se cobran sin factura (tipo de documento «NC», sin IVA, no es DTE).

El número de la nota (p. ej. BT-NC-0001) es el número interno correlativo que se asigna al aprobar; es su número oficial.
"""
import os
import re
import zipfile
from datetime import date

from django.conf import settings
from django.utils import timezone
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from . import motor
from .models import Documento

AZUL = (31, 58, 95)
GRIS = (110, 110, 110)
REEMPLAZOS = {'→': '->', '–': '-', '—': '-', '…': '...', '“': '"', '”': '"', '‘': "'", '’': "'", '•': '-', '≈': '~'}


def _t(texto) -> str:
    """Texto apto para las fuentes básicas del PDF (latin-1): tildes y ñ sí; flechas y símbolos raros se reemplazan."""
    s = str(texto or '')
    for a, b in REEMPLAZOS.items():
        s = s.replace(a, b)
    return s.encode('latin-1', 'replace').decode('latin-1')


SIG = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)   # después de la celda, pasar a la línea siguiente


def pdf_nota(doc: Documento) -> bytes:
    if doc.tipo_documento != 'NC':
        raise ValueError('Este documento es una factura: se emite en BSOFT, no como nota de cobro.')
    c, soc = doc.contrato, doc.contrato.sociedad
    borrador = doc.estado == 'B' or not doc.numero_interno
    emision = timezone.localtime(doc.aprobado_en).date() if doc.aprobado_en else timezone.localdate()

    pdf = FPDF(format='Letter')
    pdf.set_auto_page_break(True, margin=18)
    pdf.set_title(_t(f'Nota de cobro {doc.numero_interno or "borrador"}'))
    pdf.set_author(_t(soc.nombre))
    pdf.add_page()
    ancho = pdf.w - pdf.l_margin - pdf.r_margin

    # encabezado: emisor a la izquierda, recuadro con el número a la derecha
    y0 = pdf.get_y()
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*AZUL)
    pdf.multi_cell(ancho * 0.58, 6, _t(soc.nombre), **SIG)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(0, 0, 0)
    for linea in (f'RUT {soc.rut}', soc.giro, soc.direccion):
        if linea:
            pdf.multi_cell(ancho * 0.58, 4.5, _t(linea), **SIG)
    y1 = pdf.get_y()
    x = pdf.l_margin + ancho * 0.62
    pdf.set_draw_color(*AZUL)
    pdf.set_line_width(0.6)
    pdf.rect(x, y0, ancho * 0.38, 26)
    pdf.set_xy(x, y0 + 3)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(*AZUL)
    pdf.cell(ancho * 0.38, 7, 'NOTA DE COBRO', align='C', **SIG)
    pdf.set_x(x)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(ancho * 0.38, 7, _t(f'N.º {doc.numero_interno}' if not borrador else 'BORRADOR'), align='C', **SIG)
    pdf.set_x(x)
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*GRIS)
    pdf.cell(ancho * 0.38, 5, _t('Documento no tributario (sin IVA)'), align='C', **SIG)
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(max(y1, y0 + 26) + 6)

    # datos del cliente
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(235, 240, 247)
    pdf.cell(ancho, 7, _t('  Cliente'), fill=True, **SIG)
    pdf.set_font('Helvetica', '', 9.5)
    filas = [('Señor(es)', c.arrendatario.razon_social), ('RUT', c.arrendatario.rut), ('Dirección', c.direccion_contrato or ''),
             ('Contrato', f'{c.codigo} · {c.nombre_fantasia} · {c.propiedad.nombre}'),
             ('Período', f'{motor.MESES[doc.periodo.month]} {doc.periodo.year}'), ('Fecha de emisión', emision.strftime('%d-%m-%Y')),
             ('Condición de pago', doc.condicion_pago or str(c.condicion_pago or ''))]
    for k, v in filas:
        pdf.set_font('Helvetica', 'B', 9.5)
        pdf.cell(38, 6, _t(k))
        pdf.set_font('Helvetica', '', 9.5)
        pdf.multi_cell(ancho - 38, 6, _t(v), **SIG)
    if doc.glosa:
        pdf.ln(1)
        pdf.set_font('Helvetica', 'I', 9)
        pdf.multi_cell(ancho, 5, _t(doc.glosa), **SIG)
    pdf.ln(4)

    # detalle
    col_monto = 38
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(*AZUL)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(ancho - col_monto, 7, _t('  Detalle'), fill=True)
    pdf.cell(col_monto, 7, _t('Monto  '), fill=True, align='R', **SIG)
    pdf.set_text_color(0, 0, 0)
    for l in doc.lineas.all().order_by('orden'):
        y = pdf.get_y()
        pdf.set_font('Helvetica', 'B', 9.5)
        pdf.multi_cell(ancho - col_monto, 5.5, _t(l.concepto), **SIG)
        if l.detalle:
            pdf.set_font('Helvetica', '', 8)
            pdf.set_text_color(*GRIS)
            pdf.multi_cell(ancho - col_monto, 4.2, _t(l.detalle), **SIG)
            pdf.set_text_color(0, 0, 0)
        y_fin = pdf.get_y()
        pdf.set_xy(pdf.l_margin + ancho - col_monto, y)
        pdf.set_font('Helvetica', '', 9.5)
        pdf.cell(col_monto, 5.5, _t(f'{motor.fmt_clp(int(l.neto))}  '), align='R')
        pdf.set_xy(pdf.l_margin, y_fin + 1.5)
        pdf.set_draw_color(220, 220, 220)
        pdf.set_line_width(0.2)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + ancho, pdf.get_y())
        pdf.ln(1.5)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_fill_color(235, 240, 247)
    pdf.cell(ancho - col_monto, 8, _t('  TOTAL A PAGAR'), fill=True)
    pdf.cell(col_monto, 8, _t(f'{motor.fmt_clp(int(doc.total))}  '), fill=True, align='R', **SIG)

    # datos de pago y pie
    if soc.datos_pago:
        pdf.ln(6)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(ancho, 6, _t('Datos para el pago'), **SIG)
        pdf.set_font('Helvetica', '', 9)
        pdf.multi_cell(ancho, 5, _t(soc.datos_pago), **SIG)
    pdf.ln(8)
    pdf.set_font('Helvetica', '', 7.5)
    pdf.set_text_color(*GRIS)
    pdf.multi_cell(ancho, 4, _t('Este documento no es una factura ni un documento tributario electrónico: es una nota de cobro '
                                'por el arriendo indicado, sin IVA, según el contrato.'), **SIG)
    if borrador:
        pdf.set_font('Helvetica', 'B', 60)
        pdf.set_text_color(230, 230, 230)
        with pdf.rotation(30, pdf.w / 2, pdf.h / 2):
            pdf.text(pdf.w / 2 - 75, pdf.h / 2, 'BORRADOR')
    return bytes(pdf.output())


def nombre_archivo(doc: Documento) -> str:
    base = doc.numero_interno or f'BORRADOR_{doc.contrato.codigo}'
    return re.sub(r'[^\w.-]+', '_', f'Nota_de_cobro_{base}_{doc.contrato.codigo}_{doc.periodo:%Y-%m}') + '.pdf'


def exportar_mes(sociedad, año: int, mes: int):
    """PDF de todas las notas de cobro aprobadas o emitidas del mes, guardados en salidas/notas_cobro y en un .zip.
    Devuelve (zip, [documentos])."""
    docs = list(Documento.objects.filter(contrato__sociedad=sociedad, periodo=date(año, mes, 1), tipo_documento='NC', estado__in=('A', 'X'))
                .select_related('contrato__arrendatario', 'contrato__propiedad', 'contrato__sociedad').order_by('numero_interno'))
    if not docs:
        raise ValueError('No hay notas de cobro aprobadas para ese mes.')
    slug = re.sub(r'\W+', '_', sociedad.nombre).strip('_')
    carpeta = os.path.join(settings.MEDIA_ROOT, 'notas_cobro', f'{año}-{mes:02d}', slug)
    os.makedirs(carpeta, exist_ok=True)
    zpath = os.path.join(os.path.dirname(carpeta), f'Notas_de_cobro_{slug}_{año}-{mes:02d}.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            datos = pdf_nota(d)
            nombre = nombre_archivo(d)
            with open(os.path.join(carpeta, nombre), 'wb') as fh:
                fh.write(datos)
            z.writestr(nombre, datos)
    return zpath, docs
