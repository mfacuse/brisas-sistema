from django.conf import settings
from django.db import models


class SegundoFactor(models.Model):
    """Verificación en dos pasos: clave secreta de la app de códigos (Google Authenticator, Microsoft Authenticator…)."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='segundo_factor')
    secreto = models.CharField(max_length=64)
    activo = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    ultimo_paso = models.BigIntegerField(default=0, help_text='último código usado (no se puede reutilizar)')

    class Meta:
        verbose_name = 'verificación en dos pasos'
        verbose_name_plural = 'verificaciones en dos pasos (borrar = el usuario la configura de nuevo)'

    def __str__(self):
        return f'{self.usuario} · {"activa" if self.activo else "sin confirmar"}'


class IntentoIngreso(models.Model):
    """Registro de ingresos (para bloquear tras varios intentos fallidos y para auditoría)."""
    usuario = models.CharField(max_length=150)
    ip = models.CharField(max_length=45, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    exito = models.BooleanField(default=False)
    paso = models.CharField(max_length=10, default='clave')   # clave | codigo

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'intento de ingreso'
        verbose_name_plural = 'intentos de ingreso'
