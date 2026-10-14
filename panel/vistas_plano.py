"""Plano gráfico de cada propiedad: locales ocupados (verde), por vencer en menos de 4 meses (amarillo) y vacíos (rojo)."""
from math import sqrt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from maestro import planos
from maestro.models import Contrato, Local, Propiedad

from .permisos import puede_forzar
from .views import ctx_base

COLORES = {'verde': '#2e9d5b', 'amarillo': '#e0b000', 'rojo': '#d64545'}


def _fmt(d):
    return d.strftime('%d-%m-%Y') if d else '—'


def _preparar(lp, hoy):
    e = planos.estado(lp, hoy)
    pts = lp.poligono
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ancho, alto = max(xs) - min(xs), max(ys) - min(ys)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2   # centro del rectángulo que lo contiene
    if not planos._dentro((cx, cy), pts):                       # forma en L: el centro cae afuera → promedio de vértices
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    girar = alto > ancho * 1.6                      # local alto y angosto: el texto va en vertical
    largo, grosor = (alto, ancho) if girar else (ancho, alto)
    fs = max(0.45, min(1.6, grosor / 3.2, largo / 4))
    fs2 = fs * 0.6
    cabe = lambda texto, tam: len(texto) * tam * 0.56 <= largo * 0.92
    nombre = ' / '.join(f['c'].nombre_fantasia for f in e['contratos']) or 'Disponible'
    n = max(3, int(largo * 0.92 / (fs2 * 0.56)))
    lineas = [nombre if len(nombre) <= n else nombre[:n - 1] + '…']
    if e['contratos']:
        f = min(e['contratos'], key=lambda f: f['dias'] if f['dias'] is not None else 10 ** 6)
        fechas = f"{_fmt(f['inicio'])} – {_fmt(f['termino'])}"
        if not cabe(fechas, fs2 * 0.85):
            fechas = f"hasta {_fmt(f['termino'])}"
        if cabe(fechas, fs2 * 0.85) and grosor > fs + fs2 * 2.2:
            lineas.append(fechas)
    titulo = [f'Local {lp.etiqueta} · {lp.m2_plano or "?"} m² en el plano' + (' (contorno aproximado)' if lp.aproximado else '')]
    for f in e['contratos']:
        c = f['c']
        titulo.append(f"{c.codigo} {c.nombre_fantasia} — {c.arrendatario.razon_social} · desde {_fmt(f['inicio'])} hasta {_fmt(f['termino'])}"
                      + (f" ({f['dias']} días)" if f['dias'] is not None else ''))
    if not e['contratos']:
        titulo.append('Disponible (sin contrato vigente)')
    # números con punto decimal (el idioma del sistema usa coma, y el dibujo SVG necesita punto)
    return dict(lp=lp, e=e, color=COLORES[e['color']], puntos=' '.join(f'{x:.2f},{y:.2f}' for x, y in pts), cx=f'{cx:.2f}', cy=f'{cy:.2f}',
                fs=f'{fs:.2f}', fs2=f'{fs2:.2f}', fs3=f'{fs2 * 0.85:.2f}', lineas=lineas, titulo='\n'.join(titulo),
                giro=f'rotate(-90 {cx:.2f} {cy:.2f})' if girar else '', y0=f'{cy - (fs2 * len(lineas)) / 2 + fs * 0.35:.2f}',
                url=f"/contratos/{e['contratos'][0]['c'].codigo}/" if e['contratos'] else '')


@login_required
def plano(request):
    c = ctx_base(request)
    props = list(Propiedad.objects.select_related('sociedad').order_by('id'))
    pid = request.GET.get('propiedad')
    prop = next((p for p in props if str(p.pk) == pid), None) or next((p for p in props if p.sociedad_id == c['sociedad'].id), props[0] if props else None)
    hoy = timezone.localdate()
    pisos, filas, conteo = [], [], {'verde': 0, 'amarillo': 0, 'rojo': 0}
    en_plano = set()
    if prop:
        for piso in prop.planos.prefetch_related('locales_plano__locales__contratos__arrendatario'):
            items = [_preparar(lp, hoy) for lp in piso.locales_plano.all()]
            for it in items:
                conteo[it['e']['color']] += 1
                en_plano |= {l.pk for l in it['lp'].locales.all()}
            pisos.append(dict(piso=piso, items=items, trazo=f'{max(piso.ancho, piso.alto) / 900:.3f}', caja=f'0 0 {piso.ancho:.2f} {piso.alto:.2f}',
                              fondo=[' '.join(f'{x:.2f},{y:.2f}' for x, y in pts) for pts in piso.fondo],
                              textos=[(f'{x:.1f}', f'{y:.1f}', t) for x, y, t in piso.textos]))
            filas += [dict(piso=piso.nombre, **it) for it in items]
    sin_plano = (Contrato.objects.filter(propiedad=prop, activo=True).exclude(locales__in=en_plano).select_related('arrendatario')
                 .prefetch_related('locales').distinct() if prop else [])
    c.update(propiedades=props, prop=prop, pisos=pisos, filas=filas, conteo=conteo, sin_plano=sin_plano, hoy=hoy,
             sin_vinculo=Contrato.objects.filter(propiedad=prop, activo=True, locales__isnull=True).count() if prop else 0)
    return render(request, 'panel/plano.html', c)


@login_required
@require_POST
def plano_importar(request):
    if not puede_forzar(request.user):
        raise PermissionDenied
    prop = Propiedad.objects.get(pk=request.POST.get('propiedad'))
    messages.info(request, planos.importar_propiedad(prop, forzar=True))
    return redirect(f'/plano/?propiedad={prop.pk}')
