"""Mudanza a la nube: carga el archivo exportado por `preparar_nube` en una base vacía (una sola vez).

Solo para superusuarios y solo mientras la base no tenga contratos (nunca pisa datos existentes)."""
import os
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.management import call_command
from django.db import transaction
from django.shortcuts import redirect, render

from maestro.models import Contrato


@user_passes_test(lambda u: u.is_active and u.is_superuser)
def importar_datos(request):
    vacia = not Contrato.objects.exists()
    if request.method == 'POST' and vacia:
        f = request.FILES.get('archivo')
        if not f or not f.name.endswith('.json'):
            messages.error(request, 'Elija el archivo .json de la mudanza.')
            return redirect('importar_datos')
        fd, tmp = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'wb') as fh:
                for parte in f.chunks():
                    fh.write(parte)
            with transaction.atomic():
                call_command('loaddata', tmp, verbosity=0)
        except Exception as e:
            messages.error(request, f'No se pudieron cargar los datos (no se guardó nada): {e}')
            return redirect('importar_datos')
        finally:
            os.unlink(tmp)
        messages.success(request, f'Datos cargados: {Contrato.objects.count()} contratos. Ya puede entrar con su usuario y clave de siempre.')
        return redirect('configuracion')
    return render(request, 'panel/importar_datos.html', {'vacia': vacia, 'n': Contrato.objects.count()})
