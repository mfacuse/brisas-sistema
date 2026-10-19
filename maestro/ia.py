"""Lectura de contratos con IA (Claude, de Anthropic): lee el PDF y propone los datos para crear o actualizar el contrato.

- Nada se aplica solo: la propuesta queda «lista para revisar» y una persona elige qué campos aplicar (queda en el historial).
- La clave de la API va en el archivo privado `.clave_anthropic` (o en ANTHROPIC_API_KEY). Se ingresa desde el panel.
- Costo aproximado con Claude Opus 5.5: US$ 4 por millón de tokens de entrada y US$ 20 de salida; un contrato de 20–30 páginas
  cuesta del orden de US$ 0,2–0,3. Cada propuesta guarda su costo.
- El texto del contrato se envía a Anthropic para leerlo (decisión del propietario, 2026-10-13).
"""
import base64
import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections, transaction

from . import almacen, historial
from .models import (ActaEntrega, Arrendatario, ArchivoContrato, Contrato, EventoArchivo, PropuestaIA, Propiedad, RegistroCambio,
                     TramoRenta)

ARCHIVO_CLAVE = '.clave_anthropic'
MAX_BYTES = 30 * 1024 * 1024
PRECIOS = {'claude-opus-5-5': (Decimal('4'), Decimal('20')), 'claude-sonnet-5-5': (Decimal('2'), Decimal('10')),
           'claude-fable-5-1': (Decimal('10'), Decimal('50'))}  # US$ por millón de tokens (entrada, salida)
EN_SEGUNDO_PLANO = True   # las pruebas lo apagan


class SinClave(Exception):
    pass


# ------------------------------------------------------------------ clave de la API
def _ruta_clave() -> Path:
    return Path(getattr(settings, 'SECRETOS_DIR', settings.BASE_DIR)) / ARCHIVO_CLAVE


def clave_api():
    k = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not k:
        k = (almacen.leer_dato('clave_anthropic', _ruta_clave()) or '').strip()
    if getattr(settings, 'PRUEBAS', False):
        # en las pruebas automáticas nunca se usa la clave real (ni el archivo ni la variable de entorno), solo claves de prueba
        return k if k.startswith('sk-ant-prueba') else ''
    return k


def clave_configurada() -> str:
    """'' si no hay clave; si hay, solo sus últimos 4 caracteres (nunca se muestra entera)."""
    k = clave_api()
    return f'…{k[-4:]}' if k else ''


def guardar_clave(texto: str):
    texto = texto.strip()
    if not texto:
        almacen.borrar_dato('clave_anthropic', _ruta_clave())
        return
    almacen.guardar_dato('clave_anthropic', texto)
    _ruta_clave().unlink(missing_ok=True)


# ------------------------------------------------------------------ qué se le pide a la IA
TEXTO = {'type': 'string'}
FECHA = {'type': 'string', 'description': 'AAAA-MM-DD, o "" si el documento no lo indica'}
NUMERO = {'type': 'string', 'description': 'número con punto decimal (sin separador de miles), o "" si no lo indica'}


def _enum(*v):
    return {'type': 'string', 'enum': list(v)}


def _obj(props):
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}


ESQUEMA = _obj({
    'tipo_documento_fuente': _enum('contrato', 'anexo', 'modificacion', 'cesion', 'renovacion', 'termino', 'otro'),
    'resumen': {'type': 'string', 'description': '2 a 4 frases en español: qué es el documento y qué establece o cambia'},
    'contrato_existente_codigo': {'type': 'string', 'description': 'código del contrato del sistema al que corresponde (de la lista entregada), o ""'},
    'arrendatario_razon_social': TEXTO, 'arrendatario_rut': {'type': 'string', 'description': 'RUT con puntos y guion, ej. 76.123.456-7'},
    'representante': TEXTO, 'nombre_fantasia': TEXTO, 'locales': {'type': 'string', 'description': 'locales o recintos que arrienda, como los nombra el documento'},
    'direccion_contrato': TEXTO, 'fecha_contrato': FECHA, 'inicio_vigencia': FECHA,
    'fecha_entrega': {'type': 'string', 'description': 'fecha de entrega del local al arrendatario, AAAA-MM-DD, o ""'},
    'fecha_apertura': {'type': 'string', 'description': 'fecha de apertura al público, AAAA-MM-DD, o ""'},
    'regla_inicio_cobro': {'type': 'string', 'enum': ['', 'ENT', 'APE', 'PRI'],
                           'description': 'desde cuándo se cobra la renta: ENT desde la entrega (+ días), APE desde la apertura, '
                                          'PRI apertura o N días desde la entrega lo que ocurra primero, "" si el contrato fija fechas o no lo dice'},
    'dias_inicio_cobro': {'type': 'string', 'description': 'días desde la entrega para ENT o PRI (ej. "60"), o ""'},
    'fecha_inicio_cobro': {'type': 'string', 'description': 'fecha exacta de inicio de cobro de la renta si el documento la indica, AAAA-MM-DD, o ""'},
    'plazo_meses': NUMERO, 'fin_pactado': FECHA, 'prorroga_meses': NUMERO, 'aviso_dias': NUMERO, 'fecha_termino_real': FECHA,
    'tipo_documento': {'type': 'string', 'enum': ['FA', 'FE', 'NC', ''],
                       'description': 'FA factura afecta (IVA), FE factura exenta, NC nota de cobro sin factura (no DTE), "" si no lo dice'},
    'tipo_documento_motivo': {'type': 'string', 'description': 'por qué (cláusula o texto que lo indica)'},
    'regla_uf': {'type': 'string', 'enum': ['D1', 'PH', ''], 'description': 'D1 UF del día 1 del mes; PH UF del primer día hábil'},
    'tipo_renta': {'type': 'string', 'enum': ['FIJA', 'MINVAR', ''], 'description': 'MINVAR = mínimo o % de ventas/ingresos'},
    'pct_variable': {'type': 'string', 'description': 'fracción: 2 % → "0.02"; "" si no hay renta variable'},
    'base_variable': {'type': 'string', 'enum': ['V', 'I', ''], 'description': 'V ventas netas, I ingresos netos'},
    'periodicidad': {'type': 'string', 'enum': ['M', 'S', ''], 'description': 'M mensual, S semestral'},
    'meses_cobro': {'type': 'string', 'description': 'solo si es semestral, ej. "1,6"'},
    'reajuste_ipc': {'type': 'string', 'enum': ['si', 'no', ''], 'description': 'renta en pesos reajustable por IPC'},
    'm2_contrato': NUMERO, 'garantia_uf': NUMERO, 'garantia_clp': NUMERO,
    'gastos_comunes': TEXTO, 'condiciones': {'type': 'string', 'description': 'condiciones especiales relevantes para el cobro (gracia, descuentos, multas, etc.)'},
    'tramos': {'type': 'array', 'description': 'calendario COMPLETO de renta vigente después de este documento',
               'items': _obj({'desde': FECHA, 'hasta': FECHA, 'monto': NUMERO, 'unidad': _enum('UF', 'CLP'),
                              'tipo': {'type': 'string', 'description': 'ej. "fija", "mínimo", "por m²"'}, 'nota': TEXTO})},
    'dudas': {'type': 'array', 'items': TEXTO, 'description': 'puntos ambiguos que una persona debe confirmar'},
    'evidencia': {'type': 'array', 'items': _obj({'campo': TEXTO, 'pagina': TEXTO, 'cita': {'type': 'string', 'description': 'cita breve, máx. 25 palabras'}})},
})

INSTRUCCIONES = """Eres un analista de contratos de arriendo comercial en Chile para Grupo Inverco (centros comerciales en Talca).
Lees un documento (contrato, anexo, modificación, cesión, renovación o término) y extraes los datos que el sistema de facturación necesita.

Reglas:
- Usa solo lo que dice el documento y los datos actuales del sistema que se te entregan. No inventes. Si algo no aparece, deja "".
- Fechas en AAAA-MM-DD. Números sin separador de miles y con punto decimal (53,5 UF → "53.5"; 2 % → "0.02").
- Si el documento es un anexo, modificación o cesión de un contrato existente, en «tramos» entrega el calendario COMPLETO de renta
  que queda vigente (combina los tramos actuales del sistema con lo que cambia este documento) y en los demás campos solo lo que el
  documento establece o cambia (deja "" lo que no toca).
- «tipo_documento»: FA si la renta lleva IVA (factura afecta), FE si es factura exenta, NC si el contrato indica cobro sin factura
  (nota de cobro, p. ej. arriendos habitacionales o sin IVA). Explica el motivo en «tipo_documento_motivo».
- Los gastos comunes los factura Megaservicios Talca SpA; regístralos solo como referencia en «gastos_comunes».
- Anota en «dudas» todo lo ambiguo o contradictorio, y en «evidencia» la página y una cita breve de cada dato importante (renta, plazos, tipo de documento)."""


def _contexto(archivo: ArchivoContrato, contrato):
    lista = [dict(codigo=c.codigo, fantasia=c.nombre_fantasia, arrendatario=c.arrendatario.razon_social, rut=c.arrendatario.rut,
                  locales=', '.join(l.codigo_plano for l in c.locales.all()), activo=c.activo)
             for c in Contrato.objects.filter(sociedad=archivo.sociedad).select_related('arrendatario').prefetch_related('locales')]
    txt = [f'Archivo: «{archivo.nombre}» (sociedad {archivo.sociedad.nombre}).',
           'Contratos de esta sociedad en el sistema:', json.dumps(lista, ensure_ascii=False)]
    if contrato:
        txt += [f'El archivo está asociado al contrato {contrato.codigo}. Datos actuales del sistema:',
                json.dumps(datos_actuales(contrato), ensure_ascii=False, default=str)]
    txt.append('Extrae los datos del documento adjunto según el esquema.')
    return '\n'.join(txt)


# ------------------------------------------------------------------ campos comparables
# (clave, etiqueta, tipo): tipo = str | date | int | dec | choice | bool
CAMPOS = [
    ('nombre_fantasia', 'Nombre de fantasía', 'str'), ('representante', 'Representante', 'str'),
    ('direccion_contrato', 'Dirección (para la factura)', 'str'), ('fecha_contrato', 'Fecha del contrato', 'date'),
    ('inicio_vigencia', 'Inicio de vigencia', 'date'), ('fecha_entrega', 'Fecha de entrega del local', 'date'),
    ('fecha_apertura', 'Fecha de apertura', 'date'), ('regla_inicio_cobro', 'Desde cuándo se cobra la renta', 'choice'),
    ('dias_inicio_cobro', 'Días desde la entrega', 'int'), ('fecha_inicio_cobro', 'Inicio de cobro de la renta', 'date'),
    ('plazo_meses', 'Plazo (meses)', 'int'), ('fin_pactado', 'Fin pactado', 'date'),
    ('prorroga_meses', 'Prórroga (meses)', 'int'), ('aviso_dias', 'Aviso de no renovación (días)', 'int'),
    ('fecha_termino_real', 'Término anticipado / efectivo', 'date'), ('tipo_documento', 'Tipo de documento', 'choice'),
    ('regla_uf', 'Regla de la UF', 'choice'), ('tipo_renta', 'Tipo de renta', 'choice'), ('periodicidad', 'Periodicidad', 'choice'),
    ('meses_cobro', 'Meses de cobro (semestral)', 'str'), ('reajuste_ipc', 'Reajuste por IPC', 'bool'),
    ('pct_variable', '% variable', 'dec'), ('base_variable', 'Base de la renta variable', 'choice'),
    ('m2_contrato', 'm² del contrato', 'dec'), ('garantia_uf', 'Garantía (UF)', 'dec'), ('garantia_clp', 'Garantía ($)', 'dec'),
    ('gastos_comunes', 'Gastos comunes (referencia)', 'str'), ('condiciones', 'Condiciones especiales', 'str'),
]


def datos_actuales(c: Contrato) -> dict:
    d = {k: getattr(c, k) for k, _, _ in CAMPOS}
    d['arrendatario'] = f'{c.arrendatario.razon_social} ({c.arrendatario.rut})'
    d['tramos'] = [dict(desde=t.desde, hasta=t.hasta, monto=t.monto, unidad=t.unidad, tipo=t.tipo) for t in c.tramos.all()]
    return d


def _convertir(valor: str, tipo: str):
    v = (valor or '').strip()
    if v == '':
        return None
    if tipo == 'date':
        return date.fromisoformat(v)
    if tipo == 'int':
        return int(Decimal(v))
    if tipo == 'dec':
        return Decimal(v)
    if tipo == 'bool':
        return v == 'si'
    return v


def _mostrar(v, tipo, campo=None):
    if v is None or v == '':
        return '—'
    if tipo == 'date':
        return v.strftime('%d-%m-%Y')
    if tipo == 'bool':
        return 'sí' if v else 'no'
    if tipo == 'choice' and campo is not None:
        return dict(campo.choices).get(v, v)
    if isinstance(v, Decimal):
        return format(v.normalize(), 'f')
    return str(v)


def _fmt_tramos(tramos):
    out = []
    for t in tramos:
        hasta = t['hasta'].strftime('%d-%m-%Y') if t.get('hasta') else 'sin término'
        monto = format(Decimal(t['monto']).normalize(), 'f') if t.get('monto') not in (None, '') else '—'
        out.append(f"{t['desde'].strftime('%d-%m-%Y')} → {hasta}: {monto} {t['unidad']}")
    return out


def tramos_propuestos(datos: dict):
    out = []
    for t in datos.get('tramos') or []:
        try:
            out.append(dict(desde=date.fromisoformat(t['desde']), hasta=date.fromisoformat(t['hasta']) if t.get('hasta') else None,
                            monto=Decimal(t['monto']) if t.get('monto') else None, unidad=t.get('unidad') or 'UF',
                            tipo=t.get('tipo', ''), nota=t.get('nota', '')))
        except (ValueError, KeyError, InvalidOperation):
            continue
    return out


def diferencias(prop: PropuestaIA):
    """Filas para la pantalla de revisión: [{clave, etiqueta, actual, propuesto, cambia}] (solo lo que la IA propone)."""
    d, c = prop.datos, prop.contrato
    filas = []
    rut, razon = d.get('arrendatario_rut', ''), d.get('arrendatario_razon_social', '')
    if rut or razon:
        actual = f'{c.arrendatario.razon_social} ({c.arrendatario.rut})' if c else '—'
        nuevo = f'{razon} ({rut})'
        filas.append(dict(clave='arrendatario', etiqueta='Arrendatario', actual=actual, propuesto=nuevo,
                          cambia=not c or (rut and rut != c.arrendatario.rut) or (razon and razon.lower() != c.arrendatario.razon_social.lower())))
    for clave, etiqueta, tipo in CAMPOS:
        try:
            nuevo = _convertir(d.get(clave, ''), tipo)
        except (ValueError, InvalidOperation):
            continue
        if nuevo is None:
            continue
        campo = Contrato._meta.get_field(clave)
        actual = getattr(c, clave) if c else None
        filas.append(dict(clave=clave, etiqueta=etiqueta, actual=_mostrar(actual, tipo, campo), propuesto=_mostrar(nuevo, tipo, campo),
                          cambia=(actual != nuevo)))
    tp = tramos_propuestos(d)
    if tp:
        ta = [dict(desde=t.desde, hasta=t.hasta, monto=t.monto, unidad=t.unidad) for t in c.tramos.all()] if c else []
        a_txt, p_txt = _fmt_tramos(ta), _fmt_tramos(tp)
        filas.append(dict(clave='tramos', etiqueta='Calendario de renta', actual='\n'.join(a_txt) or '—', propuesto='\n'.join(p_txt),
                          cambia=a_txt != p_txt))
    return filas


# ------------------------------------------------------------------ lectura
def leer_pendientes(sociedad, usuario: str = 'sistema', segundo_plano=None) -> int:
    """Pide a la IA leer todos los PDF nuevos o cambiados de la sociedad que no tengan una lectura en curso o por revisar
    (Matías, 2026-10-15: se leen todos, porque a veces son acuerdos de cambio de renta). Sin clave de IA no hace nada."""
    if not clave_api():
        return 0
    n = 0
    for a in ArchivoContrato.objects.filter(sociedad=sociedad, estado__in=('N', 'C'), ignorar=False):
        if a.propuestas.filter(estado__in=('P', 'L')).exists():
            continue
        iniciar(a, usuario, segundo_plano)
        n += 1
    return n


def iniciar(archivo: ArchivoContrato, usuario: str, segundo_plano=None) -> PropuestaIA:
    if not clave_api():
        raise SinClave('Falta la clave de la IA (Anthropic). Ingrésela en Contratos › Carpetas y configuración.')
    prop = PropuestaIA.objects.create(archivo=archivo, contrato=archivo.contrato, pedida_por=usuario, modelo=settings.IA_MODELO)
    if EN_SEGUNDO_PLANO if segundo_plano is None else segundo_plano:
        threading.Thread(target=ejecutar, args=(prop.pk,), daemon=True).start()
    else:
        ejecutar(prop.pk)
    return prop


def _cliente():
    import anthropic
    return anthropic.Anthropic(api_key=clave_api(), max_retries=3, timeout=600)


def _llamar(cliente, modelo, contenido: bytes, media_type: str, texto: str, esquema: dict, instrucciones: str):
    """Una lectura con la IA: devuelve (datos, tokens_entrada, tokens_salida, costo_usd). Lanza excepción si algo falla."""
    if len(contenido) > MAX_BYTES:
        raise ValueError(f'el archivo pesa {len(contenido) / 1e6:.0f} MB; el máximo es {MAX_BYTES // 1e6:.0f} MB')
    b64 = base64.standard_b64encode(contenido).decode('ascii')
    bloque = ({'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': b64}} if media_type == 'application/pdf'
              else {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': b64}})
    with cliente.beta.messages.stream(
        model=modelo, max_tokens=32000, betas=['server-side-fallback-2026-07-01'], fallbacks='default',
        thinking={'type': 'adaptive'}, output_config={'effort': 'high', 'format': {'type': 'json_schema', 'schema': esquema}},
        system=instrucciones, messages=[{'role': 'user', 'content': [bloque, {'type': 'text', 'text': texto}]}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == 'refusal':
        raise RuntimeError('la IA no quiso procesar este documento')
    if resp.stop_reason == 'max_tokens':
        raise RuntimeError('la respuesta de la IA quedó incompleta (documento muy largo)')
    datos = json.loads(next(b.text for b in resp.content if b.type == 'text'))
    tin, tout = resp.usage.input_tokens or 0, resp.usage.output_tokens or 0
    pin, pout = PRECIOS.get(modelo, PRECIOS['claude-opus-5-5'])
    return datos, tin, tout, (Decimal(tin) * pin + Decimal(tout) * pout) / Decimal(1_000_000)


def _llamar_texto(cliente, modelo, texto: str, esquema: dict, instrucciones: str):
    """Lectura con la IA de un texto (sin archivo adjunto). Devuelve (datos, tokens_entrada, tokens_salida, costo_usd)."""
    with cliente.beta.messages.stream(
        model=modelo, max_tokens=32000, betas=['server-side-fallback-2026-07-01'], fallbacks='default',
        thinking={'type': 'adaptive'}, output_config={'effort': 'high', 'format': {'type': 'json_schema', 'schema': esquema}},
        system=instrucciones, messages=[{'role': 'user', 'content': texto}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason in ('refusal', 'max_tokens'):
        raise RuntimeError('la IA no pudo completar la respuesta')
    datos = json.loads(next(b.text for b in resp.content if b.type == 'text'))
    tin, tout = resp.usage.input_tokens or 0, resp.usage.output_tokens or 0
    pin, pout = PRECIOS.get(modelo, PRECIOS['claude-opus-5-5'])
    return datos, tin, tout, (Decimal(tin) * pin + Decimal(tout) * pout) / Decimal(1_000_000)


def ejecutar(prop_id: int, cliente=None):
    """Lee el PDF con la IA y guarda la propuesta. Se ejecuta en segundo plano; los errores quedan en la propuesta."""
    close_old_connections()
    prop = PropuestaIA.objects.select_related('archivo__sociedad', 'contrato__arrendatario').get(pk=prop_id)
    try:
        prop.modelo = prop.modelo or settings.IA_MODELO
        prop.datos, prop.tokens_entrada, prop.tokens_salida, prop.costo_usd = _llamar(
            cliente or _cliente(), prop.modelo, almacen.leer(prop.archivo.ruta), 'application/pdf',
            _contexto(prop.archivo, prop.contrato), ESQUEMA, INSTRUCCIONES)
        cod = prop.datos.get('contrato_existente_codigo') or ''
        if not prop.contrato and cod:
            prop.contrato = Contrato.objects.filter(sociedad=prop.archivo.sociedad, codigo=cod).first()
        prop.estado = PropuestaIA.Estado.LISTA
        EventoArchivo.objects.create(archivo=prop.archivo, tipo='LEIDO_IA', usuario=prop.pedida_por,
                                     detalle=f'propuesta n.º {prop.pk} · US$ {prop.costo_usd:.2f}')
    except Exception as e:  # sin clave válida, sin red, PDF ilegible, etc.: queda registrado en la propuesta
        prop.estado = PropuestaIA.Estado.ERROR
        prop.error = _mensaje_error(e)
    prop.save()
    close_old_connections()
    return prop


def _mensaje_error(e) -> str:
    try:
        import anthropic
        if isinstance(e, anthropic.AuthenticationError):
            return 'La clave de la IA no es válida. Revísela en Contratos › Carpetas y configuración.'
        if isinstance(e, anthropic.PermissionDeniedError):
            return 'La cuenta de Anthropic no tiene permiso o saldo para usar la IA.'
        if isinstance(e, anthropic.RateLimitError):
            return 'Demasiadas lecturas seguidas; intente de nuevo en unos minutos.'
        if isinstance(e, anthropic.APIConnectionError):
            return 'No hay conexión con la IA (¿internet?).'
        if isinstance(e, anthropic.APIStatusError):
            return f'La IA respondió con un error ({e.status_code}): {e.message}'
    except ImportError:
        pass
    return str(e) or e.__class__.__name__


# ------------------------------------------------------------------ aplicar / descartar
@transaction.atomic
def aplicar(prop: PropuestaIA, claves, usuario: str, propiedad_id=None, fechas=None) -> Contrato:
    """Aplica al contrato solo los campos elegidos. Si la propuesta no tiene contrato, crea uno nuevo en la propiedad elegida
    (el código se asigna solo: B-01, B-02…).
    `fechas`: inicio de vigencia, entrega y apertura ingresadas a mano ({campo: 'AAAA-MM-DD'}); mandan sobre lo que propone la IA."""
    if prop.estado != PropuestaIA.Estado.LISTA:
        raise ValueError('Esta propuesta ya no está pendiente.')
    d, claves = prop.datos, set(claves)
    manual = {}
    for k, v in (fechas or {}).items():
        if k in ('inicio_vigencia', 'fecha_entrega', 'fecha_apertura', 'fecha_inicio_cobro') and (v or '').strip():
            try:
                manual[k] = date.fromisoformat(v.strip())
            except ValueError:
                raise ValueError(f'Fecha no válida: {v}')
    with historial.con_origen('IA', usuario):
        c = prop.contrato
        if c is None:
            prop_obj = Propiedad.objects.filter(pk=propiedad_id, sociedad=prop.archivo.sociedad).first()
            if not prop_obj:
                raise ValueError('Elija la propiedad del contrato (si no existe, créela en Administración › Propiedades).')
            inicio = manual.get('inicio_vigencia') or _convertir(d.get('inicio_vigencia', ''), 'date')
            if not inicio:
                raise ValueError('La IA no encontró el inicio de vigencia: ingréselo a mano en «Fechas» (se puede cambiar después).')
            claves |= {'arrendatario'}
            c = Contrato(propiedad=prop_obj, sociedad=prop.archivo.sociedad, inicio_vigencia=inicio,
                         nombre_fantasia=d.get('nombre_fantasia') or d.get('arrendatario_razon_social', '')[:80])
        if 'arrendatario' in claves:
            rut, razon = d.get('arrendatario_rut', '').strip(), d.get('arrendatario_razon_social', '').strip()
            if not (rut and razon):
                raise ValueError('Falta el RUT o la razón social del arrendatario.')
            c.arrendatario, _ = Arrendatario.objects.get_or_create(rut=rut, razon_social=razon,
                                                                    defaults={'representante': d.get('representante', '')})
        for clave, _, tipo in CAMPOS:
            if clave in claves:
                v = _convertir(d.get(clave, ''), tipo)
                if v is not None:
                    setattr(c, clave, v)
        for clave, v in manual.items():
            setattr(c, clave, v)
        antes = foto_contrato(c) if c.pk else {'nuevo': True}
        if 'fecha_inicio_cobro' in manual or ('fecha_inicio_cobro' in claves and d.get('fecha_inicio_cobro')):
            c.inicio_cobro_auto = False   # fecha fijada (por el contrato o a mano): no se recalcula sola
        fuente = prop.archivo.nombre
        if fuente.lower() not in (c.documentos_fuente or '').lower():
            c.documentos_fuente = '; '.join(x for x in (c.documentos_fuente, fuente) if x)
        c.save()
        if 'tramos' in claves:
            nuevos = tramos_propuestos(d)
            if not nuevos:
                raise ValueError('La propuesta no trae tramos de renta válidos.')
            c.tramos.all().delete()
            for t in nuevos:
                TramoRenta.objects.create(contrato=c, desde=t['desde'], hasta=t['hasta'], monto=t['monto'], unidad=t['unidad'],
                                          tipo=t['tipo'][:80], fuente=fuente[:120], nota=('IA: ' + t['nota']).strip()[:500])
    ahora = datetime.now(timezone.utc)
    prop.contrato, prop.estado, prop.resuelta_por, prop.resuelta_en = c, PropuestaIA.Estado.APLICADA, usuario, ahora
    prop.nota = 'Aplicado: ' + ', '.join(sorted(claves))
    prop.antes = antes
    prop.save()
    a = prop.archivo
    a.contrato, a.estado, a.revisado_por, a.revisado_en = c, 'R', usuario, ahora
    a.save()
    EventoArchivo.objects.create(archivo=a, tipo='APLICADO', usuario=usuario, detalle=f'propuesta n.º {prop.pk} aplicada a {c.codigo}')
    return c


def foto_contrato(c: Contrato) -> dict:
    """Cómo está el contrato en la base (campos que la IA puede cambiar y calendario de renta), para poder deshacer."""
    previo = Contrato.objects.get(pk=c.pk)
    return {'campos': {k: historial._txt(getattr(previo, k)) for k, _, _ in CAMPOS},
            'documentos_fuente': previo.documentos_fuente,
            'tramos': [dict(desde=historial._txt(t.desde), hasta=historial._txt(t.hasta), monto=historial._txt(t.monto), unidad=t.unidad,
                            tipo=t.tipo, fuente=t.fuente, nota=t.nota, inferido=t.inferido) for t in previo.tramos.all()]}


def _antes_desde_historial(prop: PropuestaIA) -> dict:
    """Propuestas aplicadas antes de que se guardara la foto: se arma con el historial de cambios del momento en que se aplicó."""
    if not (prop.contrato_id and prop.resuelta_en):
        return {}
    filas = list(RegistroCambio.objects.filter(contrato_id=prop.contrato_id, origen='IA', usuario=prop.resuelta_por,
                                               fecha__gte=prop.resuelta_en - timedelta(minutes=2), fecha__lte=prop.resuelta_en)
                 .order_by('fecha', 'id'))
    if any(f.objeto == 'Contrato' and f.accion == 'creado' for f in filas):
        return {'nuevo': True}
    nombres = {Contrato._meta.get_field(k).verbose_name: k for k, _, _ in CAMPOS}
    campos = {}
    for f in filas:
        if f.objeto == 'Contrato' and f.accion == 'modificado':
            for nombre, (antes, _) in f.cambios.items():
                if nombre in nombres:
                    campos.setdefault(nombres[nombre], antes)
    borrados = [f.cambios for f in filas if f.objeto == 'Tramo de renta' and f.accion == 'eliminado']
    if not borrados and not campos:
        return {}
    tipo_n = TramoRenta._meta.get_field('tipo').verbose_name
    inf_n = TramoRenta._meta.get_field('inferido').verbose_name
    ant = lambda d, k: (d.get(k) or ['', ''])[0]
    return {'campos': campos, 'desde_historial': True,
            'tramos': [dict(desde=ant(d, 'desde'), hasta=ant(d, 'hasta'), monto=ant(d, 'monto'), unidad=ant(d, 'unidad') or 'UF',
                            tipo=ant(d, tipo_n), fuente=ant(d, 'fuente'), nota=ant(d, 'nota'), inferido=ant(d, inf_n) == 'True')
                       for d in borrados] if 'tramos' in prop.nota else None}


def _valor(txt: str, tipo: str):
    if tipo == 'bool':
        return txt == 'True'
    if tipo in ('str', 'choice'):
        return txt or ''
    return _convertir(txt, tipo)


def plan_deshacer(prop: PropuestaIA) -> dict:
    """Qué haría «deshacer» con una propuesta aplicada: {error} o {campos: [(etiqueta, hoy, vuelve)], tramos_hoy, tramos_vuelven (textos), antes}."""
    c = prop.contrato
    if prop.estado != PropuestaIA.Estado.APLICADA or c is None:
        return {'error': 'Esta propuesta no está aplicada a un contrato.'}
    antes = prop.antes or _antes_desde_historial(prop)
    if antes.get('nuevo'):
        return {'error': f'Este archivo creó el contrato {c.codigo}: no hay una versión anterior a la que volver. '
                         'Si el contrato no corresponde, desactívelo en «Editar condiciones».'}
    if not antes:
        return {'error': 'No quedó registro de cómo estaba el contrato antes de aplicar este archivo: corrija la renta a mano '
                         '(Administración › Contratos) o vuelva a leer con la IA el contrato vigente.'}
    posterior = (PropuestaIA.objects.filter(contrato=c, estado=PropuestaIA.Estado.APLICADA, resuelta_en__gt=prop.resuelta_en)
                 .exclude(pk=prop.pk).select_related('archivo').first())
    if posterior:
        return {'error': f'Después se aplicó «{posterior.archivo.nombre}» al mismo contrato: deshacer este archivo borraría también '
                         'esos cambios. Revise la renta a mano o vuelva a leer con la IA el contrato vigente.'}
    hoy = foto_contrato(c)
    campos = []
    for clave, etiqueta, tipo in CAMPOS:
        if clave in antes.get('campos', {}) and antes['campos'][clave] != hoy['campos'][clave]:
            campo = Contrato._meta.get_field(clave)
            campos.append((etiqueta, _mostrar(getattr(c, clave), tipo, campo), _mostrar(_valor(antes['campos'][clave], tipo), tipo, campo)))
    tramos = antes.get('tramos')
    a_lista = lambda ts: '\n'.join(_fmt_tramos([dict(t, desde=date.fromisoformat(t['desde']), hasta=date.fromisoformat(t['hasta']) if t['hasta'] else None)
                                      for t in sorted(ts, key=lambda t: t['desde'])])) or '(sin tramos)'
    return {'antes': antes, 'campos': campos, 'tramos_hoy': a_lista(hoy['tramos']),
            'tramos_vuelven': a_lista(tramos) if tramos is not None else None}


@transaction.atomic
def deshacer(prop: PropuestaIA, usuario: str) -> Contrato:
    """Devuelve el contrato a como estaba antes de aplicar la propuesta (p. ej. se borró de la carpeta un anexo temporal)."""
    plan = plan_deshacer(prop)
    if plan.get('error'):
        raise ValueError(plan['error'])
    antes, c = plan['antes'], prop.contrato
    with historial.con_origen('deshacer archivo', usuario):
        for clave, _, tipo in CAMPOS:
            if clave in antes.get('campos', {}):
                setattr(c, clave, _valor(antes['campos'][clave], tipo))
        if 'documentos_fuente' in antes:
            c.documentos_fuente = antes['documentos_fuente']
        else:
            c.documentos_fuente = '; '.join(x.strip() for x in (c.documentos_fuente or '').split(';')
                                            if x.strip() and x.strip().lower() != prop.archivo.nombre.lower())
        c.save()
        if antes.get('tramos') is not None:
            c.tramos.all().delete()
            for t in antes['tramos']:
                TramoRenta.objects.create(contrato=c, desde=date.fromisoformat(t['desde']),
                                          hasta=date.fromisoformat(t['hasta']) if t['hasta'] else None,
                                          monto=Decimal(t['monto']) if t['monto'] else None, unidad=t['unidad'], tipo=t['tipo'],
                                          fuente=t['fuente'], nota=t['nota'], inferido=t['inferido'])
    prop.estado = PropuestaIA.Estado.DESHECHA
    prop.nota = f'{prop.nota} · Deshecho por {usuario or "sistema"}'.strip(' ·')
    prop.save()
    EventoArchivo.objects.create(archivo=prop.archivo, tipo='DESHECHO', usuario=usuario,
                                 detalle=f'{c.codigo} volvió a como estaba antes de aplicar la propuesta n.º {prop.pk}')
    return c


def deshacible(archivo) -> PropuestaIA | None:
    """La última propuesta aplicada de un archivo (la que «Deshacer» revertiría), si hay."""
    return archivo.propuestas.filter(estado=PropuestaIA.Estado.APLICADA, contrato__isnull=False).order_by('-resuelta_en').first()


def descartar(prop: PropuestaIA, usuario: str):
    prop.estado, prop.resuelta_por, prop.resuelta_en = PropuestaIA.Estado.DESCARTADA, usuario, datetime.now(timezone.utc)
    prop.save()
    EventoArchivo.objects.create(archivo=prop.archivo, tipo='DESCARTADO', usuario=usuario, detalle=f'propuesta n.º {prop.pk} descartada')


# ------------------------------------------------------------------ actas de entrega
ESQUEMA_ACTA = _obj({
    'resumen': {'type': 'string', 'description': '1 a 3 frases: qué local se entrega, a quién y en qué estado'},
    'contrato_existente_codigo': {'type': 'string', 'description': 'código del contrato del sistema al que corresponde (de la lista entregada), o ""'},
    'numero': {'type': 'string', 'description': 'número del acta si lo tiene, o ""'},
    'fecha_entrega': FECHA,
    'inicio_gastos_comunes': {'type': 'string', 'description': 'fecha de inicio de gastos comunes (GGCC) si figura, AAAA-MM-DD, o ""'},
    'locales': {'type': 'string', 'description': 'locales entregados, como los nombra el acta (incluya dirección o módulo si aparece)'},
    'equipamiento': {'type': 'array', 'description': 'lista de chequeo del acta: cada elemento con «si», «no» o «» si está en blanco',
                     'items': _obj({'elemento': TEXTO, 'estado': _enum('si', 'no', '')})},
    'arrendatario_razon_social': TEXTO, 'arrendatario_rut': TEXTO,
    'entrega_por': {'type': 'string', 'description': 'nombre (y cargo) de quien entrega por el arrendador'},
    'recibe': {'type': 'string', 'description': 'nombre (y RUT o cargo) de quien recibe por el arrendatario'},
    'lecturas': {'type': 'array', 'items': _obj({'servicio': _enum('luz', 'gas', 'agua', 'otro'), 'medidor': TEXTO, 'lectura': TEXTO})},
    'observaciones': {'type': 'string', 'description': 'estado del local, llaves, pendientes y observaciones del acta'},
    'dudas': {'type': 'array', 'items': TEXTO},
})

INSTRUCCIONES_ACTA = """Eres un asistente de administración de centros comerciales en Chile (Grupo Inverco, Talca).
Lees un acta de entrega de local (PDF o foto) y extraes sus datos. Usa solo lo que dice el acta; si algo no aparece, deja "".
Fechas en AAAA-MM-DD. Anota en «dudas» lo ilegible o ambiguo (firmas, fechas borrosas, tachaduras)."""

TIPOS_ACTA = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}


def iniciar_acta(acta: ActaEntrega):
    if not clave_api():
        raise SinClave('Falta la clave de la IA (Anthropic). Ingrésela en Contratos › Carpetas y configuración.')
    acta.estado, acta.error = ActaEntrega.Estado.LEYENDO, ''
    acta.save()
    if EN_SEGUNDO_PLANO:
        threading.Thread(target=leer_acta, args=(acta.pk,), daemon=True).start()
    else:
        leer_acta(acta.pk)


def leer_acta(acta_id: int, cliente=None):
    """Lee el acta con la IA y completa los campos que estén vacíos (lo escrito a mano no se pisa)."""
    close_old_connections()
    acta = ActaEntrega.objects.select_related('sociedad', 'contrato').get(pk=acta_id)
    try:
        tipo = TIPOS_ACTA.get(acta.extension)
        if not tipo:
            raise ValueError('formato no soportado (use PDF, JPG o PNG)')
        lista = [dict(codigo=c.codigo, fantasia=c.nombre_fantasia, arrendatario=c.arrendatario.razon_social, rut=c.arrendatario.rut,
                      locales=', '.join(l.codigo_plano for l in c.locales.all()))
                 for c in Contrato.objects.filter(sociedad=acta.sociedad).select_related('arrendatario').prefetch_related('locales')]
        texto = (f'Acta de entrega de la sociedad {acta.sociedad.nombre}. Contratos de esta sociedad: {json.dumps(lista, ensure_ascii=False)}. '
                 'Extrae los datos del acta adjunta según el esquema.')
        contenido = acta.leer_bytes()
        d, _, _, costo = _llamar(cliente or _cliente(), settings.IA_MODELO, contenido, tipo, texto, ESQUEMA_ACTA, INSTRUCCIONES_ACTA)
        acta.datos, acta.costo_usd = d, acta.costo_usd + costo
        if not acta.contrato_id and d.get('contrato_existente_codigo'):
            acta.contrato = Contrato.objects.filter(sociedad=acta.sociedad, codigo=d['contrato_existente_codigo']).first()
        for campo in ('fecha_entrega', 'inicio_gastos_comunes'):
            if not getattr(acta, campo) and d.get(campo):
                try:
                    setattr(acta, campo, date.fromisoformat(d[campo]))
                except ValueError:
                    pass
        if not acta.equipamiento and d.get('equipamiento'):
            acta.equipamiento = d['equipamiento']
        for campo in ('numero', 'locales', 'entrega_por', 'recibe', 'observaciones'):
            if not getattr(acta, campo) and d.get(campo):
                setattr(acta, campo, d[campo] if campo == 'observaciones' else d[campo][:30 if campo == 'numero' else 200])
        if not acta.lecturas and d.get('lecturas'):
            acta.lecturas = '\n'.join(f"{x.get('servicio', '')} {x.get('medidor', '')}: {x.get('lectura', '')}".strip() for x in d['lecturas'])
        acta.estado = ActaEntrega.Estado.LEIDA
    except Exception as e:
        acta.estado, acta.error = ActaEntrega.Estado.ERROR, _mensaje_error(e)
    with historial.con_origen('IA', ''):
        acta.save()
    close_old_connections()
    return acta


def registrar_acta(acta: ActaEntrega, usuario: str):
    """Pasa la fecha de entrega del acta al contrato (y con ella se recalcula el inicio de cobro si corresponde)."""
    if not acta.contrato_id:
        raise ValueError('Asocie el acta a un contrato antes de registrarla.')
    if not acta.fecha_entrega:
        raise ValueError('Falta la fecha de entrega del acta.')
    with transaction.atomic(), historial.con_origen('panel', usuario):
        c = acta.contrato
        if acta.estado != ActaEntrega.Estado.REGISTRADA or not acta.antes:
            acta.antes = {'contrato_id': c.pk, **{k: historial._txt(getattr(c, k)) for k in CAMPOS_ACTA}}
        c.fecha_entrega = acta.fecha_entrega
        c.save()
        acta.estado = ActaEntrega.Estado.REGISTRADA
        acta.save()
    return c


CAMPOS_ACTA = ('fecha_entrega', 'fecha_inicio_cobro', 'inicio_cobro_auto')


def plan_deshacer_acta(acta: ActaEntrega) -> dict:
    """{error} o {contrato, hoy, vuelve}: la fecha de entrega (y el inicio de cobro) que tenía el contrato antes de registrar el acta."""
    if acta.estado != ActaEntrega.Estado.REGISTRADA or not acta.contrato_id:
        return {'error': 'El acta no está registrada en un contrato.'}
    antes = dict(acta.antes or {})
    if antes and antes.get('contrato_id') != acta.contrato_id:
        return {'error': 'El acta se asoció a otro contrato después de registrarla: corrija la fecha de entrega a mano en «Editar condiciones».'}
    if not antes:   # registrada antes de que se guardara la foto: se busca en el historial
        nombre = Contrato._meta.get_field('fecha_entrega').verbose_name
        r = next((r for r in RegistroCambio.objects.filter(contrato_id=acta.contrato_id, objeto='Contrato', accion='modificado')
                  if (r.cambios.get(nombre) or ['', ''])[1] == historial._txt(acta.fecha_entrega)), None)
        if r is None:
            return {'error': 'No quedó registro de la fecha de entrega anterior: corríjala a mano en «Editar condiciones».'}
        ini = Contrato._meta.get_field('fecha_inicio_cobro').verbose_name
        antes = {'fecha_entrega': r.cambios[nombre][0], 'desde_historial': True}
        if ini in r.cambios:
            antes['fecha_inicio_cobro'] = r.cambios[ini][0]
    c = acta.contrato
    if c.fecha_entrega != acta.fecha_entrega:
        return {'error': f'La fecha de entrega de {c.codigo} cambió después de registrar el acta ({_mostrar(c.fecha_entrega, "date")}): '
                         'corríjala a mano en «Editar condiciones».'}
    fecha = lambda t: date.fromisoformat(t) if t else None
    return {'contrato': c, 'antes': antes,
            'hoy': [('Fecha de entrega', _mostrar(c.fecha_entrega, 'date')), ('Inicio de cobro', _mostrar(c.fecha_inicio_cobro, 'date'))],
            'vuelve': [('Fecha de entrega', _mostrar(fecha(antes.get('fecha_entrega')), 'date')),
                       ('Inicio de cobro', _mostrar(fecha(antes['fecha_inicio_cobro']), 'date') if 'fecha_inicio_cobro' in antes
                        else 'se calcula solo con la regla del contrato')]}


def deshacer_acta(acta: ActaEntrega, usuario: str) -> Contrato:
    """Devuelve al contrato la fecha de entrega (e inicio de cobro) que tenía antes de registrar el acta; el acta queda «leída»."""
    plan = plan_deshacer_acta(acta)
    if plan.get('error'):
        raise ValueError(plan['error'])
    antes, c = plan['antes'], plan['contrato']
    with transaction.atomic(), historial.con_origen('deshacer acta', usuario):
        c.fecha_entrega = date.fromisoformat(antes['fecha_entrega']) if antes.get('fecha_entrega') else None
        if 'inicio_cobro_auto' in antes:
            c.inicio_cobro_auto = antes['inicio_cobro_auto'] == 'True'
        if 'fecha_inicio_cobro' in antes:   # si es automática, save() la vuelve a calcular cuando se pueda
            c.fecha_inicio_cobro = date.fromisoformat(antes['fecha_inicio_cobro']) if antes['fecha_inicio_cobro'] else None
        c.save()
        acta.estado, acta.antes = ActaEntrega.Estado.LEIDA, {}
        acta.save()
    return c


def leer_actas_pendientes(sociedad):
    """Manda a la IA todas las actas sin leer de la sociedad (una tras otra, en segundo plano). Devuelve cuántas."""
    if not clave_api():
        raise SinClave('Falta la clave de la IA (Anthropic). Ingrésela en Contratos › Carpetas y configuración.')
    ids = list(ActaEntrega.objects.filter(sociedad=sociedad, estado='S', ya_no_esta=False).values_list('pk', flat=True))
    ActaEntrega.objects.filter(pk__in=ids).update(estado='P', error='')

    def trabajar():
        for i in ids:
            leer_acta(i)
    if EN_SEGUNDO_PLANO:
        threading.Thread(target=trabajar, daemon=True).start()
    else:
        trabajar()
    return len(ids)
