from django.contrib import admin

from . import models as m


class ContratoLocalInline(admin.TabularInline):
    model = m.ContratoLocal
    extra = 0


class TramoInline(admin.TabularInline):
    model = m.TramoRenta
    extra = 0
    fields = ('desde', 'hasta', 'monto', 'unidad', 'tipo', 'inferido', 'nota')


class DescuentoInline(admin.TabularInline):
    model = m.Descuento
    extra = 0


class SaldoInline(admin.TabularInline):
    model = m.SaldoInformado
    extra = 0


class GarantiaInline(admin.TabularInline):
    model = m.Garantia
    extra = 0


@admin.register(m.Contrato)
class ContratoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre_fantasia', 'arrendatario', 'sociedad', 'tipo_renta', 'periodicidad',
                    'tipo_documento', 'inicio_vigencia', 'fin_pactado', 'activo')
    list_filter = ('sociedad', 'propiedad', 'tipo_renta', 'tipo_documento', 'periodicidad', 'activo')
    search_fields = ('codigo', 'nombre_fantasia', 'arrendatario__razon_social', 'arrendatario__rut')
    inlines = [ContratoLocalInline, TramoInline, DescuentoInline, SaldoInline, GarantiaInline]


@admin.register(m.Local)
class LocalAdmin(admin.ModelAdmin):
    list_display = ('propiedad', 'codigo_plano', 'tipo', 'numero_municipal', 'm2_oficial', 'disponible')
    list_filter = ('propiedad', 'tipo', 'disponible')
    search_fields = ('codigo_plano', 'numero_municipal', 'designacion')


@admin.register(m.Arrendatario)
class ArrendatarioAdmin(admin.ModelAdmin):
    list_display = ('razon_social', 'rut', 'email', 'telefono')
    search_fields = ('razon_social', 'rut')


admin.site.register([m.Sociedad, m.Propiedad, m.ContratoServicio])


@admin.register(m.CondicionPago)
class CondicionPagoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'orden', 'activa')
    list_editable = ('orden', 'activa')


@admin.register(m.ArchivoContrato)
class ArchivoContratoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'sociedad', 'contrato', 'estado', 'ignorar', 'modificado', 'visto_ultima')
    list_filter = ('sociedad', 'estado', 'ignorar')
    search_fields = ('nombre', 'ruta', 'contrato__codigo')


@admin.register(m.PropuestaIA)
class PropuestaIAAdmin(admin.ModelAdmin):
    list_display = ('archivo', 'contrato', 'estado', 'costo_usd', 'creada', 'pedida_por', 'resuelta_por')
    list_filter = ('estado',)


@admin.register(m.RegistroCambio)
class RegistroCambioAdmin(admin.ModelAdmin):
    """Solo lectura: el historial no se edita."""
    list_display = ('fecha', 'usuario', 'origen', 'objeto', 'accion', 'contrato', 'descripcion')
    list_filter = ('origen', 'objeto', 'accion')
    search_fields = ('contrato__codigo', 'descripcion', 'usuario')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
