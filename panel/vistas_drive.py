"""Conexión del sistema con Google Drive usando la cuenta de Google de un administrador (autorización única, solo lectura).

Flujo OAuth 2.0 estándar de Google para aplicaciones web: el administrador pulsa «Conectar», Google le pide iniciar sesión y
aceptar el permiso de solo lectura, y vuelve al sistema con un código que se cambia por un permiso permanente (refresh token).
"""
import json
import secrets
import urllib.parse
import urllib.request

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from maestro import almacen

from .vistas_archivos import requiere_admin

AUTORIZAR = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN = 'https://oauth2.googleapis.com/token'


def _volver(request):
    return request.build_absolute_uri(reverse('drive_volver'))


def _post(url, datos: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(datos).encode(), method='POST')
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


@requiere_admin
@require_POST
def guardar_cliente(request):
    cid, sec = request.POST.get('client_id', '').strip(), request.POST.get('client_secret', '').strip()
    if not cid.endswith('.apps.googleusercontent.com') or not sec:
        messages.error(request, 'Revise el ID de cliente (termina en .apps.googleusercontent.com) y el secreto.')
    else:
        almacen.guardar_privado(almacen._ruta_cliente(), {'client_id': cid, 'client_secret': sec})
        messages.success(request, 'ID de cliente de Google guardado. Ahora pulse «Conectar Google Drive».')
    return redirect('configuracion')


@requiere_admin
@require_POST
def conectar(request):
    cli = almacen.cliente_oauth()
    if not cli:
        messages.error(request, 'Primero ingrese el ID de cliente de Google.')
        return redirect('configuracion')
    request.session['drive_estado'] = estado = secrets.token_urlsafe(24)
    q = urllib.parse.urlencode({'client_id': cli['client_id'], 'redirect_uri': _volver(request), 'response_type': 'code',
                                'scope': almacen.ALCANCE + ' openid email', 'access_type': 'offline', 'prompt': 'consent',
                                'include_granted_scopes': 'true', 'state': estado})
    return redirect(f'{AUTORIZAR}?{q}')


@requiere_admin
def volver(request):
    estado = request.session.pop('drive_estado', None)
    if not estado or request.GET.get('state') != estado:
        messages.error(request, 'La autorización no coincide (vuelva a pulsar «Conectar Google Drive»).')
        return redirect('configuracion')
    if request.GET.get('error'):
        messages.error(request, f'Google no autorizó la conexión ({request.GET["error"]}).')
        return redirect('configuracion')
    cli = almacen.cliente_oauth()
    try:
        r = _post(TOKEN, {'code': request.GET.get('code', ''), 'client_id': cli['client_id'], 'client_secret': cli['client_secret'],
                          'redirect_uri': _volver(request), 'grant_type': 'authorization_code'})
    except Exception as e:
        messages.error(request, f'No se pudo completar la conexión con Google: {e}')
        return redirect('configuracion')
    if 'refresh_token' not in r:
        messages.error(request, 'Google no entregó un permiso permanente. Vuelva a conectar.')
        return redirect('configuracion')
    correo = ''
    try:
        import base64
        carga = r.get('id_token', '').split('.')[1]
        correo = json.loads(base64.urlsafe_b64decode(carga + '=' * (-len(carga) % 4))).get('email', '')
    except Exception:
        pass
    almacen.olvidar_conexion()
    almacen.guardar_privado(almacen._ruta_token(), {'refresh_token': r['refresh_token'], 'correo': correo, 'conectado_por': request.user.get_username()})
    messages.success(request, f'Google Drive conectado{f" con {correo}" if correo else ""} (solo lectura). Ya puede elegir las carpetas de Drive.')
    return redirect('configuracion')


@requiere_admin
@require_POST
def desconectar(request):
    tok = almacen.token_oauth()
    if tok.get('refresh_token'):
        try:
            _post('https://oauth2.googleapis.com/revoke', {'token': tok['refresh_token']})
        except Exception:
            pass
    almacen.olvidar_conexion()
    messages.success(request, 'Google Drive desconectado: el sistema ya no puede leer sus carpetas de Drive.')
    return redirect('configuracion')
