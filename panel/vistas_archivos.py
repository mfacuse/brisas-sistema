"""Pantallas de archivos: carpetas por sociedad, archivos de contratos (con lectura por IA), edición e historial de contratos,
notas de cobro en PDF y facturas emitidas por BSOFT."""
import os
from datetime import date
from pathlib import Path

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from facturacion import emitidas, nota_cobro
from facturacion.models import Documento, FacturaEmitida
from maestro import almacen, carpetas, ia
from maestro.models import ActaEntrega, ArchivoContrato, Contrato, EventoArchivo, PropuestaIA, Propiedad, RegistroCambio, Sociedad

from .permisos import puede_forzar, requiere_operacion
from .views import _periodo, _sociedad, ctx_base


def requiere_admin(vista):
    @login_required
    def envuelta(request, *a, **k):
        if not puede_forzar(request.user):
            raise PermissionDenied('Solo un administrador puede cambiar la configuración.')
        return vista(request, *a, **k)
    envuelta.__name__ = vista.__name__
    return envuelta


def _usuario(request):
    return request.user.get_username()


def _servir(ruta: str, nombre: str, tipo='application/pdf'):
    """Entrega un archivo de las carpetas configuradas (Mac dentro de Drive/OneDrive, o Google Drive por internet)."""
    from urllib.parse import quote
    try:
        datos = almacen.leer(ruta)
    except almacen.CarpetaNoPermitida:
        raise Http404('Archivo fuera de las carpetas permitidas.')
    except Exception:
        raise Http404('El archivo ya no está en la carpeta (o Google Drive no está disponible).')
    r = HttpResponse(datos, content_type=tipo)
    r['Content-Disposition'] = f"inline; filename*=UTF-8''{quote(nombre)}"
    return r


def _servir_pdf(ruta: str, nombre: str):
    return _servir(ruta, nombre)


# ------------------------------------------------------------------ carpetas y configuración por sociedad
class SociedadForm(forms.ModelForm):
    class Meta:
        model = Sociedad
        fields = ['sigla', 'giro', 'direccion', 'datos_pago']
        widgets = {'datos_pago': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Banco, tipo y n.º de cuenta, RUT, correo para avisar el pago'})}


@login_required
def configuracion(request):
    c = ctx_base(request)
    filas = []
    for s in Sociedad.objects.order_by('id'):
        filas.append(dict(s=s, form=SociedadForm(instance=s, prefix=f's{s.pk}'),
                          pendientes=s.archivos_contrato.filter(estado__in=('N', 'C'), ignorar=False).count(),
                          archivos=s.archivos_contrato.exclude(estado='E').count()))
    c.update(drive_ok=almacen.drive_configurado(), drive_correo=almacen.correo_cuenta_servicio(), drive_cliente=bool(almacen.cliente_oauth()),
             drive_volver=request.build_absolute_uri(reverse('drive_volver')), puede_respaldar=almacen.puede_respaldar())
    from maestro import respaldos
    c['respaldo'] = respaldos.ultimo()
    c.update(filas=filas, clave=ia.clave_configurada(), modelo=ia.settings.IA_MODELO,
             historial=RegistroCambio.objects.filter(objeto='Sociedad')[:20])
    return render(request, 'panel/configuracion.html', c)


@requiere_admin
@require_POST
def configuracion_guardar(request):
    s = get_object_or_404(Sociedad, pk=request.POST.get('sociedad'))
    accion = request.POST.get('accion')
    if accion == 'datos':
        f = SociedadForm(request.POST, instance=s, prefix=f's{s.pk}')
        if f.is_valid():
            f.save()
            messages.success(request, f'Datos de {s.nombre} guardados.')
        else:
            messages.error(request, 'Revise los datos: ' + '; '.join(f'{k}: {v[0]}' for k, v in f.errors.items()))
    elif accion in ('carpeta', 'quitar') and request.POST.get('tipo') == 'planos':
        from maestro import planos as mp
        from maestro.models import Propiedad
        prop = get_object_or_404(Propiedad, pk=request.POST.get('propiedad'), sociedad=s)
        ruta = ''
        if accion == 'carpeta':
            try:
                ruta = carpetas.validar(request.POST.get('ruta', ''))
            except carpetas.CarpetaNoPermitida as e:
                messages.error(request, str(e))
                return redirect('configuracion')
        prop.carpeta_planos = ruta
        prop.save()
        messages.success(request, f'Carpeta de planos de {prop.nombre}: {ruta or "(sin carpeta)"}.')
        if ruta:
            messages.info(request, mp.importar_propiedad(prop))
    elif accion in ('carpeta', 'quitar'):
        tipo = request.POST.get('tipo')
        campo = {'contratos': 'carpeta_contratos', 'facturas': 'carpeta_facturas', 'actas': 'carpeta_actas'}.get(tipo)
        if not campo:
            raise Http404
        ruta = ''
        if accion == 'carpeta':
            try:
                ruta = carpetas.validar(request.POST.get('ruta', ''))
            except carpetas.CarpetaNoPermitida as e:
                messages.error(request, str(e))
                return redirect('configuracion')
        setattr(s, campo, ruta)
        s.save()
        nombre = {'contratos': 'contratos', 'facturas': 'facturas emitidas', 'actas': 'actas de entrega'}[tipo]
        messages.success(request, f'Carpeta de {nombre} de {s.nombre}: {ruta or "(sin carpeta)"}.')
        if ruta and tipo == 'contratos':
            r = carpetas.revisar(s, _usuario(request))
            messages.info(request, f'Revisión: {r}')
        elif ruta and tipo == 'actas':
            messages.info(request, f'Actas: {carpetas.revisar_actas(s)}')
        elif ruta:
            messages.info(request, f'Facturas: {emitidas.revisar(s)}')
    return redirect('configuracion')


@requiere_admin
@require_POST
def clave_ia(request):
    ia.guardar_clave(request.POST.get('clave', ''))
    messages.success(request, 'Clave de la IA guardada.' if ia.clave_configurada() else 'Clave de la IA eliminada.')
    return redirect('configuracion')


@requiere_admin
def elegir_carpeta(request):
    s = get_object_or_404(Sociedad, pk=request.GET.get('sociedad'))
    tipo = request.GET.get('tipo', 'contratos')
    prop = s.propiedades.filter(pk=request.GET.get('propiedad')).first() if tipo == 'planos' else None
    ruta_txt = request.GET.get('ruta') or (prop.carpeta_planos if prop else getattr(s, {'contratos': 'carpeta_contratos', 'actas': 'carpeta_actas'}.get(tipo, 'carpeta_facturas'))) or ''
    actual, migas, subs, n_pdf, error = '', [], [], 0, ''
    try:
        if ruta_txt and almacen.existe_carpeta(ruta_txt):
            actual = almacen.validar_carpeta(ruta_txt)
        if actual:
            migas = almacen.migas(actual)
            subs = almacen.subcarpetas(actual)
            ext = {'.dxf'} if tipo == 'planos' else {'.pdf'}
            n_pdf = len(almacen.listar(actual, ext, recursivo=False))
        else:
            subs = almacen.raices()
    except Exception as e:   # Drive sin conexión o sin permiso
        error = f'No se pudo leer la carpeta: {e}'
    c = ctx_base(request)
    c.update(s=s, tipo=tipo, prop=prop, actual=actual, migas=migas, subs=subs, n_pdf=n_pdf, error=error,
             correo_drive=almacen.correo_cuenta_servicio() if almacen.drive_configurado() else '')
    return render(request, 'panel/elegir_carpeta.html', c)


# ------------------------------------------------------------------ archivos de contratos
@requiere_operacion
@require_POST
def revisar_carpeta(request):
    soc, _ = _sociedad(request)
    r = carpetas.revisar(soc, _usuario(request))
    (messages.error if r.error else messages.success)(request, f'Carpeta revisada · {r}')
    return redirect(request.POST.get('volver') or f'{reverse("archivos")}?sociedad={soc.id}')


@login_required
def archivos(request):
    c = ctx_base(request)
    soc = c['sociedad']
    qs = (ArchivoContrato.objects.filter(sociedad=soc).select_related('contrato')
          .prefetch_related('propuestas').order_by('nombre'))
    lista = list(qs)
    for a in lista:
        a.ultima = a.propuestas.all()[0] if a.propuestas.all() else None
    c.update(pendientes=[a for a in lista if a.pendiente], al_dia=[a for a in lista if a.estado == 'R' and not a.ignorar],
             ignorados=[a for a in lista if a.ignorar and a.estado != 'E'], eliminados=[a for a in lista if a.estado == 'E'],
             contratos=Contrato.objects.filter(sociedad=soc).order_by('codigo'), clave=ia.clave_configurada(),
             leyendo=any(a.ultima and a.ultima.estado == 'P' for a in lista),
             eventos=EventoArchivo.objects.filter(archivo__sociedad=soc).select_related('archivo')[:30])
    return render(request, 'panel/archivos.html', c)


@login_required
def archivo_abrir(request, pk):
    a = get_object_or_404(ArchivoContrato, pk=pk)
    return _servir_pdf(a.ruta, a.nombre)


@requiere_operacion
@require_POST
def archivo_accion(request, pk):
    a = get_object_or_404(ArchivoContrato, pk=pk)
    accion, u = request.POST.get('accion'), _usuario(request)
    volver = f'{reverse("archivos")}?sociedad={a.sociedad_id}'
    if accion == 'asociar':
        c = Contrato.objects.filter(pk=request.POST.get('contrato') or 0, sociedad=a.sociedad).first()
        a.contrato = c
        a.save()
        EventoArchivo.objects.create(archivo=a, tipo='ASOCIADO', usuario=u, detalle=f'asociado a {c.codigo}' if c else 'sin contrato')
        messages.success(request, f'«{a.nombre}» ' + (f'asociado a {c.codigo}.' if c else 'quedó sin contrato.'))
    elif accion == 'revisado':
        a.estado, a.revisado_por, a.revisado_en = 'R', u, timezone.now()
        a.save()
        EventoArchivo.objects.create(archivo=a, tipo='REVISADO', usuario=u, detalle='marcado como revisado (sin cambios en el contrato)')
        messages.success(request, f'«{a.nombre}» marcado como revisado.')
    elif accion in ('ignorar', 'no_ignorar'):
        a.ignorar = accion == 'ignorar'
        a.save()
        EventoArchivo.objects.create(archivo=a, tipo='IGNORADO' if a.ignorar else 'NO_IGNORADO', usuario=u)
    elif accion == 'ia':
        try:
            p = ia.iniciar(a, u)
            messages.info(request, f'La IA está leyendo «{a.nombre}» (tarda 1 a 3 minutos). La página se actualiza sola.')
            if p.estado != 'P':
                return redirect('propuesta', pk=p.pk)
        except ia.SinClave as e:
            messages.error(request, str(e))
    return redirect(volver)


@requiere_operacion
@require_POST
def leer_pendientes_ia(request):
    soc, _ = _sociedad(request)
    n = 0
    try:
        for a in ArchivoContrato.objects.filter(sociedad=soc, estado__in=('N', 'C'), ignorar=False):
            if a.propuestas.filter(estado__in=('P', 'L')).exists():
                continue
            ia.iniciar(a, _usuario(request))
            n += 1
    except ia.SinClave as e:
        messages.error(request, str(e))
    if n:
        messages.info(request, f'La IA está leyendo {n} archivos. Las propuestas aparecerán en unos minutos.')
    return redirect(f'{reverse("archivos")}?sociedad={soc.id}')


@login_required
def propuesta(request, pk):
    p = get_object_or_404(PropuestaIA.objects.select_related('archivo__sociedad', 'contrato__arrendatario'), pk=pk)
    c = ctx_base(request)
    c['sociedad'] = p.archivo.sociedad
    c.update(p=p, filas=ia.diferencias(p) if p.estado in ('L', 'A', 'D') else [], d=p.datos,
             contratos=Contrato.objects.filter(sociedad=p.archivo.sociedad).order_by('codigo'),
             propiedades=Propiedad.objects.filter(sociedad=p.archivo.sociedad))
    return render(request, 'panel/propuesta.html', c)


@requiere_operacion
@require_POST
def propuesta_accion(request, pk):
    p = get_object_or_404(PropuestaIA, pk=pk)
    accion, u = request.POST.get('accion'), _usuario(request)
    if accion == 'contrato' and p.estado == 'L':
        p.contrato = Contrato.objects.filter(pk=request.POST.get('contrato') or 0, sociedad=p.archivo.sociedad).first()
        p.save()
        return redirect('propuesta', pk=p.pk)
    if accion == 'descartar' and p.estado in ('L', 'E'):
        ia.descartar(p, u)
        messages.success(request, 'Propuesta descartada.')
        return redirect(f'{reverse("archivos")}?sociedad={p.archivo.sociedad_id}')
    if accion == 'aplicar':
        try:
            ct = ia.aplicar(p, request.POST.getlist('campo'), u, request.POST.get('propiedad') or None,
                           {k: request.POST.get(k, '') for k in ('inicio_vigencia', 'fecha_entrega', 'fecha_apertura', 'fecha_inicio_cobro')})
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('propuesta', pk=p.pk)
        messages.success(request, f'Cambios aplicados a {ct.codigo}. Quedaron en el historial del contrato.')
        return redirect('contrato', codigo=ct.codigo)
    return redirect('propuesta', pk=p.pk)


# ------------------------------------------------------------------ editar contrato e historial
class ContratoForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = ['nombre_fantasia', 'direccion_contrato', 'representante', 'tipo_documento', 'condicion_pago', 'fecha_contrato', 'inicio_vigencia',
                  'fecha_entrega', 'fecha_apertura', 'regla_inicio_cobro', 'dias_inicio_cobro', 'fecha_inicio_cobro',
                  'plazo_meses', 'fin_pactado', 'prorroga_meses', 'aviso_dias', 'fecha_termino_real', 'regla_uf', 'modo_cambio_tramo',
                  'tipo_renta', 'periodicidad', 'meses_cobro', 'reajuste_ipc', 'pct_variable', 'base_variable', 'variable_desde',
                  'm2_contrato', 'garantia_uf', 'garantia_clp', 'cobra_gastos_comunes', 'cobra_agua', 'autoriza_avisos', 'activo',
                  'condiciones', 'observaciones', 'locales']
        widgets = {k: forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
                   for k in ('fecha_contrato', 'inicio_vigencia', 'fecha_entrega', 'fecha_apertura', 'fecha_inicio_cobro', 'fin_pactado', 'fecha_termino_real', 'variable_desde')}
        widgets.update({'condiciones': forms.Textarea(attrs={'rows': 3}), 'observaciones': forms.Textarea(attrs={'rows': 3}),
                        'locales': forms.SelectMultiple(attrs={'size': 8})})

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields['locales'].queryset = self.fields['locales'].queryset.filter(propiedad=self.instance.propiedad_id)
        self.fields['locales'].required = False
        self.fields['locales'].help_text = 'Locales que arrienda (para el plano). Mantenga Cmd (⌘) apretado para elegir varios.'


@requiere_operacion
def contrato_editar(request, codigo):
    ct = get_object_or_404(Contrato, codigo=codigo)
    if request.method == 'POST':
        f = ContratoForm(request.POST, instance=ct)
        if f.is_valid():
            if 'fecha_inicio_cobro' in f.changed_data:
                # escrita a mano → no se recalcula sola; borrada → vuelve a calcularse con la regla y las fechas
                f.instance.inicio_cobro_auto = f.cleaned_data['fecha_inicio_cobro'] is None
            f.save()
            messages.success(request, 'Contrato guardado. El cambio quedó en el historial; los borradores se recalculan al regenerar.')
            return redirect('contrato', codigo=ct.codigo)
    else:
        f = ContratoForm(instance=ct)
    c = ctx_base(request)
    c['sociedad'] = ct.sociedad
    c.update(ct=ct, form=f)
    return render(request, 'panel/contrato_editar.html', c)


# ------------------------------------------------------------------ notas de cobro
@login_required
def nota_cobro_pdf(request, pk):
    d = get_object_or_404(Documento.objects.select_related('contrato__sociedad', 'contrato__arrendatario', 'contrato__propiedad'), pk=pk)
    try:
        datos = nota_cobro.pdf_nota(d)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('documento', pk=d.pk)
    r = HttpResponse(datos, content_type='application/pdf')
    r['Content-Disposition'] = f'inline; filename="{nota_cobro.nombre_archivo(d)}"'
    return r


@requiere_operacion
def notas_cobro_mes(request):
    p, (soc, _) = _periodo(request), _sociedad(request)
    try:
        zpath, docs = nota_cobro.exportar_mes(soc, p.year, p.month)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect(f'{reverse("facturacion")}?sociedad={soc.id}&periodo={p:%Y-%m}')
    Documento.objects.filter(pk__in=[d.pk for d in docs], estado='A').update(estado='X')
    return FileResponse(open(zpath, 'rb'), as_attachment=True, filename=os.path.basename(zpath))


# ------------------------------------------------------------------ facturas emitidas (BSOFT / SII)
@login_required
def facturas_emitidas(request):
    c = ctx_base(request)
    soc = c['sociedad']
    filtro = request.GET.get('estado', '')
    qs = FacturaEmitida.objects.filter(sociedad=soc).select_related('documento__contrato__arrendatario')
    if filtro:
        qs = qs.filter(estado=filtro)
    filas = list(qs[:300])
    libres = list(Documento.objects.filter(contrato__sociedad=soc, estado__in=('A', 'X'), emitida__isnull=True)
                  .exclude(tipo_documento='NC').select_related('contrato__arrendatario').order_by('-periodo', 'contrato__codigo')[:200])
    for f in filas:
        f.opciones = [d for d in libres if emitidas.rut_normal(d.contrato.arrendatario.rut) == f.rut_receptor] or libres
    cuenta = dict(FacturaEmitida.objects.filter(sociedad=soc).values_list('estado').annotate(n=Count('id')))
    c.update(filas=filas, filtro=filtro, cuenta=cuenta, estados=FacturaEmitida.Estado.choices)
    return render(request, 'panel/emitidas.html', c)


@requiere_operacion
@require_POST
def revisar_emitidas(request):
    soc, _ = _sociedad(request)
    r = emitidas.revisar(soc)
    (messages.error if r.error else messages.success)(request, f'Facturas emitidas · {r}')
    return redirect(request.POST.get('volver') or f'{reverse("facturas_emitidas")}?sociedad={soc.id}')


@login_required
def emitida_abrir(request, pk):
    f = get_object_or_404(FacturaEmitida, pk=pk)
    return _servir_pdf(f.ruta, f.nombre)


@requiere_operacion
@require_POST
def emitida_accion(request, pk):
    f = get_object_or_404(FacturaEmitida, pk=pk)
    u = _usuario(request)
    try:
        if request.POST.get('accion') == 'vincular':
            d = get_object_or_404(Documento, pk=request.POST.get('documento'), contrato__sociedad=f.sociedad)
            emitidas.vincular_manual(f, d, u)
            messages.success(request, f'Folio {f.folio} vinculado a {d.numero_interno or d}.')
        elif request.POST.get('accion') == 'desvincular':
            emitidas.desvincular(f, u)
            messages.success(request, f'Folio {f.folio} desvinculado.')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect(f'{reverse("facturas_emitidas")}?sociedad={f.sociedad_id}')


# ------------------------------------------------------------------ actas de entrega de locales
class ActaForm(forms.ModelForm):
    class Meta:
        model = ActaEntrega
        fields = ['contrato', 'numero', 'fecha_entrega', 'inicio_gastos_comunes', 'locales', 'entrega_por', 'recibe', 'lecturas', 'observaciones']
        widgets = {'fecha_entrega': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'inicio_gastos_comunes': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'lecturas': forms.Textarea(attrs={'rows': 3}), 'observaciones': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *a, sociedad=None, **k):
        super().__init__(*a, **k)
        self.fields['contrato'].queryset = Contrato.objects.filter(sociedad=sociedad).order_by('codigo')


@login_required
def actas(request):
    c = ctx_base(request)
    soc = c['sociedad']
    lista = ActaEntrega.objects.filter(sociedad=soc).select_related('contrato').order_by('ya_no_esta', 'estado', 'nombre')
    c.update(actas=lista, sin_leer=lista.filter(estado='S', ya_no_esta=False).count(), contratos=Contrato.objects.filter(sociedad=soc).order_by('codigo'), clave=ia.clave_configurada(),
             leyendo=lista.filter(estado='P').exists())
    return render(request, 'panel/actas.html', c)


@requiere_operacion
@require_POST
def acta_subir(request):
    soc, _ = _sociedad(request)
    f = request.FILES.get('archivo')
    if not f or Path(f.name).suffix.lower() not in ia.TIPOS_ACTA:
        messages.error(request, 'Elija un archivo PDF, JPG o PNG del acta.')
        return redirect(f'{reverse("actas")}?sociedad={soc.id}')
    acta = ActaEntrega(sociedad=soc, nombre=f.name[:255], subida_por=_usuario(request),
                       contrato=Contrato.objects.filter(pk=request.POST.get('contrato') or 0, sociedad=soc).first())
    acta.archivo.save(f.name, f, save=False)
    acta.save()
    if ia.clave_configurada():
        ia.iniciar_acta(acta)
        messages.info(request, f'Acta «{f.name}» subida. La IA está rescatando sus datos (1 a 2 minutos).')
    else:
        messages.info(request, f'Acta «{f.name}» subida. Sin clave de IA: complete los datos a mano.')
    return redirect('acta', pk=acta.pk)


@login_required
def acta(request, pk):
    a = get_object_or_404(ActaEntrega.objects.select_related('sociedad', 'contrato'), pk=pk)
    if request.method == 'POST':
        if not puede_operar_usuario(request):
            raise PermissionDenied
        accion = request.POST.get('accion')
        if accion == 'ia':
            try:
                ia.iniciar_acta(a)
                messages.info(request, 'La IA está leyendo el acta.')
            except ia.SinClave as e:
                messages.error(request, str(e))
            return redirect('acta', pk=a.pk)
        f = ActaForm(request.POST, instance=a, sociedad=a.sociedad)
        if f.is_valid():
            f.save()
            if accion == 'registrar':
                try:
                    c = ia.registrar_acta(a, _usuario(request))
                    messages.success(request, f'Fecha de entrega {a.fecha_entrega:%d-%m-%Y} registrada en {c.codigo}.'
                                     + (f' Inicio de cobro: {c.fecha_inicio_cobro:%d-%m-%Y}.' if c.fecha_inicio_cobro else ''))
                    return redirect('contrato', codigo=c.codigo)
                except ValueError as e:
                    messages.error(request, str(e))
            else:
                messages.success(request, 'Acta guardada.')
            return redirect('acta', pk=a.pk)
    else:
        f = ActaForm(instance=a, sociedad=a.sociedad)
    c = ctx_base(request)
    c['sociedad'] = a.sociedad
    c.update(a=a, form=f, d=a.datos, clave=ia.clave_configurada())
    return render(request, 'panel/acta.html', c)


def puede_operar_usuario(request):
    from .permisos import puede_operar
    return puede_operar(request.user)


@login_required
def acta_archivo(request, pk):
    a = get_object_or_404(ActaEntrega, pk=pk)
    tipo = ia.TIPOS_ACTA.get(a.extension, 'application/octet-stream')
    try:
        if a.ruta:
            return _servir(a.ruta, a.nombre, tipo)
        return FileResponse(a.archivo.open('rb'), content_type=tipo, filename=a.nombre, as_attachment=False)
    except FileNotFoundError:
        raise Http404('El archivo del acta no se encuentra.')


@requiere_operacion
@require_POST
def actas_accion(request):
    soc, _ = _sociedad(request)
    if request.POST.get('accion') == 'revisar':
        messages.success(request, carpetas.revisar_actas(soc))
    elif request.POST.get('accion') == 'leer':
        try:
            n = ia.leer_actas_pendientes(soc)
            messages.info(request, f'La IA está leyendo {n} actas, una tras otra (unos 30 segundos cada una). La página se actualiza sola.')
        except ia.SinClave as e:
            messages.error(request, str(e))
    return redirect(f'{reverse("actas")}?sociedad={soc.id}')


# ------------------------------------------------------------------ quién cobra gastos comunes y agua (todos los contratos)
@login_required
def quien_cobra(request):
    c = ctx_base(request)
    soc = c['sociedad']
    contratos = Contrato.objects.filter(sociedad=soc, activo=True).select_related('arrendatario').order_by('codigo')
    if request.method == 'POST':
        from .permisos import puede_operar
        if not puede_operar(request.user):
            raise PermissionDenied
        n = 0
        for ct in contratos:
            g, a = request.POST.get(f'g_{ct.pk}'), request.POST.get(f'a_{ct.pk}')
            if g in ('MEGA', 'INM') and a in ('MEGA', 'INM') and (g, a) != (ct.cobra_gastos_comunes, ct.cobra_agua):
                ct.cobra_gastos_comunes, ct.cobra_agua = g, a
                ct.save()   # queda en el historial de cada contrato
                n += 1
        messages.success(request, f'{n} contrato(s) actualizado(s). Regenere los borradores para aplicar el cambio.' if n else 'No hubo cambios.')
        return redirect(f'{reverse("quien_cobra")}?sociedad={soc.id}')
    c.update(contratos=contratos, opciones=Contrato.QuienCobra.choices)
    return render(request, 'panel/quien_cobra.html', c)


# ------------------------------------------------------------------ códigos de artículo (por sociedad, tabla editable)
@login_required
def codigos_articulo(request):
    from facturacion import articulos
    from facturacion.models import CodigoServicioBsoft, LineaDocumento
    c = ctx_base(request)
    soc = c['sociedad']
    actuales = {x.origen: x for x in CodigoServicioBsoft.objects.filter(sociedad=soc)}
    filas = []
    for origen, nombre in LineaDocumento.Origen.choices:
        x = actuales.get(origen)
        cod = x.codigo if x else articulos.POR_ORIGEN.get(origen, '')
        filas.append(dict(origen=origen, nombre=nombre, codigo=cod, descripcion=(x.nota if x and x.nota else articulos.CATALOGO.get(cod, ''))))
    if request.method == 'POST':
        if not puede_forzar(request.user):
            raise PermissionDenied
        n = 0
        for f in filas:
            cod = (request.POST.get(f'c_{f["origen"]}') or '').strip()
            desc = (request.POST.get(f'd_{f["origen"]}') or '').strip()
            if not cod:
                continue
            obj = actuales.get(f['origen'])
            if obj is None or (obj.codigo, obj.nota) != (cod, desc):
                CodigoServicioBsoft.objects.update_or_create(sociedad=soc, origen=f['origen'], defaults={'codigo': cod, 'nota': desc})
                n += 1
        messages.success(request, f'{n} código(s) actualizado(s) para {soc.nombre}. Se usan en el próximo Excel de facturación.' if n else 'No hubo cambios.')
        return redirect(f'{reverse("codigos_articulo")}?sociedad={soc.id}')
    c.update(filas=filas, otros=[(articulos.CATALOGO[cod], cod) for _, cod in articulos.OTROS_POR_CONCEPTO])
    return render(request, 'panel/codigos_articulo.html', c)
