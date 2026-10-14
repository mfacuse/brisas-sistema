"""Pantallas del sistema: panel del mes, facturación, documentos, contratos, cargas, medidores, alertas e indicadores."""
import calendar
import os
import tempfile
from datetime import date
from decimal import Decimal as D, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from facturacion import asignacion, bsoft, cargas, comparacion, exportar, lectores, motor, servicios
from facturacion.models import CargaPlanilla, ConsumoServicio, Documento, FechaUFMes, FacturaEmitida, MedidorServicio, VentaMensual
from indicadores import servicio as ind
from indicadores.models import IPC, UF
from maestro.models import ArchivoContrato, Contrato, PropuestaIA, Sociedad

from .permisos import puede_forzar, puede_operar, requiere_operacion, rol


SERVICIO_DE_TIPO = {'electricidad': 'ELEC', 'gas': 'GAS', 'agua': 'AGUA', 'gastos_comunes': 'GGCC'}
NOMBRE_SERVICIO = {'ELEC': 'Electricidad', 'GAS': 'Gas', 'AGUA': 'Agua', 'GGCC': 'Gastos comunes'}


# ------------------------------------------------------------------ utilidades
def _periodo(request, clave='periodo'):
    txt = request.GET.get(clave) or request.POST.get(clave) or ''
    try:
        a, m = txt.split('-')
        return date(int(a), int(m), 1)
    except Exception:
        hoy = timezone.localdate()
        return date(hoy.year, hoy.month, 1)


def _sociedad(request):
    sid = request.GET.get('sociedad') or request.POST.get('sociedad') or ''
    socs = list(Sociedad.objects.order_by('id'))
    elegida = next((s for s in socs if str(s.id) == sid), socs[0] if socs else None)
    return elegida, socs


def _mes_vecino(p, d):
    m = p.month + d
    a = p.year + (m - 1) // 12
    return date(a, (m - 1) % 12 + 1, 1)


def ctx_base(request, **extra):
    p = extra.get('periodo') or _periodo(request)
    soc, socs = _sociedad(request)
    base = dict(periodo=p, sociedad=soc, sociedades=socs, rol=rol(request.user), puede_operar=puede_operar(request.user),
                puede_forzar=puede_forzar(request.user), mes_prev=_mes_vecino(p, -1), mes_sig=_mes_vecino(p, 1),
                qs=f'sociedad={soc.id}&periodo={p:%Y-%m}' if soc else '')
    base.update(extra)
    return base


def _fecha_uf_mes(p):
    return date(p.year, p.month, 1)


# ------------------------------------------------------------------ inicio
@login_required
def inicio(request):
    c = ctx_base(request)
    p, soc = c['periodo'], c['sociedad']
    docs = Documento.objects.filter(contrato__sociedad=soc, periodo=p).exclude(estado='N')
    por_estado = {k: 0 for k in 'BAXN'}
    for e, n in docs.values_list('estado').annotate(n=Count('id')):
        por_estado[e] = n
    tot = docs.aggregate(neto=Sum('neto'), iva=Sum('iva'), total=Sum('total'))
    uf_ok = UF.objects.filter(fecha=_fecha_uf_mes(p)).first()
    n_contratos = servicios.contratos_del_mes(soc, p.year, p.month).count()
    con_adv = sum(1 for d in docs.filter(estado='B') if motor_graves(d))
    cargos = ConsumoServicio.objects.filter(contrato__sociedad=soc, periodo_cobro=p)
    ventas_pend = _ventas_pendientes(soc, p)
    medidores_pend = MedidorServicio.objects.filter(contrato__sociedad=soc, confirmado=False).count()
    pasos = [
        dict(n=1, titulo='Indicadores', ok=bool(uf_ok), texto=(f'UF {motor.fmt_uf(uf_ok.valor)} del 01/{p:%m/%Y}' if uf_ok else f'Falta la UF del 01/{p:%m/%Y}'), url='indicadores'),
        dict(n=2, titulo='Cargas del mes', ok=cargos.exists() and not ventas_pend, texto=f'{cargos.count()} cargos de luz/gas/otros'
             + (f' · faltan ventas de {len(ventas_pend)} contrato(s)' if ventas_pend else ''), url='cargas'),
        dict(n=3, titulo='Generar borradores', ok=docs.exists(), texto=f'{docs.count()} de {n_contratos} contratos con documento', url='facturacion'),
        dict(n=4, titulo='Revisar y aprobar', ok=docs.exists() and por_estado['B'] == 0, texto=f'{por_estado["B"]} borradores · {con_adv} con advertencias · {por_estado["A"] + por_estado["X"]} aprobados', url='facturacion'),
        dict(n=5, titulo='Exportar', ok=por_estado['X'] > 0, texto='Excel de revisión y XML para BSOFT', url='facturacion'),
    ]
    c.update(docs_n=docs.count(), por_estado=por_estado, tot=tot, pasos=pasos, medidores_pend=medidores_pend,
             alertas=[a for a in servicios.alertas_vigentes(timezone.localdate(), 90, soc) if a[2] in ('ALTA', 'MEDIA')][:8])
    return render(request, 'panel/inicio.html', c)


def motor_graves(doc):
    return [a for a in doc.advertencias if not str(a).startswith('Nota:')]


def _ventas_pendientes(soc, p):
    """Contratos con renta variable a los que les faltan las ventas del mes anterior."""
    a, m = motor.mes_anterior(p.year, p.month)
    faltan = []
    for c in servicios.contratos_del_mes(soc, p.year, p.month).exclude(base_variable=''):
        if c.variable_desde and date(a, m, 1) < date(c.variable_desde.year, c.variable_desde.month, 1):
            continue
        if not VentaMensual.objects.filter(contrato=c, periodo=date(a, m, 1)).exists():
            faltan.append(c)
    return faltan


# ------------------------------------------------------------------ facturación del mes
@login_required
def facturacion(request):
    c = ctx_base(request)
    p, soc = c['periodo'], c['sociedad']
    docs = list(Documento.objects.filter(contrato__sociedad=soc, periodo=p).exclude(estado='N')
                .select_related('contrato__arrendatario').prefetch_related('lineas').order_by('contrato__codigo'))
    filas = []
    lineas_cargo = 0
    for d in docs:
        por = {}
        for l in d.lineas.all():
            por[l.origen] = por.get(l.origen, 0) + int(l.neto)
            if l.origen in ('ELEC', 'GAS', 'AGUA', 'GGCC', 'OTRO'):
                lineas_cargo += 1
        filas.append(dict(d=d, renta=por.get('RENTA', 0) + por.get('RDIF', 0) + por.get('DESC', 0), luz=por.get('ELEC', 0),
                          gas=por.get('GAS', 0), agua=por.get('AGUA', 0), ggcc=por.get('GGCC', 0), otro=por.get('OTRO', 0), graves=motor_graves(d)))
    con_doc = {d.contrato_id for d in docs}
    sin_doc = [x for x in servicios.contratos_del_mes(soc, p.year, p.month) if x.id not in con_doc]
    tot = {k: sum(int(getattr(f['d'], k)) for f in filas) for k in ('neto', 'iva', 'total')}
    cargos = ConsumoServicio.objects.filter(contrato__sociedad=soc, periodo_cobro=p)
    n_luz, n_gas, n_otro = (cargos.filter(servicio=k).count() for k in ('ELEC', 'GAS', 'OTRO'))
    c.update(n_luz=n_luz, n_gas=n_gas, n_otro=n_otro, cargos_desactualizados=bool(filas) and cargos.count() != lineas_cargo)
    fija = FechaUFMes.objects.filter(sociedad=soc, periodo=p).first()
    fecha_uf = fija.fecha if fija else _fecha_uf_mes(p)
    c.update(fecha_uf=fecha_uf, fecha_uf_fija=fija, uf_elegida=UF.objects.filter(fecha=fecha_uf).first(),
             hay_ph=servicios.contratos_del_mes(soc, p.year, p.month).filter(regla_uf='PH').exists())
    c.update(filas=filas, sin_doc=sin_doc, tot=tot, ventas_pend=_ventas_pendientes(soc, p),
             hay_borradores=any(f['d'].estado == 'B' for f in filas), hay_aprobados=any(f['d'].estado in 'AX' for f in filas),
             hay_facturas=any(f['d'].estado in 'AX' and f['d'].tipo_documento != 'NC' for f in filas),
             hay_notas=any(f['d'].estado in 'AX' and f['d'].tipo_documento == 'NC' for f in filas),
             emitidas_revisar=FacturaEmitida.objects.filter(sociedad=soc, estado__in=('D', 'S', 'I')).count(),
             uf=UF.objects.filter(fecha=fecha_uf).first())
    return render(request, 'panel/facturacion.html', c)


@requiere_operacion
@require_POST
def generar(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    try:
        r = servicios.generar_borradores(soc, p.year, p.month)
    except Exception as e:
        messages.error(request, f'No se pudo generar: {e}')
        return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')
    messages.success(request, f'Se generaron {len(r.creados)} borradores' + (f' ({len(r.reemplazados)} reemplazaron a un borrador anterior)' if r.reemplazados else '') + '.')
    for cod, motivo in r.omitidos:
        messages.info(request, f'{cod} sin documento: {motivo}')
    return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')


@requiere_operacion
@require_POST
def aprobar_todo(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    forzar = request.POST.get('forzar') == '1' and puede_forzar(request.user)
    ok, bloq = servicios.aprobar(soc, p.year, p.month, request.user.get_username(), None, forzar)
    messages.success(request, f'{len(ok)} documentos aprobados.')
    if bloq:
        messages.warning(request, f'{len(bloq)} quedaron pendientes por advertencias: ' + ', '.join(c for c, _ in bloq) + '. Revíselos uno a uno.')
    return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')


@requiere_operacion
@require_POST
def volver_borrador_todo(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    n = Documento.objects.filter(contrato__sociedad=soc, periodo=p, estado='A').update(estado='B', aprobado_por='', aprobado_en=None)
    messages.success(request, f'{n} documentos aprobados volvieron a borrador. Ahora puede regenerar los borradores.')
    return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')


@login_required
def exportar_excel(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    incluir_borradores = request.GET.get('borradores') == '1'
    try:
        ruta = exportar.exportar_excel(soc, p.year, p.month, estados=('B', 'A', 'X') if incluir_borradores else ('A', 'X'))
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')
    return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=os.path.basename(ruta))


@requiere_operacion
def exportar_xml(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    try:
        carpeta, zpath, archivos = bsoft.exportar_xml(soc, p.year, p.month, estados=('A', 'X'))
    except (ValueError, bsoft.FaltanCodigos) as e:
        messages.error(request, str(e))
        return redirect(f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}')
    Documento.objects.filter(contrato__sociedad=soc, periodo=p, estado='A').exclude(tipo_documento='NC').update(estado='X')
    return FileResponse(open(zpath, 'rb'), as_attachment=True, filename=os.path.basename(zpath))


# ------------------------------------------------------------------ documento
@login_required
def documento(request, pk):
    d = get_object_or_404(Documento.objects.select_related('contrato__arrendatario', 'contrato__sociedad', 'contrato__propiedad'), pk=pk)
    c = ctx_base(request, periodo=d.periodo)
    c['sociedad'] = d.contrato.sociedad
    c.update(d=d, lineas=d.lineas.all(), graves=motor_graves(d), notas=[a for a in d.advertencias if str(a).startswith('Nota:')])
    return render(request, 'panel/documento.html', c)


@requiere_operacion
@require_POST
def documento_accion(request, pk):
    d = get_object_or_404(Documento, pk=pk)
    accion = request.POST.get('accion')
    if accion == 'aprobar':
        if motor_graves(d) and not (request.POST.get('forzar') == '1' and puede_forzar(request.user)):
            messages.error(request, 'Tiene advertencias. Solo un administrador puede aprobarlo igual.')
        elif d.estado == 'B':
            servicios.marcar_aprobado(d, request.user.get_username())
            messages.success(request, f'Documento aprobado con el n.º interno {d.numero_interno}.')
    elif accion == 'borrador' and d.estado == 'A':
        d.estado, d.aprobado_por, d.aprobado_en = 'B', '', None
        d.save()
        messages.success(request, 'Volvió a borrador.')
    elif accion == 'anular' and d.estado in ('B', 'A') and puede_forzar(request.user):
        d.estado = 'N'
        d.save()
        messages.success(request, 'Documento anulado.')
    return redirect('documento', pk=d.pk)


# ------------------------------------------------------------------ contratos
@login_required
def contratos(request):
    c = ctx_base(request)
    q = (request.GET.get('q') or '').strip()
    solo = request.GET.get('sociedad_todas') == '1'
    qs = Contrato.objects.select_related('arrendatario', 'sociedad', 'propiedad').prefetch_related(
        'locales', Prefetch('archivos', queryset=ArchivoContrato.objects.exclude(estado='E').order_by('nombre')))
    if not solo:
        qs = qs.filter(sociedad=c['sociedad'])
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(nombre_fantasia__icontains=q) | Q(arrendatario__razon_social__icontains=q) | Q(arrendatario__rut__icontains=q))
    hoy = timezone.localdate()
    filas = []
    for ct in qs:
        t = ct.tramos.filter(desde__lte=hoy).filter(Q(hasta__isnull=True) | Q(hasta__gte=hoy)).first()
        filas.append(dict(c=ct, tramo=t, locales=', '.join(l.codigo_plano for l in ct.locales.all())))
    soc = c['sociedad']
    c.update(filas=filas, q=q, solo=solo, archivos_pendientes=ArchivoContrato.objects.filter(sociedad=soc, estado__in=('N', 'C'), ignorar=False).count(),
             propuestas_listas=PropuestaIA.objects.filter(archivo__sociedad=soc, estado='L').count())
    return render(request, 'panel/contratos.html', c)


@login_required
def contrato(request, codigo):
    ct = get_object_or_404(Contrato.objects.select_related('arrendatario', 'sociedad', 'propiedad'), codigo=codigo)
    c = ctx_base(request)
    hoy = timezone.localdate()
    c['sociedad'] = ct.sociedad
    sim = None
    pe = _periodo(request, 'sim') if request.GET.get('sim') else None
    if pe:
        try:
            r, lineas = servicios.calcular_contrato(ct, pe.year, pe.month)
            neto = sum(l.neto for l in lineas)
            afecto, exento, iva, total = motor.totales(neto, ct.tipo_documento, D(str(servicios.settings.TASA_IVA)))
            sim = dict(periodo=pe, r=r, lineas=lineas, neto=neto, iva=iva, total=total, exento=exento)
        except Exception as e:
            sim = dict(periodo=pe, error=str(e))
    fin0, vig, k = motor.vencimiento(servicios.a_contrato_d(ct), ct.plazo_meses, ct.prorroga_meses, ct.fin_pactado, hoy)
    venc = dict(plazo_inicial=fin0, vigente=vig, prorrogas=k)
    c.update(ct=ct, tramos=ct.tramos.all(), descuentos=ct.descuentos.all(), saldos=ct.saldos.all(), locales=ct.contratolocal_set.select_related('local'),
             documentos=ct.documentos.exclude(estado='N').order_by('-periodo')[:24], cargos=ct.consumos.all()[:12], medidores=ct.medidores.all(),
             ventas=ct.ventas.all()[:12], sim=sim, venc=venc, hoy=hoy,
             alertas=[a for a in servicios.alertas_vigentes(hoy, 365) if a[0] == ct.codigo], sim_default=f'{hoy:%Y-%m}',
             archivos=ct.archivos.order_by('estado', 'nombre'), historial=ct.cambios.all()[:60],
             propuestas=ct.propuestas.exclude(estado__in=('A', 'D')).select_related('archivo'))
    return render(request, 'panel/contrato.html', c)


# ------------------------------------------------------------------ cargas
def _guardar_tmp(f):
    sufijo = os.path.splitext(f.name)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as t:
        for chunk in f.chunks():
            t.write(chunk)
        return t.name


@login_required
def cargas_vista(request):
    c = ctx_base(request)
    p, soc = c['periodo'], c['sociedad']
    consumo_def = _mes_vecino(p, -1)
    c.update(consumo_def=f'{consumo_def:%Y-%m}', cobro_def=f'{p:%Y-%m}',
             cargos=ConsumoServicio.objects.filter(contrato__sociedad=soc, periodo_cobro=p).select_related('contrato', 'medidor_ref').order_by('servicio', 'contrato__codigo'),
             variables=servicios.contratos_del_mes(soc, p.year, p.month).exclude(base_variable=''), ventas_pend=_ventas_pendientes(soc, p),
             ventas=VentaMensual.objects.filter(contrato__sociedad=soc).select_related('contrato').order_by('-periodo', 'contrato__codigo')[:15],
             mes_ventas=f'{_mes_vecino(p, -1):%Y-%m}')
    meses_cmp, filas_cmp = comparacion.comparar(soc, p)
    solo_alertas = request.GET.get('alertas') == '1'
    c.update(meses_cmp=meses_cmp, filas_cmp=[f for f in filas_cmp if f.luz in ('amarillo', 'rojo')] if solo_alertas else filas_cmp,
             solo_alertas=solo_alertas, n_rojo=sum(f.luz == 'rojo' for f in filas_cmp), n_amarillo=sum(f.luz == 'amarillo' for f in filas_cmp),
             n_verde=sum(f.luz == 'verde' for f in filas_cmp))
    c['planillas_genericas'] = [
        ('agua', 'Agua', 'Planilla mensual de agua (.xlsx o .xls): una fila por local con su monto neto (y, si la trae, el consumo en m³). Asignación por medidor + IA, con revisión.'),
        ('gastos_comunes', 'Gastos comunes', 'Planilla mensual de gastos comunes (.xlsx o .xls): una fila por local o arrendatario con su monto neto. Asignación automática + IA, con revisión.')]
    c.update(planillas=CargaPlanilla.objects.filter(sociedad=soc, estado__in=('P', 'L')),
             contratos_soc=Contrato.objects.filter(sociedad=soc, activo=True).order_by('codigo'))
    r = request.session.pop('resultado_carga', None)
    if r:
        c['resultado'] = r
    return render(request, 'panel/cargas.html', c)


@requiere_operacion
@require_POST
def cargar_archivo(request):
    tipo = request.POST.get('tipo')
    f = request.FILES.get('archivo')
    p, (soc, _) = _periodo(request), _sociedad(request)
    if not f:
        messages.error(request, 'Elija un archivo.')
        return redirect(f'/cargas/?sociedad={soc.id}&periodo={p:%Y-%m}')
    ruta = _guardar_tmp(f)
    try:
        if tipo == 'otros':
            res = cargas.cargar_otros(lectores.leer_otros(ruta), f.name)
            info = f'{res.cargados} cargos "otros" cargados por ${motor.fmt_clp(int(res.total))}.'
        else:
            a, m = (request.POST.get('consumo') or '').split('-')
            consumo = date(int(a), int(m), 1)
            cobro = date(*map(int, (request.POST.get('cobro') or '').split('-')), 1) if request.POST.get('cobro') else cargas.mes_siguiente(consumo)
            if tipo not in SERVICIO_DE_TIPO:
                raise lectores.PlanillaInvalida('tipo de planilla desconocido')
            hoja = None
            try:   # formato de Boulevard para luz y gas; si no calza, el formato simple (Plaza Motor, agua, gastos comunes)
                if tipo == 'electricidad':
                    mes_txt, filas = lectores.leer_electricidad(ruta)
                    if mes_txt and lectores.norm(mes_txt) != lectores.MESES[consumo.month - 1]:
                        raise ValueError(f'La planilla es de «{mes_txt}», pero indicó consumo de {motor.MESES[consumo.month]}.')
                elif tipo == 'gas':
                    _, filas = lectores.leer_gas(ruta, consumo.year, consumo.month)
                else:
                    raise lectores.PlanillaInvalida('formato simple')
            except lectores.PlanillaInvalida:
                hoja, filas = lectores.leer_generica(ruta, SERVICIO_DE_TIPO[tipo])
            mes_hoja = lectores.mes_de_hoja(hoja) if hoja else None
            if mes_hoja and mes_hoja != (consumo.year, consumo.month):
                raise lectores.PlanillaInvalida(f'La hoja «{hoja}» es de {motor.MESES[mes_hoja[1]]} {mes_hoja[0]}, pero indicó '
                                                f'{motor.MESES[consumo.month]} {consumo.year}. Revise el mes antes de cargar.')
            if not filas:
                raise lectores.PlanillaInvalida('no se encontraron filas con cobro en la planilla')
            carga = asignacion.preparar(soc, SERVICIO_DE_TIPO[tipo], filas, consumo, cobro, f.name, request.user.get_username())
            return redirect('planilla', pk=carga.pk)
        cobro_p = cobro if tipo != 'otros' else None
        pendientes = Documento.objects.filter(contrato__sociedad=soc, periodo=cobro_p, estado__in=('A', 'X')).count() if cobro_p else 0
        request.session['resultado_carga'] = dict(info=info, aprobados_previos=pendientes, sin_asignar=[list(map(str, x)) for x in res.sin_medidor], en_cero=res.en_cero,
                                                  por_confirmar=len(res.por_confirmar))
    except (lectores.PlanillaInvalida, ValueError) as e:
        messages.error(request, f'No se pudo leer la planilla: {e}')
    finally:
        os.unlink(ruta)
    return redirect(f'/cargas/?sociedad={soc.id}&periodo={p:%Y-%m}')


@requiere_operacion
@require_POST
def guardar_venta(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    try:
        ct = Contrato.objects.get(codigo=request.POST['contrato'])
        a, m = request.POST['mes_ventas'].split('-')
        monto = D(request.POST['monto'].replace('.', '').replace(',', '.').replace('$', '').strip())
        VentaMensual.objects.update_or_create(contrato=ct, periodo=date(int(a), int(m), 1),
                                              defaults={'monto_neto': monto.quantize(D('1')), 'fuente': f'ingreso manual ({request.user.get_username()})'})
        messages.success(request, f'Ventas de {ct.nombre_fantasia} para {motor.MESES[int(m)]} {a} guardadas.')
    except (KeyError, ValueError, InvalidOperation, Contrato.DoesNotExist):
        messages.error(request, 'Revise el contrato, el mes y el monto.')
    return redirect(f'/cargas/?sociedad={soc.id}&periodo={p:%Y-%m}')


@requiere_operacion
@require_POST
def borrar_cargo(request, pk):
    cs = get_object_or_404(ConsumoServicio, pk=pk)
    cs.delete()
    messages.success(request, 'Cargo eliminado.')
    return redirect(request.POST.get('volver') or 'cargas')


# ------------------------------------------------------------------ medidores, alertas, indicadores
@login_required
def medidores(request):
    c = ctx_base(request)
    c['meds'] = MedidorServicio.objects.select_related('contrato').order_by('confirmado', 'servicio', 'contrato__codigo')
    c['contratos'] = Contrato.objects.order_by('codigo')
    return render(request, 'panel/medidores.html', c)


@requiere_operacion
@require_POST
def medidor_accion(request, pk):
    m = get_object_or_404(MedidorServicio, pk=pk)
    if request.POST.get('accion') == 'confirmar':
        nuevo = Contrato.objects.filter(codigo=request.POST.get('contrato')).first()
        if nuevo:
            m.contrato = nuevo
        m.confirmado = True
        m.save()
        messages.success(request, f'Medidor «{m.nombre_planilla}» confirmado en {m.contrato.codigo}.')
    elif request.POST.get('accion') == 'desconfirmar':
        m.confirmado = False
        m.save()
    return redirect('medidores')


@login_required
def alertas(request):
    c = ctx_base(request)
    dias = int(request.GET.get('dias') or 180)
    c.update(filas=servicios.alertas_vigentes(timezone.localdate(), dias), dias=dias)
    return render(request, 'panel/alertas.html', c)


@login_required
def indicadores(request):
    c = ctx_base(request)
    p = c['periodo']
    c.update(ufs=UF.objects.filter(fecha__gte=date(p.year, p.month, 1) - __import__('datetime').timedelta(days=45)).order_by('-fecha')[:60],
             uf_mes=UF.objects.filter(fecha=p).first(), n_prueba=UF.objects.filter(origen='PRUEBA').count(),
             ipcs=IPC.objects.filter(anio__in=[p.year - 1, p.year]), con_token=bool(ind.token_bcentral()))
    return render(request, 'panel/indicadores.html', c)


@requiere_operacion
@require_POST
def indicador_accion(request):
    accion = request.POST.get('accion')
    if accion == 'actualizar':
        for año in ind.años_por_defecto(timezone.localdate()):
            for nombre, f in (('UF', ind.cargar_uf_anio), ('IPC', ind.cargar_ipc_anio)):
                try:
                    messages.success(request, f'{nombre} {año}: {f(año)}.')
                except ind.AunNoPublicado:
                    pass
                except Exception as e:
                    messages.error(request, f'{nombre} {año}: no se pudo cargar ({e}). La UF se puede ingresar a mano.')
    elif accion == 'manual':
        try:
            f = date.fromisoformat(request.POST['fecha'])
            v = D(request.POST['valor'].replace('.', '').replace(',', '.'))
            UF.objects.update_or_create(fecha=f, defaults={'valor': v.quantize(D('0.01')), 'origen': 'MANUAL'})
            messages.success(request, f'UF del {f:%d-%m-%Y} guardada.')
        except Exception:
            messages.error(request, 'Revise la fecha y el valor de la UF.')
    return redirect('indicadores')


# ------------------------------------------------------------------ PWA
def manifest(request):
    return JsonResponse({
        'name': 'Sistema Facturación · Contratos y facturación', 'short_name': 'Facturación', 'start_url': '/', 'scope': '/',
        'display': 'standalone', 'background_color': '#f5f7fa', 'theme_color': '#1f3a5f', 'lang': 'es-CL',
        'icons': [{'src': '/static/panel/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                  {'src': '/static/panel/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                  {'src': '/static/panel/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}]},
        content_type='application/manifest+json')


def service_worker(request):
    js = '''const V='brisas-v1';const ARCH=['/static/panel/app.css','/static/panel/icon-192.png','/offline/'];
self.addEventListener('install',e=>e.waitUntil(caches.open(V).then(c=>c.addAll(ARCH)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==V).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const r=e.request;if(r.method!=='GET')return;const u=new URL(r.url);
if(u.pathname.startsWith('/static/')){e.respondWith(caches.match(r).then(h=>h||fetch(r).then(x=>{const cp=x.clone();caches.open(V).then(c=>c.put(r,cp));return x})));return}
e.respondWith(fetch(r).catch(()=>caches.match('/offline/')))});'''
    resp = HttpResponse(js, content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    return resp


def offline(request):
    return render(request, 'panel/offline.html')


# ------------------------------------------------------------------ planillas de luz y gas: revisión de la asignación
@login_required
def planilla(request, pk):
    carga = get_object_or_404(CargaPlanilla.objects.select_related('sociedad'), pk=pk)
    volver = f'/cargas/?sociedad={carga.sociedad_id}&periodo={carga.periodo_cobro:%Y-%m}'
    if request.method == 'POST':
        if not puede_operar(request.user):
            raise PermissionDenied
        if request.POST.get('accion') == 'descartar':
            carga.estado = CargaPlanilla.Estado.DESCARTADA
            carga.save()
            messages.info(request, 'Planilla descartada: no se cargó nada.')
            return redirect(volver)
        asig = {d['fila']: request.POST.get(f'c_{d["fila"]}', '') for d in carga.filas}
        try:
            res = asignacion.confirmar(carga, asig, request.user.get_username())
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('planilla', pk=carga.pk)
        pendientes = Documento.objects.filter(contrato__sociedad=carga.sociedad, periodo=carga.periodo_cobro, estado__in=('A', 'X')).count()
        messages.success(request, f'{NOMBRE_SERVICIO.get(carga.servicio, carga.servicio)}: {carga.resultado}.')
        if pendientes:
            messages.warning(request, f'{pendientes} documentos de ese mes ya estaban aprobados y no incluyen estos cargos: en Facturación use '
                                      '«Volver aprobados a borrador» y luego «Regenerar borradores».')
        return redirect(volver)
    c = ctx_base(request, periodo=carga.periodo_cobro)
    c['sociedad'] = carga.sociedad
    filas = carga.filas
    mega = set()
    if carga.servicio in ('GGCC', 'AGUA'):
        campo = 'cobra_gastos_comunes' if carga.servicio == 'GGCC' else 'cobra_agua'
        mega = set(Contrato.objects.filter(sociedad=carga.sociedad, **{campo: 'MEGA'}).values_list('codigo', flat=True))
    for d in filas:
        d['neto_int'] = int(D(d['neto']))
        d['mega'] = d.get('contrato') in mega
    c.update(carga=carga, filas=filas, contratos=Contrato.objects.filter(sociedad=carga.sociedad).order_by('codigo'),
             n_ia=sum(d['fuente'] == 'IA' for d in filas), n_conf=sum(d['fuente'] == 'medidor confirmado' for d in filas),
             n_sin=sum(not d['contrato'] and d['neto_int'] != 0 for d in filas), total=sum(d['neto_int'] for d in filas))
    return render(request, 'panel/planilla.html', c)


@requiere_operacion
@require_POST
def otro_manual(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    try:
        ct = Contrato.objects.get(codigo=request.POST['contrato'], sociedad=soc)
        a, m = request.POST['mes_cobro'].split('-')
        cobro = date(int(a), int(m), 1)
        neto = D(request.POST['neto'].replace('.', '').replace('$', '').replace(',', '.').strip()).quantize(D('1'))
        concepto = (request.POST.get('concepto') or '').strip().upper() or 'OTRO CARGO'
        ConsumoServicio.objects.create(contrato=ct, servicio='OTRO', concepto=concepto[:80], detalle=(request.POST.get('detalle') or '')[:200],
                                       periodo_consumo=cobro, periodo_cobro=cobro, neto=neto,
                                       origen_archivo=f'manual ({request.user.get_username()})')
        messages.success(request, f'Cargo «{concepto}» de {motor.fmt_clp(int(neto))} agregado a {ct.codigo} para la factura de {motor.MESES[cobro.month]} {cobro.year}.')
        if Documento.objects.filter(contrato=ct, periodo=cobro, estado__in=('A', 'X')).exists():
            messages.warning(request, 'El documento de ese mes ya estaba aprobado: vuélvalo a borrador y regenere para incluir el cargo.')
    except (KeyError, ValueError, InvalidOperation, Contrato.DoesNotExist):
        messages.error(request, 'Revise el contrato, el mes y el monto del cargo.')
    return redirect(f'/cargas/?sociedad={soc.id}&periodo={p:%Y-%m}')


@requiere_operacion
@require_POST
def fecha_uf(request):
    """Fija (o vuelve al día 1) la fecha de la UF para la sociedad y el mes. Se aplica a todos sus contratos ese mes."""
    p, (soc, _) = _periodo(request), _sociedad(request)
    volver = f'/facturacion/?sociedad={soc.id}&periodo={p:%Y-%m}'
    if request.POST.get('accion') == 'dia1':
        FechaUFMes.objects.filter(sociedad=soc, periodo=p).delete()
        messages.success(request, f'Se vuelve a usar la UF del día 1 (o del primer día hábil según cada contrato). Regenere los borradores.')
    else:
        try:
            f = date.fromisoformat(request.POST.get('fecha', ''))
        except ValueError:
            messages.error(request, 'Elija una fecha válida.')
            return redirect(volver)
        uf = UF.objects.filter(fecha=f).first()
        if not uf:
            messages.error(request, f'La UF del {f:%d-%m-%Y} no está cargada. Cárguela en UF / IPC (o ingrésela a mano) y vuelva a intentar.')
            return redirect(volver)
        FechaUFMes.objects.update_or_create(sociedad=soc, periodo=p, defaults={'fecha': f, 'usuario': request.user.get_username()})
        messages.success(request, f'Para {motor.MESES[p.month]} {p.year} se usará la UF del {f:%d-%m-%Y} ({motor.fmt_uf(uf.valor)}) en todos los contratos de {soc.nombre}. Regenere los borradores.')
    if Documento.objects.filter(contrato__sociedad=soc, periodo=p, estado__in=('A', 'X')).exists():
        messages.warning(request, 'Hay documentos aprobados o exportados: no cambian. Para aplicarles la nueva fecha use «Volver aprobados a borrador» y regenere.')
    return redirect(volver)
