"""Capa única de archivos: el sistema lee las carpetas de contratos, actas, planos y facturas desde el Mac (modo oficina)
o desde Google Drive por internet (modo nube, en Render). Todo el resto del sistema usa solo estas funciones.

Rutas:
  - Mac:          ruta completa, p. ej. /Users/…/Mi unidad/Archivos Brisas del Centro/CONTRATOS/Contratos Vigentes
  - Google Drive: «gdrive:<id>» del archivo o carpeta en Drive.
Para Drive hay dos formas de conectarse (se usa la primera disponible):
  1. Cuenta de Google del administrador, autorizada una vez con «Conectar Google Drive» (permiso de solo lectura).
     El permiso queda en el archivo privado .google_drive_token.json (carpeta de secretos) y el ID de cliente de Google en
     .google_oauth_cliente.json (o variables GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET). Ver `panel/vistas_drive.py`.
  2. Cuenta de servicio (GOOGLE_SERVICE_ACCOUNT_JSON o GOOGLE_SERVICE_ACCOUNT_FILE), con las carpetas compartidas con su correo.
"""
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

PREFIJO = 'gdrive:'
CARPETA = 'application/vnd.google-apps.folder'
ATAJO = 'application/vnd.google-apps.shortcut'


class CarpetaNoPermitida(Exception):
    pass


@dataclass
class Entrada:
    ruta: str          # ruta local o gdrive:<id>
    nombre: str
    tamano: int
    modificado: datetime
    drive_id: str = ''


def es_drive(ruta: str) -> bool:
    return (ruta or '').startswith(PREFIJO)


def _id(ruta: str) -> str:
    return ruta[len(PREFIJO):]


# ------------------------------------------------------------------ Mac (carpetas locales)
def raices_locales():
    return [Path(r).resolve() for r in settings.CARPETAS_RAIZ if Path(r).exists()]


def _validar_local(ruta: str) -> Path:
    p = Path(ruta).expanduser().resolve()
    if not any(p == r or r in p.parents for r in raices_locales()):
        raise CarpetaNoPermitida(f'«{ruta}» está fuera de las carpetas permitidas.')
    return p


def _drive_id_local(ruta: str) -> str:
    import subprocess
    try:
        r = subprocess.run(['xattr', '-p', 'com.google.drivefs.item-id#S', ruta], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


# ------------------------------------------------------------------ Google Drive
_servicio = None


ALCANCE = 'https://www.googleapis.com/auth/drive.readonly'          # leer las carpetas
ALCANCE_RESPALDOS = 'https://www.googleapis.com/auth/drive.file'     # crear/borrar SOLO los archivos que el sistema crea (respaldos)
ALCANCES = [ALCANCE, ALCANCE_RESPALDOS]


# ------------------------------------------------------------------ datos privados (en la base: los ven la web y la tarea diaria)
def leer_dato(clave: str, archivo_antiguo: Path = None):
    """Valor guardado en DatoSistema; si aún está en un archivo de la versión anterior, se traslada a la base."""
    from .models import DatoSistema
    d = DatoSistema.objects.filter(clave=clave).first()
    if d:
        return d.valor
    if archivo_antiguo is not None and archivo_antiguo.exists():
        try:
            valor = json.loads(archivo_antiguo.read_text())
        except ValueError:
            valor = archivo_antiguo.read_text().strip()
        guardar_dato(clave, valor)
        return valor
    return None


def guardar_dato(clave: str, valor):
    from .models import DatoSistema
    DatoSistema.objects.update_or_create(clave=clave, defaults={'valor': valor})


def borrar_dato(clave: str, archivo_antiguo: Path = None):
    from .models import DatoSistema
    DatoSistema.objects.filter(clave=clave).delete()
    if archivo_antiguo is not None:
        archivo_antiguo.unlink(missing_ok=True)


def _secretos() -> Path:
    return Path(getattr(settings, 'SECRETOS_DIR', settings.BASE_DIR))


def _ruta_token() -> Path:
    return _secretos() / '.google_drive_token.json'


def _ruta_cliente() -> Path:
    return _secretos() / '.google_oauth_cliente.json'


def guardar_privado(ruta: Path, datos: dict):
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(datos, fh)
    os.chmod(ruta, 0o600)


def cliente_oauth() -> dict:
    """{'client_id', 'client_secret'} de la app de Google (variables de entorno o archivo privado), o {}."""
    if os.environ.get('GOOGLE_OAUTH_CLIENT_ID') and os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'):
        return {'client_id': os.environ['GOOGLE_OAUTH_CLIENT_ID'], 'client_secret': os.environ['GOOGLE_OAUTH_CLIENT_SECRET']}
    return leer_dato('google_oauth_cliente', _ruta_cliente()) or {}


def token_oauth() -> dict:
    return leer_dato('google_drive_token', _ruta_token()) or {}


def guardar_cliente(datos: dict):
    guardar_dato('google_oauth_cliente', datos)


def guardar_token(datos: dict):
    global _servicio
    guardar_dato('google_drive_token', datos)
    _servicio = None


def puede_respaldar() -> bool:
    """La conexión con Google incluye el permiso para crear los archivos de respaldo."""
    return ALCANCE_RESPALDOS in (token_oauth().get('alcances') or '')


def _cuenta_servicio() -> bool:
    return bool(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON') or os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE'))


def drive_configurado() -> bool:
    return bool(token_oauth().get('refresh_token') and cliente_oauth()) or _cuenta_servicio()


def olvidar_conexion():
    global _servicio
    borrar_dato('google_drive_token', _ruta_token())
    _servicio = None


def correo_cuenta_servicio() -> str:
    """Correo con el que el sistema entra a Drive (la cuenta autorizada o la cuenta de servicio)."""
    if token_oauth().get('correo'):
        return token_oauth()['correo']
    try:
        return _credenciales_info().get('client_email', '') if _cuenta_servicio() else ''
    except Exception:
        return ''


def _credenciales_info() -> dict:
    if os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'):
        return json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    return json.loads(Path(os.environ['GOOGLE_SERVICE_ACCOUNT_FILE']).read_text())


def _drive():
    global _servicio
    if _servicio is None:
        from googleapiclient.discovery import build
        tok, cli = token_oauth(), cliente_oauth()
        if tok.get('refresh_token') and cli:
            from google.oauth2.credentials import Credentials
            cred = Credentials(None, refresh_token=tok['refresh_token'], token_uri='https://oauth2.googleapis.com/token',
                               client_id=cli['client_id'], client_secret=cli['client_secret'],
                               scopes=(tok.get('alcances') or ALCANCE).split())
        else:
            from google.oauth2 import service_account
            cred = service_account.Credentials.from_service_account_info(_credenciales_info(), scopes=[ALCANCE])
        _servicio = build('drive', 'v3', credentials=cred, cache_discovery=False)
    return _servicio


CAMPOS = 'id, name, mimeType, size, modifiedTime, shortcutDetails(targetId, targetMimeType)'


def _hijos(carpeta_id: str):
    out, token = [], None
    while True:
        r = _drive().files().list(q=f"'{carpeta_id}' in parents and trashed = false", fields=f'nextPageToken, files({CAMPOS})',
                                  pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += r.get('files', [])
        token = r.get('nextPageToken')
        if not token:
            return out


def _resolver(f: dict) -> dict:
    """Sigue los atajos de Drive hasta el archivo o carpeta real."""
    if f['mimeType'] == ATAJO:
        det = f.get('shortcutDetails', {})
        real = _drive().files().get(fileId=det.get('targetId'), fields=CAMPOS, supportsAllDrives=True).execute()
        return real
    return f


def _fecha(txt: str) -> datetime:
    return datetime.fromisoformat(txt.replace('Z', '+00:00')).replace(microsecond=0)


# ------------------------------------------------------------------ funciones comunes
def validar_carpeta(ruta: str) -> str:
    """Normaliza la carpeta elegida; lanza CarpetaNoPermitida si no se puede usar."""
    if es_drive(ruta):
        if not drive_configurado():
            raise CarpetaNoPermitida('Google Drive no está configurado en este servidor.')
        try:
            f = _resolver(_drive().files().get(fileId=_id(ruta), fields=CAMPOS, supportsAllDrives=True).execute())
        except Exception:
            raise CarpetaNoPermitida('No se puede abrir esa carpeta de Google Drive (¿está compartida con la cuenta del sistema?).')
        if f['mimeType'] != CARPETA:
            raise CarpetaNoPermitida('Eso no es una carpeta.')
        return PREFIJO + f['id']
    return str(_validar_local(ruta))


def existe_carpeta(ruta: str) -> bool:
    try:
        if es_drive(ruta):
            validar_carpeta(ruta)
            return True
        return _validar_local(ruta).is_dir()
    except CarpetaNoPermitida:
        return False


def listar(carpeta: str, extensiones=None, recursivo=True):
    """Archivos de la carpeta (y subcarpetas), opcionalmente filtrados por extensión (con punto, en minúsculas)."""
    ok = lambda nombre: not nombre.startswith(('.', '~$')) and (extensiones is None or Path(nombre).suffix.lower() in extensiones)
    out = []
    if es_drive(carpeta):
        pendientes, vistos = [_id(carpeta)], set()
        while pendientes:
            cid = pendientes.pop()
            if cid in vistos:
                continue
            vistos.add(cid)
            for f in _hijos(cid):
                f = _resolver(f)
                if f['mimeType'] == CARPETA:
                    if recursivo:
                        pendientes.append(f['id'])
                elif ok(f['name']):
                    out.append(Entrada(PREFIJO + f['id'], f['name'], int(f.get('size') or 0), _fecha(f['modifiedTime']), f['id']))
        return out
    base = _validar_local(carpeta)
    for raiz, dirs, archivos in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')] if recursivo else []
        for nombre in archivos:
            if not ok(nombre):
                continue
            ruta = os.path.join(raiz, nombre)
            try:
                st = os.stat(ruta)
            except OSError:
                continue
            out.append(Entrada(ruta, nombre, st.st_size, datetime.fromtimestamp(int(st.st_mtime), tz=timezone.utc)))
    return out


def drive_id(entrada: Entrada) -> str:
    return entrada.drive_id or (_drive_id_local(entrada.ruta) if not es_drive(entrada.ruta) else '')


def leer(ruta: str) -> bytes:
    if es_drive(ruta):
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        pedido = _drive().files().get_media(fileId=_id(ruta), supportsAllDrives=True)
        bajada = MediaIoBaseDownload(buf, pedido, chunksize=8 * 1024 * 1024)
        listo = False
        while not listo:
            _, listo = bajada.next_chunk()
        return buf.getvalue()
    return _validar_local(ruta).read_bytes()


def archivo_local(ruta: str):
    """Ruta local para herramientas que necesitan un archivo en disco (planos .dxf). Devuelve (ruta, temporal?)."""
    if not es_drive(ruta):
        return str(_validar_local(ruta)), False
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix='.dxf')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(leer(ruta))
    return tmp, True


def nombre(ruta: str) -> str:
    if es_drive(ruta):
        return _drive().files().get(fileId=_id(ruta), fields='name', supportsAllDrives=True).execute()['name']
    return Path(ruta).name


# ------------------------------------------------------------------ selector de carpetas
def raices():
    """[(nombre, ruta)] para empezar a navegar: carpetas del Mac y carpetas de Drive compartidas con el sistema."""
    out = [(r.name, str(r)) for r in raices_locales()]
    if drive_configurado() and token_oauth().get('refresh_token'):
        out.append(('Drive · Mi unidad', PREFIJO + _drive().files().get(fileId='root', fields='id').execute()['id']))
    if drive_configurado():
        r = _drive().files().list(q=f"sharedWithMe = true and trashed = false and (mimeType = '{CARPETA}' or mimeType = '{ATAJO}')",
                                  fields=f'files({CAMPOS})', pageSize=200, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        compartidas = sorted(((f'Drive · Compartido conmigo · {f["name"]}', PREFIJO + _resolver(f)['id']) for f in r.get('files', [])),
                             key=lambda x: x[0].lower())
        out += compartidas
    return out


def subcarpetas(ruta: str):
    if es_drive(ruta):
        return sorted(((f['name'], PREFIJO + f['id']) for f in map(_resolver, _hijos(_id(ruta))) if f['mimeType'] == CARPETA),
                      key=lambda x: x[0].lower())
    try:
        p = _validar_local(ruta)
        return sorted(((d.name, str(d)) for d in p.iterdir() if d.is_dir() and not d.name.startswith('.')), key=lambda x: x[0].lower())
    except (OSError, CarpetaNoPermitida):
        return []


def migas(ruta: str):
    """[(nombre, ruta)] desde la raíz hasta la carpeta (para el selector)."""
    if es_drive(ruta):
        out, actual, vueltas = [], _id(ruta), 0
        raices_ids = {r for _, r in raices() if es_drive(r)}
        while actual and vueltas < 15:
            f = _drive().files().get(fileId=actual, fields='id, name, parents', supportsAllDrives=True).execute()
            out.insert(0, (f['name'] if f.get('parents') else 'Mi unidad', PREFIJO + f['id']))
            if PREFIJO + f['id'] in raices_ids:
                break
            actual = (f.get('parents') or [None])[0]
            vueltas += 1
        return out
    p = _validar_local(ruta)
    raiz = next(r for r in raices_locales() if p == r or r in p.parents)
    out = []
    while True:
        out.insert(0, (p.name or str(p), str(p)))
        if p == raiz:
            return out
        p = p.parent


# ------------------------------------------------------------------ respaldos: carpeta propia del sistema en Mi unidad
CARPETA_RESPALDOS = 'Respaldos sistema Brisas'


def carpeta_respaldos() -> str:
    """Id de la carpeta de respaldos creada por el sistema (la busca o la crea). Se puede mover dentro de Drive."""
    r = _drive().files().list(q=f"name = '{CARPETA_RESPALDOS}' and mimeType = '{CARPETA}' and trashed = false",
                              fields='files(id)', pageSize=5).execute()
    if r.get('files'):
        return r['files'][0]['id']
    return _drive().files().create(body={'name': CARPETA_RESPALDOS, 'mimeType': CARPETA}, fields='id').execute()['id']


def subir(carpeta_id: str, nombre: str, contenido: bytes, tipo='application/gzip') -> dict:
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=tipo, resumable=False)
    return _drive().files().create(body={'name': nombre, 'parents': [carpeta_id]}, media_body=media, fields='id, name, size').execute()


def archivos_de(carpeta_id: str):
    """Archivos (creados por el sistema) dentro de la carpeta, del más nuevo al más antiguo."""
    r = _drive().files().list(q=f"'{carpeta_id}' in parents and trashed = false", fields='files(id, name, size, createdTime)',
                              orderBy='createdTime desc', pageSize=200).execute()
    return r.get('files', [])


def borrar(archivo_id: str):
    _drive().files().delete(fileId=archivo_id).execute()
