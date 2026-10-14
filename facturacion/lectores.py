"""Lectores de las planillas mensuales de electricidad y gas (y de cargos «otros»).

Devuelven filas sencillas; no tocan la base de datos (eso lo hace `cargas.py`). Las planillas de origen son las que
arma el propietario cada mes (Facturacion_electrica_Brisas_<Mes>_<Año>.xlsx y Facturación Gas ….xls)."""
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal as D
from pathlib import Path

import openpyxl

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


class PlanillaInvalida(Exception):
    pass


def norm(t) -> str:
    """minúsculas, sin tildes ni signos, espacios simples."""
    t = unicodedata.normalize('NFKD', str(t or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', t)).strip()


def _num(v):
    if v is None or v == '' or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return D(str(v))
    try:
        return D(str(v).replace('.', '').replace(',', '.'))
    except Exception:
        return None


def hojas(ruta):
    """{nombre_hoja: [[valores de la fila 1], …]} con los valores calculados (no las fórmulas)."""
    ruta = Path(ruta)
    try:
        if ruta.suffix.lower() == '.xls':
            try:
                import xlrd
            except ImportError as e:  # pragma: no cover
                raise PlanillaInvalida('Para leer archivos .xls instale xlrd (pip install xlrd) o guarde la planilla como .xlsx.') from e
            wb = xlrd.open_workbook(str(ruta))
            return {s.name: [s.row_values(i) for i in range(s.nrows)] for s in wb.sheets()}
        wb = openpyxl.load_workbook(ruta, data_only=True)
        return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb}
    except PlanillaInvalida:
        raise
    except Exception as e:
        raise PlanillaInvalida(f'El archivo no es una planilla de Excel válida ({type(e).__name__}).') from e


def _cel(fila, i):
    return fila[i] if i is not None and i < len(fila) else None


@dataclass
class FilaCargo:
    servicio: str  # ELEC | GAS
    etiqueta_local: str
    nombre: str
    tarifa: str
    lectura_anterior: object
    lectura_actual: object
    factor: object
    cantidad: object
    unidad: str
    neto: D
    fila: int  # número de fila en la hoja (1 = primera), para citar el origen


# ------------------------------------------------------------------ electricidad
def leer_electricidad(ruta, hoja=None):
    """Lee las tres tablas (trifásicos BT-2, BT 4.3 y monofásicos BT 1). Devuelve (mes_texto, [FilaCargo])."""
    todas = hojas(ruta)
    nombre = hoja or next((n for n in todas if 'electric' in norm(n)), None)
    if nombre is None:
        raise PlanillaInvalida(f'No encontré la hoja de consumo eléctrico (hojas: {list(todas)})')
    filas = todas[nombre]
    mes = next((str(r[2]).strip() for r in filas[:8] if len(r) > 2 and norm(r[2]) in MESES), '')
    out = []
    i = 0
    while i < len(filas):
        enc = filas[i]
        if len(enc) > 3 and norm(enc[2]) in ('n local', 'no local', 'nº local', 'n lOCAL'.lower()) and norm(enc[3]) == 'nombre':
            cols = {norm(v): j for j, v in enumerate(enc) if v not in (None, '')}
            def col(*pref):
                for k, j in cols.items():
                    if any(k.startswith(p) for p in pref):
                        return j
                return None
            c_fijo = col('cargo fijo')
            c_const = col('constante', 'cte')
            c_kwh = col('consumos kw')
            c_fact = col('a facturar')
            c_tar = col('tarifa', 'tarfia')
            if None in (c_fijo, c_kwh, c_fact):
                raise PlanillaInvalida(f'Faltan columnas en la tabla de la fila {i + 1}')
            c_ant, c_act = c_fijo + 1, c_fijo + 2
            j = i + 1
            while j < len(filas) and str(_cel(filas[j], 3) or '').strip():
                f = filas[j]
                neto = _num(_cel(f, c_fact))
                if neto is not None:
                    out.append(FilaCargo('ELEC', str(_cel(f, 2) or '').strip(), str(_cel(f, 3)).strip(), str(_cel(f, c_tar) or '').strip(),
                                         _num(_cel(f, c_ant)), _num(_cel(f, c_act)), _num(_cel(f, c_const)), _num(_cel(f, c_kwh)), 'kWh', neto, j + 1))
                j += 1
            i = j
        else:
            i += 1
    if not out:
        raise PlanillaInvalida('No encontré filas de consumo eléctrico (¿cambió el formato de la planilla?).')
    return mes, out


# ------------------------------------------------------------------ gas
def leer_gas(ruta, año: int, mes: int):
    """Lee la hoja del mes de gas (el nombre incluye el mes y los dos últimos dígitos del año, p. ej. « SEPTIEMBRE 26»)."""
    todas = hojas(ruta)
    pat_mes, pat_año = MESES[mes - 1], str(año)[2:]
    cand = [n for n in todas if pat_mes in norm(n) and re.search(rf'\b{pat_año}\b', norm(n))]
    if not cand:
        raise PlanillaInvalida(f'No hay una hoja «{pat_mes.upper()} {pat_año}» en la planilla de gas (hojas: {list(todas)[-4:]}…).')
    nombre = cand[0]
    filas = todas[nombre]
    i = next((k for k, f in enumerate(filas) if norm(_cel(f, 1)) == 'consumo gas talca'), None)
    if i is None:
        raise PlanillaInvalida(f'La hoja {nombre!r} no tiene la tabla «Consumo Gas Talca».')
    out = []
    for j in range(i + 1, len(filas)):
        f = filas[j]
        n = str(_cel(f, 1) or '').strip()
        if not n or norm(n) == 'total':
            break
        neto = _num(_cel(f, 5))
        if neto is not None:
            out.append(FilaCargo('GAS', '', n, '', _num(_cel(f, 2)), _num(_cel(f, 3)), D('3.65'), _num(_cel(f, 4)), 'L', neto, j + 1))
    if not out:
        raise PlanillaInvalida(f'La hoja {nombre!r} no tiene filas de consumo.')
    return nombre, out


# ------------------------------------------------------------------ otros cargos (plantilla genérica)
ENCABEZADOS_OTROS = ['Contrato', 'Concepto en la factura', 'Detalle', 'Neto $', 'Mes de cobro (AAAA-MM)']


def leer_otros(ruta):
    """Plantilla simple: Contrato | Concepto | Detalle | Neto $ | Mes de cobro. Devuelve [(fila, codigo, concepto, detalle, neto, 'AAAA-MM')]."""
    filas = next(iter(hojas(ruta).values()))
    ini = next((k for k, f in enumerate(filas) if norm(_cel(f, 0)) == 'contrato'), None)
    if ini is None:
        raise PlanillaInvalida('No encontré el encabezado «Contrato» en la planilla de otros cargos.')
    out = []
    for k in range(ini + 1, len(filas)):
        f = filas[k]
        cod = str(_cel(f, 0) or '').strip().upper()
        if not cod:
            continue
        neto = _num(_cel(f, 3))
        if neto is None:
            raise PlanillaInvalida(f'Fila {k + 1}: el monto neto no es un número.')
        mes = _cel(f, 4)
        mes = mes.strftime('%Y-%m') if hasattr(mes, 'strftime') else str(mes or '').strip()[:7]
        out.append((k + 1, cod, str(_cel(f, 1) or '').strip(), str(_cel(f, 2) or '').strip(), neto, mes))
    return out


# ------------------------------------------------------------------ planillas de formato simple (agua, gastos comunes y luz/gas de Plaza Motor)
COLS_MONTO = ['a facturar neto', 'a facturar', 'monto neto', 'neto', 'gasto comun', 'gastos comunes', 'ggcc', 'monto', 'valor', 'total']
COLS_LOCAL = ['n local', 'no local', 'nro local', 'local', 'contrato', 'modulo', 'unidad']
COLS_NOMBRE = ['arrendatario', 'razon social', 'nombre', 'cliente', 'fantasia', 'locatario']
COLS_CONSUMO = {'AGUA': (['consumo m3', 'consumo', 'm3'], 'm³'), 'ELEC': (['consumo kwh', 'kwh', 'consumo'], 'kWh'),
                'GAS': (['consumo m3', 'consumo', 'litros', 'm3'], 'm³')}
MES_ABREV = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'ago': 8, 'sep': 9, 'set': 9, 'oct': 10, 'nov': 11, 'dic': 12}


def _buscar(enc, opciones, usadas=()):
    for o in opciones:
        for i, e in enumerate(enc):
            if i not in usadas and e and (e == o or e.startswith(o + ' ') or e.endswith(' ' + o)):
                return i
    for o in opciones:
        for i, e in enumerate(enc):
            if i not in usadas and e and o in e and not e.startswith('nro cliente'):
                return i
    return None


def _es_texto(v):
    return isinstance(v, str) and v.strip() and _num(v) is None


def _es_entero(v):
    n = _num(v) if v not in (None, '') else None
    return n is not None and n == n.to_integral_value() and 0 <= n < 10000


def _es_total(t: str) -> bool:
    """«Total», «TOTAL GENERAL», «Sub total»… (pero no «Totaland», que es un arrendatario)."""
    palabras = norm(t).split()
    return 'total' in palabras or 'subtotal' in palabras


def mes_de_hoja(nombre: str):
    """«AGO26» o «Agosto 2026» → (2026, 8); None si el nombre de la hoja no indica un mes."""
    t = norm(nombre).replace(' ', '')
    for abrev, m in MES_ABREV.items():
        if t.startswith(abrev):
            dig = ''.join(ch for ch in t if ch.isdigit())
            if len(dig) in (2, 4):
                return (2000 + int(dig) if len(dig) == 2 else int(dig)), m
    return None


def leer_generica(ruta, servicio: str):
    """Planilla simple con una fila por local y su monto: agua (AGUA), gastos comunes (GGCC) y luz/gas en formato
    simple (Plaza Motor). Detecta solas las columnas: monto («Neto», «Monto», «$»…), nombre («Arrendatario», «Nombre»…;
    si no tiene título, la columna de texto) y local («Local», o la columna de números junto al nombre); opcionales
    consumo y lecturas. Devuelve (hoja, [FilaCargo])."""
    claves_consumo, unidad = COLS_CONSUMO.get(servicio, ([], ''))
    for nombre_hoja, filas in hojas(ruta).items():
        for k, f in enumerate(filas[:25]):
            crudo = [str(c).strip() if c is not None else '' for c in f]
            enc = [norm(c) for c in f]
            i_monto = _buscar(enc, COLS_MONTO)
            if i_monto is None:
                i_monto = next((i for i, c in enumerate(crudo) if c in ('$', '$ neto', 'neto $', '$ a facturar')), None)
            if i_monto is None:
                continue
            datos = [r for r in filas[k + 1:k + 40] if any(c not in (None, '') for c in r)]
            usadas = {i_monto}
            i_cliente = _buscar(enc, ['nro cliente', 'n cliente', 'numero cliente', 'n de cliente'], usadas)
            usadas.add(i_cliente)
            i_nombre = _buscar(enc, COLS_NOMBRE, usadas)
            if i_nombre is not None and sum(_es_texto(_cel(r, i_nombre)) for r in datos) < 2:
                i_nombre = None   # el título calzó, pero la columna no trae nombres
            if i_nombre is None:   # columna de nombres sin título: la que tiene más textos
                cand = [(sum(_es_texto(_cel(r, i)) for r in datos), i) for i in range(len(f)) if i not in usadas]
                mejor = max(cand, default=(0, None))
                i_nombre = mejor[1] if mejor[0] >= 2 else None
            usadas.add(i_nombre)
            i_local = _buscar(enc, COLS_LOCAL, usadas)
            if i_local is None and i_nombre is not None:   # números de local sin título reconocible: la columna de enteros junto al nombre
                for i in (i_nombre - 1, i_nombre + 1):
                    if 0 <= i < len(f) and i not in usadas and sum(_es_entero(_cel(r, i)) for r in datos) >= 2:
                        i_local = i
                        break
            if i_nombre is None and i_local is None:
                continue
            usadas.add(i_local)
            i_cons = _buscar(enc, claves_consumo, usadas) if claves_consumo else None
            usadas.add(i_cons)
            i_ant = _buscar(enc, ['lectura anterior', 'l anterior', 'anterior'], usadas)
            usadas.add(i_ant)
            i_act = _buscar(enc, ['lectura actual', 'l actual', 'actual'], usadas)
            out = []
            for j in range(k + 1, len(filas)):
                fila = filas[j]
                nombre = str(_cel(fila, i_nombre) or '').strip() if i_nombre is not None else ''
                local = _cel(fila, i_local) if i_local is not None else None
                local = (str(int(local)) if isinstance(local, float) and local.is_integer() else str(local or '')).strip()
                if not (nombre or local) or _es_total(nombre) or _es_total(local):
                    continue
                neto = _num(_cel(fila, i_monto))
                if neto is None:
                    continue   # sin monto (p. ej. local sin consumo informado)
                cons = _num(_cel(fila, i_cons)) if i_cons is not None else None
                cliente = _cel(fila, i_cliente) if i_cliente is not None else None
                cliente = f'cliente {int(cliente) if isinstance(cliente, float) and cliente.is_integer() else cliente}' if cliente not in (None, '') else ''
                out.append(FilaCargo(servicio, local, nombre or local, cliente, _num(_cel(fila, i_ant)) if i_ant is not None else None,
                                     _num(_cel(fila, i_act)) if i_act is not None else None, None, cons, unidad if cons is not None else '',
                                     neto, j + 1))
            if out:
                return nombre_hoja, out
    raise PlanillaInvalida('No encontré una tabla con columnas de local o nombre y de monto ($, neto) en la planilla.')
