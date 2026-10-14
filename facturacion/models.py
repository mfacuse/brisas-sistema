from django.db import models

from maestro.models import Contrato


class VentaMensual(models.Model):
    """Ventas netas (o ingresos netos) del mes `periodo` informadas por el arrendatario, en pesos."""
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='ventas')
    periodo = models.DateField('mes de las ventas (día 1)')
    monto_neto = models.DecimalField(max_digits=16, decimal_places=0)
    fuente = models.CharField(max_length=120, blank=True, help_text='correo, planilla RobFre, ingreso manual…')
    ingresado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('contrato', 'periodo')]
        ordering = ['-periodo']


class MedidorServicio(models.Model):
    """Medidor (luz o gas) o fila de la planilla del proveedor y el contrato al que se cobra.
    Mientras `confirmado` sea falso, los documentos que lo usan quedan con advertencia y no se aprueban solos."""
    class Servicio(models.TextChoices):
        ELECTRICIDAD = 'ELEC', 'Energía eléctrica'
        GAS = 'GAS', 'Gas'
        AGUA = 'AGUA', 'Agua'
        GASTOS_COMUNES = 'GGCC', 'Gastos comunes'

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='medidores')
    servicio = models.CharField(max_length=4, choices=Servicio.choices)
    etiqueta_local = models.CharField('«Nº Local» en la planilla', max_length=60, blank=True)
    nombre_planilla = models.CharField('nombre en la planilla', max_length=80)
    tarifa = models.CharField(max_length=40, blank=True)
    confirmado = models.BooleanField(default=False)
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [('servicio', 'etiqueta_local', 'nombre_planilla')]
        ordering = ['servicio', 'contrato__codigo']
        verbose_name = 'medidor'

    def __str__(self):
        return f'{self.get_servicio_display()} · {self.nombre_planilla} → {self.contrato.codigo}'


class ConsumoServicio(models.Model):
    """Cargo adicional que se suma a la factura del contrato: electricidad o gas por medidor (a costo, desde la
    planilla del proveedor) o un «otro» genérico. `periodo_cobro` es el mes de la factura donde se cobra."""
    class Servicio(models.TextChoices):
        ELECTRICIDAD = 'ELEC', 'Energía eléctrica'
        GAS = 'GAS', 'Gas'
        AGUA = 'AGUA', 'Agua'
        GASTOS_COMUNES = 'GGCC', 'Gastos comunes'
        OTRO = 'OTRO', 'Otro cargo'

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='consumos')
    servicio = models.CharField(max_length=4, choices=Servicio.choices)
    medidor = models.CharField(max_length=60, blank=True, help_text='etiqueta del medidor o local en la planilla')
    medidor_ref = models.ForeignKey(MedidorServicio, null=True, blank=True, on_delete=models.SET_NULL, related_name='consumos')
    concepto = models.CharField('concepto en la factura (solo «otro»)', max_length=80, blank=True)
    periodo_consumo = models.DateField('mes consumido (día 1)')
    periodo_cobro = models.DateField('mes de la factura donde se cobra (día 1)')
    lectura_anterior = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    lectura_actual = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    factor = models.DecimalField('constante de factor', max_digits=8, decimal_places=3, null=True, blank=True)
    cantidad = models.DecimalField('consumo (kWh o litros)', max_digits=14, decimal_places=2, null=True, blank=True)
    unidad_consumo = models.CharField(max_length=6, blank=True)
    tarifa = models.CharField(max_length=40, blank=True)
    detalle = models.CharField(max_length=200, blank=True)
    neto = models.DecimalField(max_digits=14, decimal_places=0)
    origen_archivo = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['-periodo_cobro', 'contrato', 'servicio']
        verbose_name = 'cargo adicional (luz, gas, otro)'
        verbose_name_plural = 'cargos adicionales (luz, gas, otro)'

    def __str__(self):
        return f'{self.contrato.codigo} {self.get_servicio_display()} {self.periodo_cobro:%Y-%m} ${self.neto}'


class Documento(models.Model):
    """Borrador de factura / nota de cobro de un contrato para un mes. Los folios llegan en la etapa BSOFT."""
    class Estado(models.TextChoices):
        BORRADOR = 'B', 'Borrador'
        APROBADO = 'A', 'Aprobado'
        EXPORTADO = 'X', 'Exportado'
        ANULADO = 'N', 'Anulado'

    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name='documentos')
    periodo = models.DateField('mes facturado (día 1)')
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.BORRADOR)
    tipo_documento = models.CharField(max_length=2)
    valor_uf = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fecha_uf = models.DateField(null=True, blank=True)
    glosa = models.CharField(max_length=200, blank=True)
    neto = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    exento = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    iva = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    advertencias = models.JSONField(default=list, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    aprobado_por = models.CharField(max_length=80, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)
    folio = models.CharField('folio SII (etapa BSOFT)', max_length=20, blank=True)
    numero_interno = models.CharField('n.º interno', max_length=24, blank=True, db_index=True,
                                      help_text='Se asigna al aprobar: BT-F-0001 (factura) o BT-NC-0001 (nota de cobro). No se reutiliza.')

    class Meta:
        ordering = ['periodo', 'contrato__codigo']
        constraints = [models.UniqueConstraint(fields=['contrato', 'periodo'], condition=~models.Q(estado='N'),
                                               name='un_documento_vigente_por_contrato_y_mes')]

    def __str__(self):
        return f'{self.contrato.codigo} {self.periodo:%Y-%m} [{self.get_estado_display()}]'


class LineaDocumento(models.Model):
    class Origen(models.TextChoices):
        RENTA = 'RENTA', 'Renta'
        RENTA_DIF = 'RDIF', 'Diferencia renta variable'
        DESCUENTO = 'DESC', 'Descuento'
        ELECTRICIDAD = 'ELEC', 'Energía eléctrica'
        GAS = 'GAS', 'Gas'
        AGUA = 'AGUA', 'Agua'
        GASTOS_COMUNES = 'GGCC', 'Gastos comunes'
        OTRO = 'OTRO', 'Otro'

    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name='lineas')
    orden = models.PositiveSmallIntegerField()
    origen = models.CharField(max_length=5, choices=Origen.choices)
    concepto = models.CharField(max_length=80)
    detalle = models.TextField(blank=True, help_text='De dónde sale el monto (auditable)')
    unidad = models.CharField(max_length=3)
    cantidad_unidad = models.DecimalField('monto en UF o pesos antes de convertir', max_digits=16, decimal_places=4)
    valor_uf = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    neto = models.DecimalField(max_digits=14, decimal_places=0)
    exento = models.BooleanField(default=False)

    class Meta:
        ordering = ['documento', 'orden']


class CodigoServicioBsoft(models.Model):
    """Código de servicio de BSOFT (<CodServicio>) que corresponde a cada tipo de línea, por sociedad."""
    sociedad = models.ForeignKey('maestro.Sociedad', on_delete=models.CASCADE, related_name='codigos_bsoft')
    origen = models.CharField(max_length=5, choices=LineaDocumento.Origen.choices)
    codigo = models.CharField(max_length=10)
    nota = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = [('sociedad', 'origen')]
        verbose_name = 'código de servicio BSOFT'
        verbose_name_plural = 'códigos de servicio BSOFT'

    def __str__(self):
        return f'{self.sociedad.nombre} · {self.get_origen_display()} → {self.codigo}'


class Correlativo(models.Model):
    """Último número interno usado por sociedad y serie (F = facturas, NC = notas de cobro)."""
    sociedad = models.ForeignKey('maestro.Sociedad', on_delete=models.CASCADE, related_name='correlativos')
    serie = models.CharField(max_length=3)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [('sociedad', 'serie')]


class FacturaEmitida(models.Model):
    """Factura emitida por BSOFT en el SII, leída desde su PDF y vinculada (si calza) con el documento del sistema."""
    class Estado(models.TextChoices):
        VINCULADA = 'V', 'Vinculada'
        MANUAL = 'M', 'Vinculada a mano'
        DUDOSA = 'D', 'Revisar: el RUT calza pero el monto no'
        SIN = 'S', 'Sin documento del sistema'
        ILEGIBLE = 'I', 'No se pudo leer'

    sociedad = models.ForeignKey('maestro.Sociedad', on_delete=models.PROTECT, related_name='facturas_emitidas')
    ruta = models.CharField(max_length=700)
    nombre = models.CharField(max_length=255)
    pagina = models.PositiveSmallIntegerField(default=1, help_text='primera página de la factura dentro del PDF')
    tamano = models.BigIntegerField(default=0)
    modificado = models.DateTimeField(null=True, blank=True)
    tipo_dte = models.CharField(max_length=3, blank=True, help_text='33 afecta, 34 exenta, 61 nota de crédito')
    folio = models.CharField(max_length=20, blank=True)
    rut_receptor = models.CharField(max_length=15, blank=True)
    fecha_emision = models.DateField(null=True, blank=True)
    neto = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    exento = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    iva = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    documento = models.OneToOneField(Documento, null=True, blank=True, on_delete=models.SET_NULL, related_name='emitida')
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.SIN)
    nota = models.CharField(max_length=300, blank=True)
    leida_en = models.DateTimeField(auto_now=True)
    vinculada_por = models.CharField(max_length=80, blank=True)

    class Meta:
        unique_together = [('sociedad', 'ruta', 'pagina')]
        ordering = ['-fecha_emision', '-folio']
        verbose_name = 'factura emitida (BSOFT/SII)'
        verbose_name_plural = 'facturas emitidas (BSOFT/SII)'

    def __str__(self):
        return f'Folio {self.folio or "?"} · {self.rut_receptor} · ${self.total or 0}'


class CargaPlanilla(models.Model):
    """Planilla de luz o gas leída y esperando que alguien confirme a qué contrato va cada fila (con ayuda de la IA)."""
    class Estado(models.TextChoices):
        ASIGNANDO = 'P', 'La IA está asignando'
        REVISAR = 'L', 'Lista para revisar'
        CARGADA = 'C', 'Cargada'
        DESCARTADA = 'D', 'Descartada'

    sociedad = models.ForeignKey('maestro.Sociedad', on_delete=models.PROTECT, related_name='cargas_planilla')
    servicio = models.CharField(max_length=4)
    archivo = models.CharField(max_length=255)
    periodo_consumo = models.DateField()
    periodo_cobro = models.DateField()
    filas = models.JSONField(default=list)   # filas leídas de la planilla + contrato propuesto, confianza y motivo
    estado = models.CharField(max_length=1, choices=Estado.choices, default=Estado.REVISAR)
    error_ia = models.TextField(blank=True)
    costo_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    subida_por = models.CharField(max_length=80, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    resultado = models.TextField(blank=True)

    class Meta:
        ordering = ['-creada']


class FechaUFMes(models.Model):
    """Fecha de la UF elegida a mano para una sociedad y mes (por defecto se usa el día 1, o el primer día hábil si el contrato lo dice).
    Se aplica a todos los contratos de la sociedad ese mes (decisión del propietario, 14-10-2026)."""
    sociedad = models.ForeignKey('maestro.Sociedad', on_delete=models.CASCADE, related_name='fechas_uf')
    periodo = models.DateField('mes facturado (día 1)')
    fecha = models.DateField('fecha de la UF')
    usuario = models.CharField(max_length=80, blank=True)
    cambiado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('sociedad', 'periodo')]
        verbose_name = 'fecha de la UF del mes'
        verbose_name_plural = 'fechas de la UF elegidas por mes'

    def __str__(self):
        return f'{self.sociedad.nombre} {self.periodo:%m/%Y}: UF del {self.fecha:%d-%m-%Y}'
