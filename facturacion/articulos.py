"""Códigos de artículo de cada línea de la factura (los mismos en Boulevard Talca y 15 Oriente; Matías, 2026-10-15).

La tabla por sociedad está en «códigos de artículo» (modelo CodigoServicioBsoft, editable en Administración). Los «otros cargos»
se reconocen por su concepto: habilitación, gastos administrativos o equipamiento; el resto va a VARIOS."""
import re
import unicodedata

CATALOGO = {'111': 'ARRIENDO', '222': 'HABILITACION', '333': 'ARRIENDO VARIABLE', '444': 'CONSUMO AGUA', '555': 'ENERGIA ELECTRICA',
            '666': 'CONSUMO GAS', '777': 'GASTOS ADMINISTRATIVOS', '888': 'EQUIPAMIENTO', '999': 'VARIOS'}
# tipo de línea → código (descuento de renta con arriendo; gastos comunes con gastos administrativos: decisión de Matías)
POR_ORIGEN = {'RENTA': '111', 'DESC': '111', 'RDIF': '333', 'AGUA': '444', 'ELEC': '555', 'GAS': '666', 'GGCC': '777', 'OTRO': '999'}
OTROS_POR_CONCEPTO = [(r'habilit', '222'), (r'gasto.*administr|administraci', '777'), (r'equipa', '888')]
REEMPLAZOS = {'×': 'x', '→': '->', '–': '-', '—': '-', '·': '-', '…': '...', '²': '2', '³': '3', '°': ' ', 'º': ' ', '\n': ' '}


def sin_tildes(t: str) -> str:
    """Texto sin tildes, sin ñ y sin símbolos especiales (para BSOFT): «Diseño · año» → «Diseno - ano»."""
    for a, b in REEMPLAZOS.items():
        t = t.replace(a, b)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    return ' '.join(t.split())


def codigo(linea, codigos: dict) -> str:
    """Código de artículo de una línea (`codigos` = {origen: código} de la sociedad)."""
    if linea.origen == 'OTRO':
        txt = sin_tildes(f'{linea.concepto} {linea.detalle}').lower()
        for patron, cod in OTROS_POR_CONCEPTO:
            if re.search(patron, txt):
                return cod
    return codigos.get(linea.origen) or POR_ORIGEN.get(linea.origen, '999')
