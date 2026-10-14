"""XML de importación de BSOFT: un <Documento> por factura (formato «Arriendo_Automatico_V2»).

Estructura (según el ejemplo entregado por el propietario):
    <Documento>
      <Encabezado><RUTcliente>15556978-6</RUTcliente><glosaDocto>…</glosaDocto></Encabezado>
      <Detalle><NroLinDet>1</NroLinDet><CodServicio>1002</CodServicio><Cantidad>1</Cantidad><Valor>10430</Valor></Detalle> …
    </Documento>
No trae fecha, tipo de documento ni sociedad: BSOFT los define al importar (una sesión por sociedad).
"""
import os
import re
import unicodedata
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from django.conf import settings

from . import motor
from .models import CodigoServicioBsoft, Documento, LineaDocumento


class FaltanCodigos(Exception):
    pass


def _ascii(t: str) -> str:
    """Sin tildes ni ñ: el ejemplo de BSOFT es ASCII y no declara codificación."""
    return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()


def rut_bsoft(rut: str) -> str:
    """12.345.678-9 → 12345678-9. Rechaza lo que no sea un RUT chileno (p. ej. cédulas de extranjero con texto)."""
    mt = re.fullmatch(r'\s*([\d.]+)-([\dkK])\s*', rut)
    if not mt:
        raise ValueError(f'RUT no válido para BSOFT: «{rut}»')
    return f"{mt.group(1).replace('.', '')}-{mt.group(2).upper()}"


def glosa_bsoft(doc: Documento) -> str:
    c = doc.contrato
    nombre = c.propiedad.nombre_glosa or c.propiedad.nombre
    partes = [nombre]
    if doc.valor_uf and doc.fecha_uf:
        partes.append(f'Valor de la UF {motor.fmt_uf(doc.valor_uf)} del {doc.fecha_uf:%d/%m/%Y}')
    partes.append(f'{motor.MESES[doc.periodo.month]} {doc.periodo.year}')
    return _ascii(' '.join(partes))


def xml_documento(doc: Documento, codigos: dict) -> str:
    L = ['<Documento>', '\t<Encabezado>',
         f'\t\t\t<RUTcliente>{escape(rut_bsoft(doc.contrato.arrendatario.rut))}</RUTcliente>',
         f'\t\t\t<glosaDocto>{escape(glosa_bsoft(doc))}</glosaDocto>', '\t</Encabezado>']
    for i, l in enumerate(doc.lineas.all().order_by('orden'), start=1):
        L += ['\t<Detalle>', f'\t\t <NroLinDet>{i}</NroLinDet>', f'\t\t <CodServicio>{codigos[l.origen]}</CodServicio>',
              '\t\t <Cantidad>1</Cantidad>', f'\t\t <Valor>{int(l.neto)}</Valor>', '\t</Detalle>']
    L.append('</Documento>')
    return '\r\n'.join(L) + '\r\n'


def exportar_xml(sociedad, año: int, mes: int, estados=('A', 'X'), carpeta=None):
    """Escribe un .xml por documento y un .zip con todos. Devuelve (carpeta, zip, [archivos])."""
    docs = list(Documento.objects.filter(contrato__sociedad=sociedad, periodo=date(año, mes, 1), estado__in=estados)
                .exclude(tipo_documento='NC')  # las notas de cobro no son DTE: no van a BSOFT, se emiten en PDF
                .select_related('contrato__arrendatario', 'contrato__propiedad').prefetch_related('lineas').order_by('contrato__codigo'))
    if not docs:
        raise ValueError('No hay facturas aprobadas para ese mes (las notas de cobro no van a BSOFT: se emiten en PDF).')
    codigos = dict(CodigoServicioBsoft.objects.filter(sociedad=sociedad).values_list('origen', 'codigo'))
    usados = {l.origen for d in docs for l in d.lineas.all()}
    faltan = sorted(usados - set(codigos))
    if faltan:
        nombres = dict(LineaDocumento.Origen.choices)
        raise FaltanCodigos('Faltan los códigos de servicio BSOFT de: ' + ', '.join(nombres[o] for o in faltan)
                            + f' (sociedad {sociedad.nombre}). Cárguelos en Admin → Códigos de servicio BSOFT.')
    slug = re.sub(r'\W+', '_', _ascii(sociedad.nombre)).strip('_')
    carpeta = carpeta or os.path.join(settings.MEDIA_ROOT, 'bsoft', f'{año}-{mes:02d}', slug)
    os.makedirs(carpeta, exist_ok=True)
    archivos = []
    for d in docs:
        ruta = os.path.join(carpeta, f'{d.contrato.codigo}_{año}-{mes:02d}.xml')
        with open(ruta, 'w', encoding='ascii', newline='') as fh:
            fh.write(xml_documento(d, codigos))
        archivos.append(ruta)
    zpath = os.path.join(os.path.dirname(carpeta), f'{slug}_{año}-{mes:02d}.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for a in archivos:
            z.write(a, os.path.basename(a))
    return carpeta, zpath, archivos
