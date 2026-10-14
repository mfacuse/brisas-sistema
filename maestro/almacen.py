"""Capa única de archivos: el sistema lee las carpetas de contratos, actas, planos y facturas desde el Mac (modo oficina)
o desde Google Drive por internet (modo nube, en Render). Todo el resto del sistema usa solo estas funciones.

Rutas:
  - Mac:          ruta completa, p. ej. /Users/…/Mi unidad/Archivos Brisas del Centro/CONTRATOS/Contratos Vigentes
  - Google Drive: «gdrive:<id>» del archivo o carpeta en Drive.
Para Drive se usa una cuenta de servicio de Google (variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON con su clave, o
GOOGLE_SERVICE_ACCOUNT_FILE con la ruta del archivo). Las carpetas se comparten con el correo de esa cuenta de servicio
(solo lectura basta) y aparecen en el selector de carpetas.
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


def drive_configurado() -> bool:
    return bool(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON') or os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE'))


def correo_cuenta_servicio() -> str:
    try:
        return _credenciales_info().get('client_email', '')
    except Exception:
        return ''


def _credenciales_info() -> dict:
    if os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'):
        return json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    return json.loads(Path(os.environ['GOOGLE_SERVICE_ACCOUNT_FILE']).read_text())


def _drive():
    global _servicio
    if _servicio is None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        cred = service_account.Credentials.from_service_account_info(
            _credenciales_info(), scopes=['https://www.googleapis.com/auth/drive.readonly'])
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
    if drive_configurado():
        r = _drive().files().list(q=f"sharedWithMe = true and trashed = false and (mimeType = '{CARPETA}' or mimeType = '{ATAJO}')",
                                  fields=f'files({CAMPOS})', pageSize=200, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        out += sorted(((f'Drive · {f["name"]}', PREFIJO + _resolver(f)['id']) for f in r.get('files', [])), key=lambda x: x[0].lower())
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
            out.insert(0, (f['name'], PREFIJO + f['id']))
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
