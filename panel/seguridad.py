"""Ingreso seguro: bloqueo tras intentos fallidos y verificación en dos pasos (código de 6 dígitos de una app del celular).

Estado 2026-10-14: verificación APAGADA en la nube por decisión de Matías mientras dure el desarrollo (DJANGO_2FA=0 en render.yaml);
se reactiva poniendo DJANGO_2FA=1. Las configuraciones existentes se conservan.

En la nube (DJANGO_2FA=1) todo usuario debe configurar la verificación la primera vez que entra. En el Mac (modo oficina) es opcional."""
from datetime import timedelta

import pyotp
import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import IntentoIngreso, SegundoFactor

MAX_FALLAS = 5
VENTANA = timedelta(minutes=15)
EMISOR = 'Sistema Facturación'
LIBRES = ('/login/', '/salir/', '/cuenta/', '/static/', '/sw.js', '/manifest.webmanifest', '/offline/')


def _ip(request):
    return (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''))[:45]


def bloqueado(usuario: str) -> bool:
    desde = timezone.now() - VENTANA
    return IntentoIngreso.objects.filter(usuario__iexact=usuario, exito=False, fecha__gte=desde).count() >= MAX_FALLAS


def _siguiente(request, valor):
    return valor if valor and url_has_allowed_host_and_scheme(valor, {request.get_host()}, request.is_secure()) else settings.LOGIN_REDIRECT_URL


def ingresar(request):
    form = AuthenticationForm(request, data=request.POST or None)
    nxt = request.POST.get('next') or request.GET.get('next', '')
    error = ''
    if request.method == 'POST':
        usuario = (request.POST.get('username') or '').strip()
        if bloqueado(usuario):
            error = 'Demasiados intentos fallidos. Espere 15 minutos e intente de nuevo.'
        elif form.is_valid():
            u = form.get_user()
            IntentoIngreso.objects.create(usuario=usuario, ip=_ip(request), exito=True)
            # con la verificación apagada (DJANGO_2FA≠1) se entra solo con la clave, aunque la persona la tenga configurada
            sf = SegundoFactor.objects.filter(usuario=u, activo=True).first() if settings.EXIGIR_2FA else None
            if sf:
                request.session['2fa_usuario'], request.session['2fa_next'] = u.pk, nxt
                return redirect('ingresar_codigo')
            login(request, u)
            return redirect(_siguiente(request, nxt))
        else:
            IntentoIngreso.objects.create(usuario=usuario, ip=_ip(request), exito=False)
            error = 'Usuario o clave incorrectos.' if not bloqueado(usuario) else 'Demasiados intentos fallidos. Espere 15 minutos.'
    return render(request, 'panel/login.html', {'form': form, 'next': nxt, 'error': error})


def verificar(sf: SegundoFactor, codigo: str) -> bool:
    """Código válido (con 30 s de tolerancia) y no usado antes."""
    totp = pyotp.TOTP(sf.secreto)
    codigo = (codigo or '').replace(' ', '')
    for desfase in (0, -1, 1):
        paso = totp.timecode(timezone.now()) + desfase
        if paso > sf.ultimo_paso and pyotp.utils.strings_equal(totp.generate_otp(paso), codigo):
            sf.ultimo_paso = paso
            sf.save(update_fields=['ultimo_paso'])
            return True
    return False


def ingresar_codigo(request):
    pk = request.session.get('2fa_usuario')
    if not pk:
        return redirect('login')
    u = get_user_model().objects.get(pk=pk)
    error = ''
    if request.method == 'POST':
        sf = SegundoFactor.objects.filter(usuario=u, activo=True).first()
        if bloqueado(u.get_username()):
            error = 'Demasiados intentos fallidos. Espere 15 minutos.'
        elif sf and verificar(sf, request.POST.get('codigo')):
            IntentoIngreso.objects.create(usuario=u.get_username(), ip=_ip(request), exito=True, paso='codigo')
            nxt = request.session.pop('2fa_next', '')
            request.session.pop('2fa_usuario', None)
            login(request, u, backend='django.contrib.auth.backends.ModelBackend')
            return redirect(_siguiente(request, nxt))
        else:
            IntentoIngreso.objects.create(usuario=u.get_username(), ip=_ip(request), exito=False, paso='codigo')
            error = 'Código incorrecto o vencido. Use el código que muestra ahora la app.'
    return render(request, 'panel/login_codigo.html', {'error': error, 'usuario': u})


@login_required
def configurar(request):
    """Muestra el código QR para la app del celular y activa la verificación al confirmar un código."""
    sf, _ = SegundoFactor.objects.get_or_create(usuario=request.user, defaults={'secreto': pyotp.random_base32()})
    if sf.activo and request.GET.get('nuevo') != '1' and request.method != 'POST':
        return render(request, 'panel/segundo_factor.html', {'activo': True, 'exigido': settings.EXIGIR_2FA})
    if request.GET.get('nuevo') == '1' and request.method != 'POST':
        sf.secreto, sf.activo, sf.ultimo_paso = pyotp.random_base32(), False, 0
        sf.save()
    if request.method == 'POST':
        if verificar(sf, request.POST.get('codigo')):
            sf.activo = True
            sf.save()
            messages.success(request, 'Verificación en dos pasos activada. Desde ahora, al ingresar se le pedirá el código de la app.')
            return redirect('inicio')
        messages.error(request, 'El código no coincide. Revise que el reloj del celular esté en hora y use el código actual.')
    uri = pyotp.TOTP(sf.secreto).provisioning_uri(name=request.user.get_username(), issuer_name=EMISOR)
    qr = segno.make(uri, error='m').svg_inline(scale=5, dark='#1d2733', light='#ffffff')
    return render(request, 'panel/segundo_factor.html', {'qr': qr, 'secreto': sf.secreto, 'exigido': settings.EXIGIR_2FA, 'activo': False})


class MiddlewareSegundoFactor:
    """Si la verificación es obligatoria, quien no la ha configurado solo puede ir a la pantalla para configurarla."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.EXIGIR_2FA and getattr(request, 'user', None) and request.user.is_authenticated
                and not request.path.startswith(LIBRES)
                and not SegundoFactor.objects.filter(usuario=request.user, activo=True).exists()):
            return redirect('configurar_2fa')
        return self.get_response(request)
