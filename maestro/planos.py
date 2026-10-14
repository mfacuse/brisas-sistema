"""Planos de las propiedades: lee los .dxf de la carpeta de planos de cada propiedad y guarda, por piso, el contorno de cada local.

Cómo reconoce los locales: busca los rótulos «LOCAL 06», «LOCAL 23», «LOCAL A»… y toma la figura cerrada más chica que contiene el
rótulo (de preferencia en la capa de superficies auxiliares, que en los planos de Boulevard calza con los m² escritos). Si un local no
tiene contorno dibujado, se usa la forma de un vecino con los mismos m² o un cuadro del tamaño de sus m² (marcado «aproximado»).
Los planos sin rótulos de locales (elevaciones, cortes) se omiten. Si el plano no trae contornos cerrados (p. ej. Plaza Motor, dibujado con
líneas sueltas), se usan los contornos trazados una vez en «locales_plano.json» de la misma carpeta (coordenadas del dibujo). Ese archivo
también puede traer «divisiones»: locales que en el plano son uno solo pero se arriendan en partes (Boulevard 1A/1B y 11A/11B). Unidades del dibujo: centímetros ($INSUNITS = 5) o metros (6).
"""
import os
import re
from datetime import datetime, timedelta, timezone as tz
from decimal import Decimal
from math import sqrt
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from . import almacen
from .models import Local, LocalPlano, PlanoPiso

CAPAS_FONDO = {'muros', 'tabiques', 'pilares hormigon', 'limite terreno', 'escalera', 'e-escalera y barandas', 'n_hormigon'}
CAPA_LOCALES = 'a-auxiliar'
RE_LOCAL = re.compile(r'(?i)^\s*local\s*(\d{1,3}|[A-Z])\s*$')
RE_M2 = re.compile(r'^\s*(\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)\s*m²')
MESES_ALERTA = 4


def _area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def _dentro(p, pts):
    c, n = False, len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def _centro(pts):
    return sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)


def _m2_texto(t):
    m = RE_M2.match(t)
    if not m:
        return None
    v = m.group(1)
    return float(v.replace('.', '')) if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', v) else float(v.replace(',', '.'))


def leer_dxf(ruta: str):
    """Devuelve (rótulos, m², polígonos cerradas, fondo, textos de calles) en unidades del dibujo."""
    from ezdxf.addons import iterdxf
    doc = iterdxf.opendxf(ruta)   # lectura por partes: el plano del segundo piso pesa 250 MB
    rotulos, m2s, polis, fondo, textos = [], [], [], [], []
    for e in doc.modelspace():
        t, capa = e.dxftype(), e.dxf.layer.lower()
        if t in ('TEXT', 'MTEXT'):
            txt = (e.dxf.text if t == 'TEXT' else e.text).replace('\\P', ' ').replace('\n', ' ').strip()
            p = (e.dxf.insert[0], e.dxf.insert[1])
            if t == 'TEXT' and e.dxf.get('halign', 0) and e.dxf.hasattr('align_point'):
                p = (e.dxf.align_point[0], e.dxf.align_point[1])
            m = RE_LOCAL.match(txt)
            if m:
                rotulos.append((m.group(1).upper().lstrip('0') or '0', p))
            elif _m2_texto(txt) is not None:
                m2s.append((_m2_texto(txt), p))
            elif re.match(r'(?i)(calle|estacionamientos?$|\d+ oriente$)', txt):
                textos.append((p, txt.upper()))
        elif t == 'LWPOLYLINE':
            pts = [(x, y) for x, y, *_ in e.get_points()]
            if len(pts) >= 2:
                cerrada = e.closed or (len(pts) > 2 and pts[0] == pts[-1])
                if cerrada and len(pts) >= 3:
                    polis.append((capa, pts))
                if capa in CAPAS_FONDO:
                    fondo.append(pts + ([pts[0]] if e.closed else []))
        elif t == 'LINE' and capa in CAPAS_FONDO:
            fondo.append([(e.dxf.start[0], e.dxf.start[1]), (e.dxf.end[0], e.dxf.end[1])])
    doc.close()
    return rotulos, m2s, polis, fondo, textos


def _unidades(ruta: str) -> float:
    """Metros por unidad de dibujo según $INSUNITS (lee solo la cabecera)."""
    with open(ruta, 'r', encoding='latin-1', errors='ignore') as f:
        ant = ''
        for i, linea in enumerate(f):
            if ant.strip() == '$INSUNITS':
                next(f)
                u = int(next(f).strip())
                return {4: 0.001, 5: 0.01, 6: 1.0}.get(u, 0.01)
            if linea.strip() == 'ENTITIES' or i > 20000:
                break
            ant = linea
    return 0.01


def locales_para(propiedad, etiqueta: str):
    qs = Local.objects.filter(propiedad=propiedad)
    num = re.match(r'(\d+)-?([A-Z]?)$', etiqueta)
    if num:
        n, letra = int(num.group(1)), num.group(2)
        if letra:   # local dividido: «1A» → L01-A / L1A
            return [l for l in qs if re.match(rf'^L0*{n}-?{letra}(?![0-9A-Za-z])', l.codigo_plano)]
        return [l for l in qs if re.match(rf'^L0*{n}(?![0-9])', l.codigo_plano)]
    return [l for l in qs if re.match(rf'^M[óo]dulo {etiqueta}\b', l.codigo_plano)]


def _nombre_piso(propiedad, locales, archivo):
    pisos = [l.piso for l in locales if l.piso]
    if pisos:
        return max(set(pisos), key=pisos.count).replace(' (plano)', '')
    return 'Planta'   # propiedad de un solo piso o sin el piso registrado en el maestro de locales


def importar_archivo(propiedad, ruta: str, nombre: str = '', modificado=None, trazados=None):
    """Lee un plano (del Mac o de Google Drive). `trazados`: contenido de locales_plano.json de la carpeta (o None)."""
    local, temporal = almacen.archivo_local(ruta)
    try:
        entrada = (trazados or {}).get(nombre or Path(local).name) or {}
        return _importar(propiedad, ruta, local, nombre or Path(local).name, modificado,
                         entrada if entrada.get('locales') else None, entrada.get('divisiones'))
    finally:
        if temporal:
            os.unlink(local)


@transaction.atomic
def _importar(propiedad, ruta: str, local: str, nombre: str, modificado, trazado, divisiones=None):
    k = _unidades(local)
    rotulos, m2s, polis, fondo, textos = leer_dxf(local)
    if trazado:
        k = trazado.get('unidad_m', k)
        rotulos, m2s = [], []
        for et, pts in trazado['locales'].items():
            cx, cy = _centro(pts)
            rotulos.append((et, (cx, cy)))
            m2s.append((_area(pts) * k * k, (cx, cy)))
            polis.append((CAPA_LOCALES, [tuple(p) for p in pts]))
    if not rotulos:
        return None
    m = lambda pts: [(x * k, y * k) for x, y in pts]
    polis = [(c, m(pts)) for c, pts in polis]
    rotulos = [(e, (p[0] * k, p[1] * k)) for e, p in rotulos]
    m2s = [(v, (p[0] * k, p[1] * k)) for v, p in m2s]
    hallados = {}
    for et, p in rotulos:
        cand = [(c, pts, _area(pts)) for c, pts in polis if _dentro(p, pts) and 2 < _area(pts) < 3000]
        cand.sort(key=lambda x: (x[0] != CAPA_LOCALES, x[2]))
        m2 = min(m2s, key=lambda v: (v[1][0] - p[0]) ** 2 + (v[1][1] - p[1]) ** 2)[0] if m2s else None
        mejor = cand[0] if cand and cand[0][0] == CAPA_LOCALES else None
        hallados[et] = dict(p=p, pts=mejor[1] if mejor else None, m2=m2 if mejor is None else round(mejor[2], 1), aprox=mejor is None)
    for et, h in hallados.items():
        if h['pts']:
            continue
        locs = locales_para(propiedad, et)
        m2_maestro = float(sum((l.m2_oficial or 0) for l in locs)) or None
        vecino = None
        if et.isdigit() and h['m2']:
            vecinos = [(o, v) for o, v in hallados.items() if v['pts'] and not v['aprox'] and abs(v['m2'] - h['m2']) < 1]
            vecino = min(vecinos, key=lambda ov: (ov[1]['p'][0] - h['p'][0]) ** 2 + (ov[1]['p'][1] - h['p'][1]) ** 2)[1] if vecinos else None
        if vecino:
            dx, dy = h['p'][0] - vecino['p'][0], h['p'][1] - vecino['p'][1]
            h['pts'], h['m2'] = [(x + dx, y + dy) for x, y in vecino['pts']], vecino['m2']
        else:
            lado = sqrt(min(m2_maestro or (h['m2'] if h['m2'] and h['m2'] < 60 else 9), 120))
            x, y = h['p']
            h['pts'] = [(x - lado / 2, y - lado / 2), (x + lado / 2, y - lado / 2), (x + lado / 2, y + lado / 2), (x - lado / 2, y + lado / 2)]
            h['m2'] = m2_maestro or h['m2']
    # locales divididos (p. ej. 1 → 1A y 1B): contornos de cada parte en «divisiones» de locales_plano.json, en metros del dibujo
    for et, partes in (divisiones or {}).items():
        if et in hallados:
            del hallados[et]
            for sub, pts in partes.items():
                pts = [tuple(x) for x in pts]
                hallados[sub] = dict(p=_centro(pts), pts=pts, m2=round(_area(pts), 1), aprox=False)
    # límites: los locales más el deslinde del terreno
    todos = [pt for h in hallados.values() for pt in h['pts']]
    minx, maxx = min(x for x, _ in todos), max(x for x, _ in todos)
    miny, maxy = min(y for _, y in todos), max(y for _, y in todos)
    fondo = [m(pts) for pts in fondo]
    margen = 8
    def en_marco(pts):
        return all(minx - margen <= x <= maxx + margen and miny - margen <= y <= maxy + margen for x, y in pts)
    limite = [pts for c, pts in polis if c == 'limite terreno' and en_marco(pts)]
    for pts in limite:
        for x, y in pts:
            minx, maxx, miny, maxy = min(minx, x), max(maxx, x), min(miny, y), max(maxy, y)
    minx, miny, maxx, maxy = minx - 2, miny - 2, maxx + 2, maxy + 2
    tr = lambda pts: [[round(x - minx, 2), round(maxy - y, 2)] for x, y in pts]   # SVG: y hacia abajo
    piso, _ = PlanoPiso.objects.get_or_create(propiedad=propiedad, archivo=ruta, defaults={'nombre': Path(nombre).stem})
    piso.fondo = [tr(pts) for pts in fondo if en_marco(pts)]
    piso.textos = [[round(p[0] * k - minx, 1), round(maxy - p[1] * k, 1), t] for p, t in textos
                   if minx <= p[0] * k <= maxx and miny <= p[1] * k <= maxy]
    piso.ancho, piso.alto = round(maxx - minx, 2), round(maxy - miny, 2)
    piso.modificado = modificado
    piso.locales_plano.all().delete()
    todos_locales = []
    for et, h in sorted(hallados.items(), key=lambda kv: (not kv[0][:1].isdigit(), kv[0].zfill(6))):
        lp = LocalPlano.objects.create(piso=piso, etiqueta=et, poligono=tr(h['pts']), aproximado=h['aprox'],
                                       m2_plano=Decimal(str(h['m2'])) if h['m2'] else None)
        locs = locales_para(propiedad, et)
        lp.locales.set(locs)
        todos_locales += locs
    piso.nombre = _nombre_piso(propiedad, todos_locales, ruta)
    piso.orden = {'subterráneo': -1, 'primer piso': 1, 'segundo piso': 2}.get(piso.nombre.lower(), 9)
    piso.save()
    return piso


def importar_propiedad(propiedad, forzar=False) -> str:
    if not propiedad.carpeta_planos:
        return f'{propiedad.nombre}: sin carpeta de planos'
    import json
    if not almacen.existe_carpeta(propiedad.carpeta_planos):
        return f'{propiedad.nombre}: no se encuentra la carpeta de planos'
    try:
        entradas = almacen.listar(propiedad.carpeta_planos, {'.dxf', '.json'}, recursivo=False)
    except Exception as e:
        return f'{propiedad.nombre}: no se pudo leer la carpeta de planos ({e})'
    js = next((e for e in entradas if e.nombre == 'locales_plano.json'), None)
    trazados = json.loads(almacen.leer(js.ruta).decode('utf-8')) if js else None
    leidos, omitidos, iguales = [], [], 0
    for ent in sorted((e for e in entradas if e.nombre.lower().endswith('.dxf')), key=lambda e: e.nombre):
        # si cambian el plano o sus contornos trazados, se vuelve a leer
        mod = max(ent.modificado, js.modificado) if js and trazados and ent.nombre in trazados else ent.modificado
        previo = PlanoPiso.objects.filter(propiedad=propiedad, archivo=ent.ruta).first()
        if previo and previo.modificado == mod and not forzar:
            iguales += 1
            continue
        piso = importar_archivo(propiedad, ent.ruta, ent.nombre, mod, trazados)
        if piso:
            leidos.append(f'{ent.nombre} → {piso.nombre} ({piso.locales_plano.count()} locales)')
        else:
            omitidos.append(ent.nombre)
    partes = leidos + ([f'sin locales (omitidos): {", ".join(omitidos)}'] if omitidos else []) + ([f'{iguales} sin cambios'] if iguales else [])
    return f'{propiedad.nombre}: ' + ('; '.join(partes) or 'sin planos .dxf')


# ------------------------------------------------------------------ estado de cada local para el plano
def estado(lp: LocalPlano, hoy):
    """Color y datos del local: verde ocupado, amarillo si al contrato le quedan menos de 4 meses, rojo vacío."""
    from facturacion import motor, servicios
    contratos = []
    for l in lp.locales.all():
        for c in l.contratos.all():
            if c.activo and c.inicio_vigencia <= hoy and (not c.fecha_termino_real or c.fecha_termino_real >= hoy) and c not in contratos:
                contratos.append(c)
    if not contratos:
        return dict(color='rojo', contratos=[], termino=None, dias=None)
    filas, peor = [], None
    for c in contratos:
        if c.fecha_termino_real:
            termino = c.fecha_termino_real
        else:
            _, termino, _ = motor.vencimiento(servicios.a_contrato_d(c), c.plazo_meses, c.prorroga_meses, c.fin_pactado, hoy)
        dias = (termino - hoy).days if termino else None
        filas.append(dict(c=c, inicio=c.inicio_vigencia, termino=termino, dias=dias))
        if dias is not None and (peor is None or dias < peor):
            peor = dias
    limite = (hoy.replace(day=1) + timedelta(days=31 * MESES_ALERTA) - hoy.replace(day=1)).days
    color = 'amarillo' if peor is not None and peor < limite else 'verde'
    return dict(color=color, contratos=filas, termino=min((f['termino'] for f in filas if f['termino']), default=None), dias=peor)
