from django.contrib import admin, messages
from . import servicios
from .models import (CodigoServicioBsoft, ConsumoServicio, Correlativo, Documento, FacturaEmitida, LineaDocumento,
                     MedidorServicio, VentaMensual)


class LineaInline(admin.TabularInline):
    model = LineaDocumento
    extra = 0
    readonly_fields = ('orden', 'origen', 'concepto', 'detalle', 'unidad', 'cantidad_unidad', 'valor_uf', 'neto')
    can_delete = False


@admin.action(description='Aprobar documentos seleccionados (los que tienen advertencias quedan pendientes)')
def aprobar(modeladmin, request, queryset):
    n = 0
    for d in queryset.filter(estado='B'):
        graves = [x for x in d.advertencias if not str(x).startswith('Nota:')]
        if graves:
            messages.warning(request, f'{d}: advertencias pendientes ({"; ".join(graves)[:150]}).')
            continue
        servicios.marcar_aprobado(d, request.user.get_username())
        n += 1
    messages.info(request, f'{n} documento(s) aprobado(s).')


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('contrato', 'periodo', 'estado', 'tipo_documento', 'numero_interno', 'folio', 'neto', 'iva', 'total', 'valor_uf')
    list_filter = ('estado', 'contrato__sociedad', 'periodo', 'tipo_documento')
    search_fields = ('contrato__codigo', 'contrato__nombre_fantasia', 'numero_interno', 'folio')
    readonly_fields = ('numero_interno',)
    inlines = [LineaInline]
    actions = [aprobar]


@admin.register(MedidorServicio)
class MedidorAdmin(admin.ModelAdmin):
    list_display = ('servicio', 'nombre_planilla', 'etiqueta_local', 'contrato', 'tarifa', 'confirmado', 'nota')
    list_filter = ('servicio', 'confirmado')
    search_fields = ('nombre_planilla', 'etiqueta_local', 'contrato__codigo', 'contrato__nombre_fantasia')
    list_editable = ('confirmado',)


@admin.register(ConsumoServicio)
class ConsumoAdmin(admin.ModelAdmin):
    list_display = ('contrato', 'servicio', 'medidor', 'periodo_consumo', 'periodo_cobro', 'cantidad', 'neto')
    list_filter = ('servicio', 'periodo_cobro')
    search_fields = ('contrato__codigo', 'contrato__nombre_fantasia', 'medidor', 'concepto')


admin.site.register(VentaMensual)


@admin.register(CodigoServicioBsoft)
class CodigoArticuloAdmin(admin.ModelAdmin):
    list_display = ('sociedad', 'origen', 'codigo', 'nota')
    list_editable = ('codigo', 'nota')
    list_filter = ('sociedad',)
    ordering = ('sociedad__nombre', 'origen')


@admin.register(FacturaEmitida)
class FacturaEmitidaAdmin(admin.ModelAdmin):
    list_display = ('folio', 'tipo_dte', 'fecha_emision', 'rut_receptor', 'total', 'estado', 'documento', 'nombre')
    list_filter = ('sociedad', 'estado', 'tipo_dte')
    search_fields = ('folio', 'rut_receptor', 'nombre', 'documento__numero_interno')


@admin.register(Correlativo)
class CorrelativoAdmin(admin.ModelAdmin):
    list_display = ('sociedad', 'serie', 'ultimo')
