"""UF e IPC: lectura desde la base y carga desde fuentes oficiales.

Fuentes, en orden de preferencia:
  1. Banco Central de Chile (API de la Base de Datos Estadísticos), solo si hay un token en el archivo `.token_bcentral`
     de la carpeta del sistema (o en la variable de entorno BCCH_TOKEN). El token es gratis: cuenta en si3.bcentral.cl › Mi Cuenta.
  2. SII (sii.cl › Valores y fechas): publica la UF diaria y el IPC del INE. Es pública y no necesita registro.
Si la primera falla se usa la siguiente. Cada consulta espera como máximo TIMEOUT segundos.
(Antes se usaba mindicador.cl, que dejó de responder y hacía lento el encendido.)
"""
import html
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction

from facturacion.motor import UFNoDisponible
from .models import IPC, UF

TIMEOUT = 10
BCCH_API = 'https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx'
BCCH_SERIE_UF = 'F073.UFF.PRE.Z.D'          # UF diaria
BCCH_SERIE_IPC = 'F074.IPC.VAR.Z.Z.C.M'     # IPC general, variación mensual en %
SII_UF = 'https://www.sii.cl/valores_y_fechas/uf/uf{año}.htm'
SII_IPC = 'https://www.sii.cl/valores_y_fechas/utm/utm{año}.htm'
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
DOS_DEC = Decimal('0.01')


class AunNoPublicado(Exception):
    """La fuente todavía no tiene publicado ese año (p. ej. 2027 durante 2026)."""


@dataclass
class Carga:
    fuente: str
    total: int      # valores que entregó la fuente
    nuevos: int     # valores creados o corregidos en la base

    def __str__(self):
        return f'{self.total} valores desde {self.fuente} ({self.nuevos} nuevos o actualizados)'


def valor_uf(d: date) -> Decimal:
    """Valor de la UF para la fecha `d`. Lanza UFNoDisponible si no está cargada."""
    try:
        return UF.objects.get(fecha=d).valor
    except UF.DoesNotExist:
        raise UFNoDisponible(f'UF del {d:%d-%m-%Y} no está cargada')


def variacion_ipc(año: int, mes: int):
    """Variación mensual del IPC en % o None si aún no se publica/carga."""
    r = IPC.objects.filter(anio=año, mes=mes).first()
    return r.variacion_pct if r else None


# ------------------------------------------------------------------ descarga
def _contexto_ssl():
    """Certificados de `certifi` si está instalado (en macOS con Python de python.org el almacén del sistema suele venir vacío)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'brisas-del-centro/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_contexto_ssl()) as f:
            return f.read().decode('utf-8-sig')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AunNoPublicado(url) from e
        raise


def _numero_cl(txt: str):
    """'41.252,94' → Decimal('41252.94'); vacío → None."""
    txt = html.unescape(txt).replace('\xa0', ' ').strip()
    if not txt:
        return None
    return Decimal(txt.replace('.', '').replace(',', '.'))


# ------------------------------------------------------------------ Banco Central
def token_bcentral():
    tok = os.environ.get('BCCH_TOKEN', '').strip()
    if tok:
        return tok
    archivo = Path(getattr(settings, 'SECRETOS_DIR', settings.BASE_DIR)) / '.token_bcentral'
    if archivo.exists():
        return archivo.read_text(encoding='utf-8').strip() or None
    return None


def _serie_bcentral(serie: str, año: int):
    """[(fecha, valor)] de la serie para el año; omite los días sin dato."""
    q = urllib.parse.urlencode({'token': token_bcentral(), 'function': 'GetSeries', 'timeseries': serie,
                                'firstdate': f'{año}-01-01', 'lastdate': f'{año}-12-31'})
    data = json.loads(_get(f'{BCCH_API}?{q}'))
    if data.get('Codigo') != 0:
        raise RuntimeError(f"Banco Central: {data.get('Descripcion') or data.get('Codigo')}")
    out = []
    for o in (data.get('Series') or {}).get('Obs') or []:
        v = str(o.get('value', '')).strip()
        if o.get('statusCode', 'OK') != 'OK' or v in ('', 'NaN'):
            continue
        d, m, a = o['indexDateString'].split('-')
        out.append((date(int(a), int(m), int(d)), Decimal(v)))
    return out


def uf_bcentral(año: int) -> dict:
    return {f: v.quantize(DOS_DEC) for f, v in _serie_bcentral(BCCH_SERIE_UF, año)}


def ipc_bcentral(año: int) -> dict:
    return {(f.year, f.month): v.quantize(DOS_DEC) for f, v in _serie_bcentral(BCCH_SERIE_IPC, año)}


# ------------------------------------------------------------------ SII
def leer_uf_sii(pagina: str, año: int) -> dict:
    """Valores diarios de la página «UF {año}» del SII (una tabla por mes con pares día / valor)."""
    out = {}
    for mes, nombre in enumerate(MESES, 1):
        m = re.search(rf"id=['\"]mes_{nombre}['\"](.*?)</table>", pagina, re.S)
        if not m:
            continue
        for dia, valor in re.findall(r'<strong>\s*(\d{1,2})\s*</strong>\s*</th>\s*<td[^>]*>(.*?)</td>', m.group(1), re.S):
            v = _numero_cl(valor)
            if v is not None:
                out[date(año, mes, int(dia))] = v.quantize(DOS_DEC)
    return out


def leer_ipc_sii(pagina: str, año: int) -> dict:
    """Variación mensual del IPC (columna «Mensual») de la página «UTM - UTA - IPC {año}» del SII."""
    out = {}
    for nombre, celdas in re.findall(r'<tr>\s*<th[^>]*>\s*([A-Za-z]+)\s*</th>(.*?)</tr>', pagina, re.S):
        if nombre.lower() not in MESES:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', celdas, re.S)
        v = _numero_cl(tds[3]) if len(tds) >= 6 else None   # UTM, UTA, IPC en puntos, variación mensual, acumulada, 12 meses
        if v is not None:
            out[(año, MESES.index(nombre.lower()) + 1)] = v.quantize(DOS_DEC)
    return out


def uf_sii(año: int) -> dict:
    return leer_uf_sii(_get(SII_UF.format(año=año)), año)


def ipc_sii(año: int) -> dict:
    return leer_ipc_sii(_get(SII_IPC.format(año=año)), año)


# ------------------------------------------------------------------ carga a la base
def _fuentes(bcentral, sii):
    f = [('Banco Central', 'BCCH', bcentral)] if token_bcentral() else []
    return f + [('SII', 'SII', sii)]


def _descargar(año: int, fuentes):
    """Prueba las fuentes en orden; devuelve (nombre, origen, valores) de la primera que responde."""
    errores, no_publicado = [], 0
    for nombre, origen, fn in fuentes:
        try:
            return nombre, origen, fn(año)
        except AunNoPublicado:
            no_publicado += 1
            errores.append(f'{nombre}: {año} aún no publicado')
        except Exception as e:   # sin red, fuente caída, token inválido o página cambiada
            errores.append(f'{nombre}: {e}')
    if no_publicado == len(fuentes):
        raise AunNoPublicado(f'{año} aún no publicado')
    raise RuntimeError('; '.join(errores))


@transaction.atomic
def _guardar_uf(valores: dict, origen: str) -> int:
    """Crea o corrige solo lo que cambió, en una sola transacción (rápido aunque la base esté en Google Drive)."""
    actuales = {u.fecha: u for u in UF.objects.filter(fecha__in=list(valores))}
    nuevos, cambiados = [], []
    for f, v in valores.items():
        u = actuales.get(f)
        if u is None:
            nuevos.append(UF(fecha=f, valor=v, origen=origen))
        elif u.valor != v or u.origen == 'PRUEBA':
            u.valor, u.origen = v, origen
            cambiados.append(u)
    UF.objects.bulk_create(nuevos)
    UF.objects.bulk_update(cambiados, ['valor', 'origen'])
    return len(nuevos) + len(cambiados)


@transaction.atomic
def _guardar_ipc(valores: dict, origen: str) -> int:
    años = {a for a, _ in valores}
    actuales = {(r.anio, r.mes): r for r in IPC.objects.filter(anio__in=años)}
    nuevos, cambiados = [], []
    for (a, m), v in valores.items():
        r = actuales.get((a, m))
        if r is None:
            nuevos.append(IPC(anio=a, mes=m, variacion_pct=v, origen=origen))
        elif r.variacion_pct != v or r.origen == 'PRUEBA':
            r.variacion_pct, r.origen = v, origen
            cambiados.append(r)
    IPC.objects.bulk_create(nuevos)
    IPC.objects.bulk_update(cambiados, ['variacion_pct', 'origen'])
    return len(nuevos) + len(cambiados)


def cargar_uf_anio(año: int) -> Carga:
    """Descarga la UF diaria del año y la guarda. Reemplaza los valores de prueba de esas fechas."""
    nombre, origen, valores = _descargar(año, _fuentes(uf_bcentral, uf_sii))
    return Carga(nombre, len(valores), _guardar_uf(valores, origen))


def cargar_ipc_anio(año: int) -> Carga:
    """Descarga la variación mensual del IPC del año y la guarda. Reemplaza los valores de prueba de esos meses."""
    nombre, origen, valores = _descargar(año, _fuentes(ipc_bcentral, ipc_sii))
    return Carga(nombre, len(valores), _guardar_ipc(valores, origen))


def años_por_defecto(hoy: date):
    """El año actual; en enero también el anterior (el IPC de diciembre se publica el 8 de enero)
    y en diciembre también el siguiente (la UF de los primeros días de enero se publica en diciembre)."""
    años = [hoy.year]
    if hoy.month == 1:
        años.insert(0, hoy.year - 1)
    if hoy.month == 12:
        años.append(hoy.year + 1)
    return años
