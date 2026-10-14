from django.db import models


class UF(models.Model):
    fecha = models.DateField(primary_key=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    origen = models.CharField(max_length=8, default='API', help_text='BCCH (Banco Central), SII, API (mindicador.cl, antiguo), MANUAL o PRUEBA (datos ficticios)')

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.fecha}: {self.valor}'


class IPC(models.Model):
    """Variación mensual del IPC (en %). El IPC de un mes se publica a comienzos del mes siguiente."""
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    variacion_pct = models.DecimalField(max_digits=6, decimal_places=2)
    origen = models.CharField(max_length=8, default='API', help_text='BCCH (Banco Central), SII, API (mindicador.cl, antiguo) o PRUEBA')

    class Meta:
        unique_together = [('anio', 'mes')]
        ordering = ['-anio', '-mes']

    def __str__(self):
        return f'{self.anio}-{self.mes:02d}: {self.variacion_pct}%'
