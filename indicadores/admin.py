from django.contrib import admin

from .models import IPC, UF


@admin.register(UF)
class UFAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'valor')
    date_hierarchy = 'fecha'


@admin.register(IPC)
class IPCAdmin(admin.ModelAdmin):
    list_display = ('anio', 'mes', 'variacion_pct')
    list_filter = ('anio',)
