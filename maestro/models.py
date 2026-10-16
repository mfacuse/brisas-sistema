"""Maestro de sociedades, propiedades, locales, arrendatarios y contratos.

Fuente de los datos iniciales: planillas de la Fase 0 (revisión de contratos y maestro de locales).
"""
import re
from decimal import Decimal
from pathlib import Path

from django.db import models


class Sociedad(models.Model):
    """Sociedad que factura (una sesión de BSOFT por sociedad)."""
    nombre = models.CharField(max_length=120)
    rut = models.CharField(max_length=15, unique=True)
    giro = models.CharField(max_length=120, blank=True, default='Arriendo Inmuebles Amoblados')
    direccion = models.CharField(max_length=160, blank=True)
    sigla = models.CharField('sigla (numeración interna)', max_length=6, blank=True,
                             help_text='Prefijo de los números internos: BT-F-0001 (facturas) y BT-NC-0001 (notas de cobro)')
    carpeta_contratos = models.CharField('carpeta de contratos', max_length=500, blank=True)
    carpeta_facturas = models.CharField('carpeta de facturas emitidas (PDF de BSOFT)', max_length=500, blank=True)
    carpeta_actas = models.CharField('carpeta de actas de entrega', max_length=500, blank=True)
    datos_pago = models.TextField('datos para el pago (van en la nota de cobro)', blank=True)

    class Meta:
        verbose_name_plural = 'sociedades'

    def __str__(self):
        return f'{self.nombre} ({self.rut})'


class Propiedad(models.Model):
    sociedad = models.ForeignKey(Sociedad, on_delete=models.PROTECT, related_name='propiedades')
    codigo = models.SlugField(max_length=30, unique=True)
    nombre = models.CharField(max_length=80)
    direccion = models.CharField(max_length=160, blank=True)
    nombre_glosa = models.CharField('nombre en la glosa de la factura', max_length=80, blank=True)
    carpeta_planos = models.CharField('carpeta de planos (.dxf)', max_length=500, blank=True)
    prefijo = models.CharField('letra de los códigos de contrato', max_length=4, blank=True,
                               help_text='B → B-01, B-02…; vacío = primera letra del nombre')

    class Meta:
        verbose_name_plural = 'propiedades'

    def __str__(self):
        return self.nombre

    def letra(self) -> str:
        return (self.prefijo or self.nombre[:1] or 'C').upper()

    def siguiente_codigo(self) -> str:
        """Siguiente código correlativo de contrato de esta propiedad (B-41 si el último es B-40). No reutiliza números."""
        letra = self.letra()
        nums = [int(m.group(1)) for c in Contrato.objects.filter(codigo__startswith=f'{letra}-').values_list('codigo', flat=True)
                if (m := re.fullmatch(rf'{re.escape(letra)}-(\d+)', c))]
        return f'{letra}-{max(nums, default=0) + 1:02d}'


class Local(models.Model):
    """Unidad física. Guarda el número del plano y el municipal (son distintos)."""
    class Tipo(models.TextChoices):
        LOCAL = 'LOCAL', 'Local'
        MODULO = 'MODULO', 'Módulo'
        SUPERMERCADO = 'SUPER', 'Supermercado'
        ESTACIONAMIENTO = 'ESTAC', 'Estacionamiento'
        PUBLICIDAD = 'PUBLI', 'Publicidad'
        ACCESO = 'ACCESO', 'Acceso peatonal'

    propiedad = models.ForeignKey(Propiedad, on_delete=models.PROTECT, related_name='locales')
    codigo_plano = models.CharField('local (plano)', max_length=40)
    tipo = models.CharField(max_length=8, choices=Tipo.choices, default=Tipo.LOCAL)
    piso = models.CharField(max_length=30, blank=True)
    calle = models.CharField(max_length=30, blank=True)
    numero_municipal = models.CharField('n° municipal / de contrato', max_length=20, blank=True)
    designacion = models.CharField(max_length=60, blank=True)
    m2_oficial = models.DecimalField('m² oficiales (ficha)', max_digits=9, decimal_places=2, null=True, blank=True)
    disponible = models.BooleanField('disponible (sin contrato, confirmado)', default=False)
    observaciones = models.TextField(blank=True)

    class Meta:
        unique_together = [('propiedad', 'codigo_plano')]
        ordering = ['propiedad', 'id']
        verbose_name_plural = 'locales'

    def __str__(self):
        return f'{self.propiedad.codigo}:{self.codigo_plano}'


class Arrendatario(models.Model):
    """Se identifica por RUT + razón social. Los datos de contacto se cargan después (no vienen de la Fase 0)."""
    razon_social = models.CharField(max_length=160)
    rut = models.CharField(max_length=20)
    representante = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)

    class Meta:
        unique_together = [('rut', 'razon_social')]
        ordering = ['razon_social']

    def __str__(self):
        return f'{self.razon_social} ({self.rut})'


class CondicionPago(models.Model):
    """Condición de pago de las facturas (maestro; Matías, 2026-10-15): CONTADO, CRÉDITO, CRÉDITO 30 DÍAS, CRÉDITO 60 DÍAS…"""
    POR_DEFECTO = 'CRÉDITO'
    nombre = models.CharField(max_length=40, unique=True)
    orden = models.PositiveSmallIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'condición de pago'
        verbose_name_plural = 'condiciones de pago'

    def __str__(self):
        return self.nombre

    @classmethod
    def por_defecto(cls):
        return cls.objects.get_or_create(nombre=cls.POR_DEFECTO, defaults={'orden': 2})[0]


class Contrato(models.Model):
    class TipoRenta(models.TextChoices):
        FIJA = 'FIJA', 'Fija'
        MINIMO_VARIABLE = 'MINVAR', 'Mínimo o % de ventas/ingresos'

    class Periodicidad(models.TextChoices):
        MENSUAL = 'M', 'Mensual'
        SEMESTRAL = 'S', 'Semestral'

    class TipoDocumento(models.TextChoices):
        FACTURA_AFECTA = 'FA', 'Factura afecta'
        FACTURA_EXENTA = 'FE', 'Factura exenta'
        NOTA_COBRO = 'NC', 'Nota de cobro (sin IVA, no DTE)'

    class ReglaUF(models.TextChoices):
        DIA1 = 'D1', 'UF del día 1 del mes'
        PRIMER_HABIL = 'PH', 'UF del primer día hábil'

    class ModoCambioTramo(models.TextChoices):
        PRORRATA = 'PR', 'Prorratear por días cuando la renta cambia a mitad de mes'
        INICIO_MES = 'IM', 'Aplicar la renta vigente el día 1 de cada mes'

    class ReglaInicioCobro(models.TextChoices):
        CALENDARIO = '', 'Según el calendario de renta (o la fecha indicada)'
        ENTREGA = 'ENT', 'Desde la entrega del local (+ días indicados)'
        APERTURA = 'APE', 'Desde la apertura'
        PRIMERO = 'PRI', 'Apertura o N días desde la entrega, lo que ocurra primero'

    class QuienCobra(models.TextChoices):
        MEGASERVICIOS = 'MEGA', 'Megaservicios (directo al arrendatario)'
        INMOBILIARIA = 'INM', 'La inmobiliaria (en la factura)'
        NO_SE_COBRA = 'NO', 'No se cobra (paga directo a la empresa de servicio)'

    class BaseVariable(models.TextChoices):
        NINGUNA = '', 'Sin renta variable'
        VENTAS = 'V', 'Ventas netas'
        INGRESOS = 'I', 'Ingresos netos'

    codigo = models.CharField(max_length=12, unique=True, blank=True,
                              help_text='Se asigna solo al crear el contrato: letra de la propiedad + correlativo (B-01, O-01…)')
    propiedad = models.ForeignKey(Propiedad, on_delete=models.PROTECT, related_name='contratos')
    sociedad = models.ForeignKey(Sociedad, on_delete=models.PROTECT, related_name='contratos')
    arrendatario = models.ForeignKey(Arrendatario, on_delete=models.PROTECT, related_name='contratos')
    nombre_fantasia = models.CharField(max_length=80)
    locales = models.ManyToManyField(Local, through='ContratoLocal', related_name='contratos')
    direccion_contrato = models.CharField('dirección según contrato (para la factura)', max_length=200, blank=True)
    representante = models.CharField(max_length=200, blank=True)

    # plazo
    fecha_contrato = models.DateField(null=True, blank=True)
    inicio_vigencia = models.DateField()
    plazo_meses = models.PositiveIntegerField(default=12)
    fin_pactado = models.DateField('fin pactado (si el contrato fija fecha)', null=True, blank=True)
    prorroga_meses = models.PositiveIntegerField('prórroga (0 = sin prórroga)', default=12)
    aviso_dias = models.PositiveIntegerField('aviso de no renovación (días)', null=True, blank=True)
    fecha_termino_real = models.DateField('término anticipado / efectivo', null=True, blank=True)
    fecha_entrega = models.DateField('fecha de entrega del local', null=True, blank=True)
    fecha_apertura = models.DateField('fecha de apertura', null=True, blank=True)
    regla_inicio_cobro = models.CharField('desde cuándo se cobra la renta', max_length=3, choices=ReglaInicioCobro.choices, blank=True, default='')
    dias_inicio_cobro = models.PositiveIntegerField('días desde la entrega', null=True, blank=True,
                                                    help_text='para «desde la entrega» o «lo que ocurra primero» (ej. 60)')
    fecha_inicio_cobro = models.DateField('inicio de cobro de la renta', null=True, blank=True,
                                          help_text='Se completa sola según la regla y las fechas de entrega/apertura; se puede cambiar a mano')
    inicio_cobro_auto = models.BooleanField('inicio de cobro calculado por el sistema', default=True, editable=False)

    # cobro
    tipo_renta = models.CharField(max_length=8, choices=TipoRenta.choices, default=TipoRenta.FIJA)
    periodicidad = models.CharField(max_length=1, choices=Periodicidad.choices, default=Periodicidad.MENSUAL)
    meses_cobro = models.CharField('meses de cobro (semestral)', max_length=20, blank=True, help_text='Ej.: 1,6')
    reajuste_ipc = models.BooleanField('reajuste anual por IPC (renta en pesos)', default=False)
    tipo_documento = models.CharField(max_length=2, choices=TipoDocumento.choices, default=TipoDocumento.FACTURA_AFECTA)
    regla_uf = models.CharField(max_length=2, choices=ReglaUF.choices, default=ReglaUF.DIA1)
    modo_cambio_tramo = models.CharField(max_length=2, choices=ModoCambioTramo.choices, default=ModoCambioTramo.PRORRATA)
    pct_variable = models.DecimalField('% variable', max_digits=6, decimal_places=4, null=True, blank=True,
                                       help_text='0.02 = 2% de las ventas netas del mes anterior')
    base_variable = models.CharField(max_length=1, choices=BaseVariable.choices, blank=True, default='')

    # condiciones
    m2_contrato = models.DecimalField('m² según contrato (base de cobro y de gastos comunes)', max_digits=9, decimal_places=2, null=True, blank=True)
    variable_desde = models.DateField('la renta variable rige desde (vacío = desde el inicio)', null=True, blank=True)
    garantia_uf = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    garantia_clp = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    gastos_comunes = models.TextField('gastos comunes según contrato (referencia)', blank=True)
    cobra_gastos_comunes = models.CharField('quién cobra los gastos comunes', max_length=4, choices=QuienCobra.choices, default=QuienCobra.MEGASERVICIOS)
    cobra_agua = models.CharField('quién cobra el agua', max_length=4, choices=QuienCobra.choices, default=QuienCobra.MEGASERVICIOS)
    cobra_luz = models.CharField('quién cobra la luz', max_length=4, choices=QuienCobra.choices, default=QuienCobra.INMOBILIARIA)
    cobra_gas = models.CharField('quién cobra el gas', max_length=4, choices=QuienCobra.choices, default=QuienCobra.INMOBILIARIA)
    condicion_pago = models.ForeignKey(CondicionPago, verbose_name='condición de pago', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='contratos', help_text='Va en la factura y en el Excel (por defecto CRÉDITO).')
    condiciones = models.TextField(blank=True)
    observaciones = models.TextField(blank=True)
    documentos_fuente = models.TextField(blank=True)
    confianza_lectura = models.CharField(max_length=10, blank=True)
    autoriza_avisos = models.BooleanField('contrato autoriza avisos por correo y WhatsApp', default=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} · {self.nombre_fantasia}'

    def calcular_inicio_cobro(self):
        """Inicio de cobro según la regla del contrato y las fechas de entrega/apertura; None si aún no se puede saber."""
        from datetime import timedelta
        dias = timedelta(days=self.dias_inicio_cobro or 0)
        r = self.regla_inicio_cobro
        if r == 'ENT' and self.fecha_entrega:
            return self.fecha_entrega + dias
        if r == 'APE':
            return self.fecha_apertura
        if r == 'PRI' and self.fecha_entrega:
            tope = self.fecha_entrega + dias
            return min(self.fecha_apertura, tope) if self.fecha_apertura else tope
        return None

    def save(self, *a, **k):
        if not self.codigo:
            self.codigo = self.propiedad.siguiente_codigo()
        if self.condicion_pago_id is None:
            self.condicion_pago = CondicionPago.por_defecto()
        # se completa sola mientras nadie la haya fijado a mano (una fecha escrita a mano no se pisa)
        if self.fecha_inicio_cobro is None or self.inicio_cobro_auto:
            calc = self.calcular_inicio_cobro()
            if calc:
                self.fecha_inicio_cobro, self.inicio_cobro_auto = calc, True
        super().save(*a, **k)

    def cobra_inmobiliaria(self, servicio: str) -> bool:
        """¿La inmobiliaria cobra este servicio en su factura? (lo puede cobrar Megaservicios o no cobrarse; pantalla «Quién cobra cada servicio»)."""
        return self.quien_cobra(servicio) == 'INM'

    def quien_cobra(self, servicio: str) -> str:
        return {'GGCC': self.cobra_gastos_comunes, 'AGUA': self.cobra_agua, 'ELEC': self.cobra_luz, 'GAS': self.cobra_gas}.get(servicio, 'INM')

    @property
    def meses_cobro_lista(self):
        return [int(x) for x in self.meses_cobro.split(',') if x.strip()]

    @property
    def m2_cobro(self):
        """m² base de cobro y de gastos comunes: los del contrato (decisión del propietario, 09-10-2026)."""
        if self.m2_contrato is not None:
            return self.m2_contrato
        return sum((l.m2_oficial or Decimal('0')) for l in self.locales.all())


class ContratoLocal(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    local = models.ForeignKey(Local, on_delete=models.PROTECT)

    class Meta:
        unique_together = [('contrato', 'local')]

    def __str__(self):
        return f'{self.contrato.codigo} ↔ {self.local}'


class TramoRenta(models.Model):
    """Un tramo del calendario de renta de un contrato. monto=None → el contrato no lo define."""
    class Unidad(models.TextChoices):
        UF = 'UF', 'UF'
        CLP = 'CLP', 'Pesos'

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='tramos')
    desde = models.DateField()
    hasta = models.DateField('hasta (vacío = sin fecha de término)', null=True, blank=True)
    monto = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unidad = models.CharField(max_length=3, choices=Unidad.choices, default=Unidad.UF)
    tipo = models.CharField('tipo de renta (texto de la planilla)', max_length=80, blank=True)
    fuente = models.CharField(max_length=120, blank=True)
    nota = models.TextField(blank=True)
    inferido = models.BooleanField('fecha o monto inferido (por confirmar)', default=False)

    class Meta:
        ordering = ['contrato', 'desde']

    def __str__(self):
        return f'{self.contrato.codigo} {self.desde}→{self.hasta or "…"}: {self.monto} {self.unidad}'


class Descuento(models.Model):
    class Tipo(models.TextChoices):
        PORCENTAJE = 'PCT', '% de la renta'
        UF = 'UF', 'UF al mes'
        CLP = 'CLP', 'Pesos al mes'

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='descuentos')
    desde = models.DateField()
    hasta = models.DateField()
    tipo = models.CharField(max_length=3, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=14, decimal_places=4)
    motivo = models.CharField(max_length=160)


class Garantia(models.Model):
    """Registro de la garantía recibida (Fase 2 la usa en cobranza y devoluciones)."""
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='garantias')
    monto_uf = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monto_clp = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    forma = models.CharField(max_length=40, blank=True, help_text='depósito, boleta, vale vista…')
    fecha_recepcion = models.DateField(null=True, blank=True)
    vencimiento = models.DateField(null=True, blank=True)
    nota = models.CharField(max_length=200, blank=True)


class SaldoInformado(models.Model):
    """Saldo adeudado informado por el propietario (no calculado por el sistema)."""
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='saldos')
    concepto = models.CharField(max_length=60, default='Saldo adeudado')
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    unidad = models.CharField(max_length=3, choices=TramoRenta.Unidad.choices)
    fecha = models.DateField()
    fuente = models.CharField(max_length=120, blank=True)
    nota = models.CharField(max_length=200, blank=True)


class ContratoServicio(models.Model):
    """Contratos que no son arriendos (p. ej. administración con Megaservicios Talca SpA)."""
    codigo = models.CharField(max_length=12, unique=True)
    sociedad = models.ForeignKey(Sociedad, on_delete=models.PROTECT)
    contraparte = models.CharField(max_length=160)
    rut_contraparte = models.CharField(max_length=20)
    objeto = models.CharField(max_length=200)
    fecha = models.DateField(null=True, blank=True)
    vigencia = models.CharField(max_length=200, blank=True)
    condiciones = models.TextField(blank=True)

    def __str__(self):
        return f'{self.codigo} · {self.contraparte}'


# ---------------------------------------------------------------------- archivos originales, historial y lectura con IA
class ArchivoContrato(models.Model):
    """Un PDF encontrado en la carpeta de contratos de una sociedad. El sistema compara tamaño y fecha de modificación
    en cada revisión para saber si es nuevo, si cambió o si desapareció."""
    class Estado(models.TextChoices):
        NUEVO = 'N', 'Nuevo'
        CAMBIADO = 'C', 'Cambiado'
        REVISADO = 'R', 'Al día'
        ELIMINADO = 'E', 'Ya no está en la carpeta'

    sociedad = models.ForeignKey(Sociedad, on_delete=models.PROTECT, related_name='archivos_contrato')
    contrato = models.ForeignKey(Contrato, null=True, blank=True, on_delete=models.SET_NULL, related_name='archivos')
    ruta = models.CharField(max_length=700, help_text='ruta completa en este computador')
    nombre = models.CharField(max_length=255)
    tamano = models.BigIntegerField(default=0)
    modificado = models.DateTimeField(null=True, blank=True)
    drive_id = models.CharField(max_length=80, blank=True)
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.NUEVO)
    ignorar = models.BooleanField('no es un contrato de arriendo (no avisar)', default=False)
    visto_primera = models.DateTimeField(auto_now_add=True)
    visto_ultima = models.DateTimeField(null=True, blank=True)
    revisado_por = models.CharField(max_length=80, blank=True)
    revisado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('sociedad', 'ruta')]
        ordering = ['sociedad', 'nombre']
        verbose_name = 'archivo de contrato'
        verbose_name_plural = 'archivos de contratos'

    def __str__(self):
        return self.nombre

    @property
    def url_drive(self):
        return f'https://drive.google.com/file/d/{self.drive_id}/view' if self.drive_id else ''

    @property
    def pendiente(self):
        # también queda pendiente si la IA lo leyó y nadie aplicó ni descartó su propuesta
        if self.ignorar or self.estado == 'E':
            return False
        return self.estado in ('N', 'C') or self.propuestas.filter(estado__in=('P', 'L')).exists()


class EventoArchivo(models.Model):
    """Historial de cada archivo: cuándo apareció, cambió, desapareció, a qué contrato se asoció, etc."""
    archivo = models.ForeignKey(ArchivoContrato, on_delete=models.CASCADE, related_name='eventos')
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=20)
    detalle = models.CharField(max_length=300, blank=True)
    usuario = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ['-fecha', '-id']


class RegistroCambio(models.Model):
    """Historial de cambios de contratos (y sus rentas, descuentos, locales) y de la configuración de cada sociedad.
    Se escribe solo, desde el panel, la administración, el importador o una propuesta de la IA."""
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=80, blank=True)
    origen = models.CharField(max_length=30, blank=True, help_text='panel, administración, importador, IA, sistema…')
    contrato = models.ForeignKey(Contrato, null=True, blank=True, on_delete=models.SET_NULL, related_name='cambios')
    objeto = models.CharField(max_length=40)
    objeto_id = models.CharField(max_length=40, blank=True)
    descripcion = models.CharField(max_length=200)
    accion = models.CharField(max_length=12)
    cambios = models.JSONField(default=dict, blank=True, help_text='{campo: [antes, después]}')
    nota = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-fecha', '-id']
        verbose_name = 'cambio registrado'
        verbose_name_plural = 'historial de cambios'


class PropuestaIA(models.Model):
    """Lectura de un PDF por la IA: datos que propone para crear o actualizar un contrato. Nada se aplica sin aprobación."""
    class Estado(models.TextChoices):
        LEYENDO = 'P', 'Leyendo'
        LISTA = 'L', 'Lista para revisar'
        ERROR = 'E', 'Error'
        APLICADA = 'A', 'Aplicada'
        DESCARTADA = 'D', 'Descartada'

    archivo = models.ForeignKey(ArchivoContrato, on_delete=models.CASCADE, related_name='propuestas')
    contrato = models.ForeignKey(Contrato, null=True, blank=True, on_delete=models.SET_NULL, related_name='propuestas')
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.LEYENDO)
    datos = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    modelo = models.CharField(max_length=40, blank=True)
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)
    costo_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    creada = models.DateTimeField(auto_now_add=True)
    pedida_por = models.CharField(max_length=80, blank=True)
    resuelta_por = models.CharField(max_length=80, blank=True)
    resuelta_en = models.DateTimeField(null=True, blank=True)
    nota = models.TextField(blank=True)

    class Meta:
        ordering = ['-creada']
        verbose_name = 'propuesta de la IA'
        verbose_name_plural = 'propuestas de la IA'


class ActaEntrega(models.Model):
    """Acta de entrega de un local: se sube el archivo (PDF o foto), la IA rescata los datos y queda el vínculo al archivo."""
    class Estado(models.TextChoices):
        SIN_LEER = 'S', 'Sin leer'
        LEYENDO = 'P', 'Leyendo'
        LEIDA = 'L', 'Leída: revisar'
        ERROR = 'E', 'Error de lectura'
        REGISTRADA = 'R', 'Registrada'

    sociedad = models.ForeignKey(Sociedad, on_delete=models.PROTECT, related_name='actas')
    contrato = models.ForeignKey(Contrato, null=True, blank=True, on_delete=models.SET_NULL, related_name='actas')
    archivo = models.FileField(upload_to='actas_entrega/%Y/', blank=True, help_text='acta subida desde el panel')
    ruta = models.CharField('ruta en la carpeta de actas', max_length=700, blank=True, help_text='acta encontrada en la carpeta de la sociedad')
    tamano = models.BigIntegerField(default=0)
    modificado = models.DateTimeField(null=True, blank=True)
    drive_id = models.CharField(max_length=80, blank=True)
    ya_no_esta = models.BooleanField('ya no está en la carpeta', default=False)
    nombre = models.CharField('nombre del archivo', max_length=255)
    numero = models.CharField('n.º del acta', max_length=30, blank=True)
    inicio_gastos_comunes = models.DateField('inicio de gastos comunes', null=True, blank=True)
    equipamiento = models.JSONField('equipamiento (sí/no)', default=list, blank=True)
    subida_por = models.CharField(max_length=80, blank=True)
    subida_en = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.SIN_LEER)
    fecha_entrega = models.DateField('fecha de entrega', null=True, blank=True)
    locales = models.CharField('locales entregados', max_length=200, blank=True)
    entrega_por = models.CharField('entrega (por el arrendador)', max_length=200, blank=True)
    recibe = models.CharField('recibe (por el arrendatario)', max_length=200, blank=True)
    lecturas = models.TextField('lecturas de medidores al entregar', blank=True)
    observaciones = models.TextField('estado del local y observaciones', blank=True)
    datos = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    costo_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)

    class Meta:
        ordering = ['-subida_en']
        verbose_name = 'acta de entrega'
        verbose_name_plural = 'actas de entrega'

    def __str__(self):
        return f'Acta {self.nombre}' + (f' · {self.contrato.codigo}' if self.contrato_id else '')

    @property
    def url_drive(self):
        return f'https://drive.google.com/file/d/{self.drive_id}/view' if self.drive_id else ''

    def leer_bytes(self) -> bytes:
        if self.ruta:
            from .almacen import leer
            return leer(self.ruta)
        with self.archivo.open('rb') as fh:
            return fh.read()

    @property
    def extension(self) -> str:
        return Path(self.nombre or self.archivo.name).suffix.lower()


class PlanoPiso(models.Model):
    """Un piso de una propiedad, leído de un plano .dxf: fondo (muros, deslindes) y el contorno de cada local, en metros."""
    propiedad = models.ForeignKey(Propiedad, on_delete=models.CASCADE, related_name='planos')
    nombre = models.CharField(max_length=60)
    orden = models.SmallIntegerField(default=0)
    archivo = models.CharField(max_length=700)
    modificado = models.DateTimeField(null=True, blank=True)
    ancho = models.FloatField(default=0)
    alto = models.FloatField(default=0)
    fondo = models.JSONField(default=list, blank=True, help_text='polilíneas del fondo [[x, y], …] en metros')
    textos = models.JSONField(default=list, blank=True, help_text='rótulos del fondo [x, y, texto]')
    importado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['propiedad', 'orden', 'nombre']
        unique_together = [('propiedad', 'archivo')]

    def __str__(self):
        return f'{self.propiedad} · {self.nombre}'


class LocalPlano(models.Model):
    """Contorno de un local en el plano y los locales del maestro que representa."""
    piso = models.ForeignKey(PlanoPiso, on_delete=models.CASCADE, related_name='locales_plano')
    etiqueta = models.CharField(max_length=20, help_text='como figura en el plano: 06, 23, A…')
    locales = models.ManyToManyField(Local, blank=True, related_name='en_plano')
    poligono = models.JSONField(default=list)
    m2_plano = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)
    aproximado = models.BooleanField('contorno aproximado', default=False)

    class Meta:
        ordering = ['piso', 'etiqueta']


class DatoSistema(models.Model):
    """Datos privados y de estado del sistema compartidos por el servidor web y la tarea diaria de la nube
    (permiso de Google Drive, cliente de Google, clave de la IA, último respaldo). No se muestran en pantalla."""
    clave = models.CharField(max_length=60, unique=True)
    valor = models.JSONField(default=dict)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'dato privado del sistema'
        verbose_name_plural = 'datos privados del sistema'

    def __str__(self):
        return self.clave
