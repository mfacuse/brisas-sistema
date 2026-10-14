from django.contrib import admin

from .models import IntentoIngreso, SegundoFactor


@admin.register(SegundoFactor)
class SegundoFactorAdmin(admin.ModelAdmin):
    """Para reiniciar la verificación de alguien que perdió el celular: borrar su fila (la configura de nuevo al ingresar)."""
    list_display = ('usuario', 'activo', 'creado')
    fields = ('usuario', 'activo', 'creado')
    readonly_fields = ('usuario', 'creado')

    def has_add_permission(self, request):
        return False


@admin.register(IntentoIngreso)
class IntentoIngresoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'usuario', 'ip', 'paso', 'exito')
    list_filter = ('exito', 'paso')
    search_fields = ('usuario', 'ip')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
