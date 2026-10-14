"""Carpetas de contratos por sociedad: elegir la carpeta, revisarla y detectar PDF nuevos, cambiados, movidos o eliminados.

La revisión solo mira nombre, tamaño y fecha de modificación (no abre los PDF), así que es rápida aunque los archivos
estén «solo en la nube» en Google Drive. El contenido lo lee la IA solo cuando se pide (ver `ia.py`).
"""
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from django.db import transaction

from .models import ArchivoContrato, Contrato, EventoArchivo

EXTENSIONES = {'.pdf'}


from .almacen import CarpetaNoPermitida  # noqa: E402  (se reexporta: otras partes la importan desde aquí)
from . import almacen  # noqa: E402


# ------------------------------------------------------------------ carpetas permitidas (Mac o Google Drive: ver almacen.py)
def validar(ruta: str) -> str:
    """Carpeta normalizada (ruta del Mac dentro de Drive/OneDrive, o gdrive:<id>). Si no se puede usar, CarpetaNoPermitida."""
    return almacen.validar_carpeta(ruta)


# ------------------------------------------------------------------ asociar archivo ↔ contrato por nombre
def _fuentes(texto: str):
    """«Contrato Local 16 X.pdf; …X Anexo.pdf; …Y.pdf y (Cesión) 2.pdf (duplicados)» →
    (['contrato local 16 x.pdf'], ['x anexo.pdf', 'y.pdf', '(cesión) 2.pdf'])  (nombres completos, terminaciones)."""
    completos, sufijos = [], []
    for parte in (texto or '').split(';'):
        for i, pieza in enumerate(re.findall(r'.*?\.pdf', _norm(parte))):
            pieza = pieza.strip()
            if i == 0 and not pieza.startswith(('…', '...')):
                completos.append(pieza)
            else:
                sufijos.append(re.sub(r'^(y\s+|…|\.\.\.)+', '', pieza).strip())
    return completos, [x for x in sufijos if x]


def mapa_fuentes(sociedad):
    return [(c, *_fuentes(c.documentos_fuente)) for c in Contrato.objects.filter(sociedad=sociedad).exclude(documentos_fuente='')]


def _norm(t: str) -> str:
    """Minúsculas y tildes en forma única (macOS puede guardar «ó» como o + tilde)."""
    return unicodedata.normalize('NFC', t or '').strip().lower()


def contrato_por_nombre(nombre: str, mapa):
    n = _norm(nombre)
    for c, completos, _ in mapa:
        if n in completos:
            return c
    for c, _, sufijos in mapa:
        if any(n.endswith(s) for s in sufijos):
            return c
    return None


# ------------------------------------------------------------------ revisión
@dataclass
class Resumen:
    sociedad: str
    carpeta: str = ''
    total: int = 0
    nuevos: list = field(default_factory=list)
    cambiados: list = field(default_factory=list)
    eliminados: list = field(default_factory=list)
    movidos: list = field(default_factory=list)
    error: str = ''

    def __str__(self):
        if self.error:
            return f'{self.sociedad}: {self.error}'
        if not self.carpeta:
            return f'{self.sociedad}: sin carpeta de contratos configurada'
        partes = [f'{self.total} PDF']
        for n, l in (('nuevos', self.nuevos), ('cambiados', self.cambiados), ('movidos o renombrados', self.movidos), ('ya no están', self.eliminados)):
            if l:
                partes.append(f'{len(l)} {n}')
        return f'{self.sociedad}: ' + ', '.join(partes)


def _encontrados(carpeta: str):
    return {e.ruta: e for e in almacen.listar(carpeta, EXTENSIONES)}


@transaction.atomic
def revisar(sociedad, usuario: str = '') -> Resumen:
    res = Resumen(sociedad.nombre, sociedad.carpeta_contratos)
    if not sociedad.carpeta_contratos:
        return res
    if not almacen.existe_carpeta(sociedad.carpeta_contratos):
        # Drive desconectado o carpeta movida: no se marca nada como eliminado
        res.error = f'no se encuentra la carpeta «{sociedad.carpeta_contratos}» (¿Google Drive está abierto?)'
        return res
    ahora = datetime.now(timezone.utc)
    previos = {a.ruta: a for a in ArchivoContrato.objects.filter(sociedad=sociedad)}
    primera_vez = not previos
    try:
        encontrados = _encontrados(sociedad.carpeta_contratos)
    except Exception as e:   # sin internet o Drive sin permiso: no se marca nada como eliminado
        res.error = f'no se pudo leer la carpeta ({e})'
        return res
    res.total = len(encontrados)
    mapa = mapa_fuentes(sociedad)
    desaparecidos = {r: a for r, a in previos.items() if r not in encontrados and a.estado != 'E'}

    def evento(a, tipo, detalle=''):
        EventoArchivo.objects.create(archivo=a, tipo=tipo, detalle=detalle[:300], usuario=usuario)

    for ruta, ent in encontrados.items():
        nombre, tamano, mod = ent.nombre, ent.tamano, ent.modificado
        a = previos.get(ruta)
        if a:
            if a.estado == 'E':
                a.estado = 'C'
                evento(a, 'REAPARECIDO', 'volvió a estar en la carpeta')
                res.cambiados.append(a)
            elif a.tamano != tamano or a.modificado != mod:
                detalle = f'tamaño {a.tamano:,} → {tamano:,} bytes · modificado {mod:%d-%m-%Y %H:%M} (UTC)'.replace(',', '.')
                a.estado = 'C'
                evento(a, 'CAMBIADO', detalle)
                res.cambiados.append(a)
            a.tamano, a.modificado, a.visto_ultima = tamano, mod, ahora
            a.save()
            continue
        movido = next((x for x in desaparecidos.values() if (x.nombre == nombre and x.tamano == tamano)
                       or (ent.drive_id and x.drive_id == ent.drive_id)), None)
        if movido:
            del desaparecidos[movido.ruta]
            evento(movido, 'MOVIDO', f'{movido.ruta} → {ruta}')
            movido.ruta, movido.modificado, movido.visto_ultima, movido.tamano = ruta, mod, ahora, tamano
            movido.save()
            res.movidos.append(movido)
            continue
        c = contrato_por_nombre(nombre, mapa)
        a = ArchivoContrato.objects.create(sociedad=sociedad, ruta=ruta, nombre=nombre, tamano=tamano, modificado=mod,
                                           drive_id=almacen.drive_id(ent), contrato=c, visto_ultima=ahora,
                                           estado='R' if (primera_vez and c) else 'N')
        if a.estado == 'R':
            evento(a, 'REGISTRADO', f'ya estaba cargado en el sistema como {c.codigo} (lectura inicial de los contratos)')
        else:
            evento(a, 'NUEVO', f'asociado por nombre a {c.codigo}' if c else 'sin contrato asociado')
            res.nuevos.append(a)
    for a in desaparecidos.values():
        a.estado = 'E'
        a.save()
        evento(a, 'ELIMINADO', 'ya no está en la carpeta configurada')
        res.eliminados.append(a)
    return res


def revisar_todas(usuario: str = ''):
    from .models import Sociedad
    return [revisar(s, usuario) for s in Sociedad.objects.order_by('id')]


# ------------------------------------------------------------------ carpeta de actas de entrega
EXT_ACTAS = {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}


@transaction.atomic
def revisar_actas(sociedad) -> str:
    """Crea un acta «sin leer» por cada archivo nuevo de la carpeta de actas; avisa los cambiados y los que ya no están."""
    from .models import ActaEntrega
    if not sociedad.carpeta_actas:
        return f'{sociedad.nombre}: sin carpeta de actas configurada'
    if not almacen.existe_carpeta(sociedad.carpeta_actas):
        return f'{sociedad.nombre}: no se encuentra la carpeta de actas (¿Google Drive está abierto o compartido?)'
    try:
        entradas = almacen.listar(sociedad.carpeta_actas, EXT_ACTAS)
    except Exception as e:
        return f'{sociedad.nombre}: no se pudo leer la carpeta de actas ({e})'
    previas = {a.ruta: a for a in ActaEntrega.objects.filter(sociedad=sociedad).exclude(ruta='')}
    por_drive = {a.drive_id: a for a in previas.values() if a.drive_id}
    vistos, nuevas, cambiadas = set(), 0, 0
    for ent in entradas:
        ruta, nombre, mod = ent.ruta, ent.nombre, ent.modificado
        vistos.add(ruta)
        a = previas.get(ruta) or (por_drive.get(ent.drive_id) if ent.drive_id else None)
        if a is None:
            ActaEntrega.objects.create(sociedad=sociedad, ruta=ruta, nombre=nombre[:255], tamano=ent.tamano, modificado=mod,
                                       drive_id=almacen.drive_id(ent), subida_por='carpeta')
            nuevas += 1
            continue
        if a.ruta != ruta:   # misma acta, ahora leída desde Drive (o movida): se conserva todo
            a.ruta = ruta
            a.save(update_fields=['ruta'])
        if (ent.tamano and a.tamano != ent.tamano) or a.ya_no_esta:
            a.tamano, a.modificado, a.ya_no_esta = ent.tamano, mod, False
            if a.estado != 'R':
                a.estado = 'S'   # el archivo cambió: hay que volver a leerlo
            a.save()
            cambiadas += 1
    ya_no = ActaEntrega.objects.filter(sociedad=sociedad, ya_no_esta=False).exclude(ruta='').exclude(ruta__in=vistos).update(ya_no_esta=True)
    return f'{sociedad.nombre}: {len(vistos)} actas en la carpeta, {nuevas} nuevas, {cambiadas} cambiadas, {ya_no} ya no están'
