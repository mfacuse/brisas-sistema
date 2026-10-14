import pyotp
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from .models import IntentoIngreso, SegundoFactor


class BloqueoTest(TestCase):
    def setUp(self):
        User.objects.create_user('ana', password='clave-correcta-123')

    def test_cinco_fallas_bloquean_aunque_despues_ponga_la_clave_correcta(self):
        for _ in range(5):
            r = self.client.post('/login/', {'username': 'ana', 'password': 'mala'})
        self.assertContains(r, 'Demasiados intentos')
        r = self.client.post('/login/', {'username': 'ana', 'password': 'clave-correcta-123'})
        self.assertContains(r, 'Demasiados intentos')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_ingreso_normal_y_no_redirige_a_otros_sitios(self):
        r = self.client.post('/login/', {'username': 'ana', 'password': 'clave-correcta-123', 'next': 'https://malicioso.com/'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        self.assertTrue(IntentoIngreso.objects.filter(usuario='ana', exito=True).exists())


@override_settings(EXIGIR_2FA=True)
class SegundoFactorTest(TestCase):
    def setUp(self):
        self.u = User.objects.create_user('ana', password='clave-correcta-123')

    def test_primera_vez_obliga_a_configurar_y_luego_pide_el_codigo(self):
        r = self.client.post('/login/', {'username': 'ana', 'password': 'clave-correcta-123'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        r = self.client.get('/facturacion/')
        self.assertRedirects(r, '/cuenta/verificacion/', fetch_redirect_response=False)   # no puede usar el sistema sin configurarla
        r = self.client.get('/cuenta/verificacion/')
        self.assertContains(r, '<svg')
        sf = SegundoFactor.objects.get(usuario=self.u)
        self.client.post('/cuenta/verificacion/', {'codigo': '000000'})
        sf.refresh_from_db()
        self.assertFalse(sf.activo)
        self.client.post('/cuenta/verificacion/', {'codigo': pyotp.TOTP(sf.secreto).now()})
        sf.refresh_from_db()
        self.assertTrue(sf.activo)
        self.assertEqual(self.client.get('/facturacion/').status_code, 200)
        # siguiente ingreso: clave + código
        self.client.post('/salir/')
        r = self.client.post('/login/', {'username': 'ana', 'password': 'clave-correcta-123'})
        self.assertRedirects(r, '/login/codigo/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)   # con la clave sola todavía no entra
        r = self.client.post('/login/codigo/', {'codigo': '123456'})
        self.assertContains(r, 'Código incorrecto')
        sf.ultimo_paso = 0
        sf.save()
        codigo = pyotp.TOTP(sf.secreto).now()
        r = self.client.post('/login/codigo/', {'codigo': codigo})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        self.assertIn('_auth_user_id', self.client.session)
        # el mismo código no sirve dos veces
        self.client.post('/salir/')
        self.client.post('/login/', {'username': 'ana', 'password': 'clave-correcta-123'})
        r = self.client.post('/login/codigo/', {'codigo': codigo})
        self.assertContains(r, 'Código incorrecto')


class ImportarDatosTest(TestCase):
    def test_solo_en_base_vacia_y_solo_superusuario(self):
        import json
        from django.core.files.uploadedfile import SimpleUploadedFile
        from maestro.models import Sociedad
        u = User.objects.create_user('op', password='x')
        self.client.force_login(u)
        self.assertEqual(self.client.get('/configuracion/importar-datos/').status_code, 302)   # no es superusuario
        admin = User.objects.create_superuser('instalacion', password='x')
        self.client.force_login(admin)
        datos = [{'model': 'maestro.sociedad', 'pk': 50, 'fields': {'nombre': 'Soc Nube', 'rut': '1-9', 'giro': '', 'direccion': '', 'sigla': 'SN',
                  'carpeta_contratos': 'gdrive:abc', 'carpeta_facturas': '', 'carpeta_actas': '', 'datos_pago': ''}}]
        archivo = SimpleUploadedFile('brisas_nube.json', json.dumps(datos).encode(), content_type='application/json')
        self.client.post('/configuracion/importar-datos/', {'archivo': archivo})
        self.assertEqual(Sociedad.objects.get(pk=50).carpeta_contratos, 'gdrive:abc')
