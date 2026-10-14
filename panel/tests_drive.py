import base64
import json
import os
import tempfile
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from maestro import almacen

from . import vistas_drive


class ConexionDriveTest(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='brisas_secretos_')
        o = override_settings(SECRETOS_DIR=self.dir)
        o.enable()
        self.addCleanup(o.disable)
        almacen.olvidar_conexion()
        self.admin = User.objects.create_superuser('admin', password='x')
        self.client.force_login(self.admin)

    def test_conectar_y_desconectar(self):
        self.assertFalse(almacen.drive_configurado())
        self.client.post('/configuracion/drive/cliente/', {'client_id': 'malo', 'client_secret': 's'})
        self.assertEqual(almacen.cliente_oauth(), {})
        self.client.post('/configuracion/drive/cliente/', {'client_id': '123-abc.apps.googleusercontent.com', 'client_secret': 'secreto'})
        self.assertEqual(oct(os.stat(almacen._ruta_cliente()).st_mode & 0o777), '0o600')
        r = self.client.post('/configuracion/drive/conectar/')
        url = urlparse(r['Location'])
        q = parse_qs(url.query)
        self.assertEqual(url.netloc, 'accounts.google.com')
        self.assertIn('drive.readonly', q['scope'][0])
        self.assertEqual(q['access_type'], ['offline'])
        # un regreso con otro «state» se rechaza
        self.client.get('/configuracion/drive/volver/', {'state': 'otro', 'code': 'x'})
        self.assertFalse(almacen.drive_configurado())
        self.client.post('/configuracion/drive/conectar/')
        estado = self.client.session['drive_estado']
        carga = base64.urlsafe_b64encode(json.dumps({'email': 'mfacuse@invercochile.com'}).encode()).decode().rstrip('=')
        with mock.patch.object(vistas_drive, '_post', return_value={'refresh_token': 'rt', 'id_token': f'a.{carga}.b'}) as post:
            r = self.client.get('/configuracion/drive/volver/', {'state': estado, 'code': 'codigo'}, follow=True)
        self.assertEqual(post.call_args[0][1]['grant_type'], 'authorization_code')
        self.assertContains(r, 'conectado con mfacuse@invercochile.com')
        self.assertTrue(almacen.drive_configurado())
        self.assertEqual(oct(os.stat(almacen._ruta_token()).st_mode & 0o777), '0o600')
        with mock.patch.object(vistas_drive, '_post', return_value={}):
            self.client.post('/configuracion/drive/desconectar/')
        self.assertFalse(almacen.drive_configurado())

    def test_solo_administradores(self):
        u = User.objects.create_user('op', password='x')
        self.client.force_login(u)
        self.assertEqual(self.client.post('/configuracion/drive/conectar/').status_code, 403)

    def test_desde_127_0_0_1_lleva_a_localhost(self):
        almacen.guardar_privado(almacen._ruta_cliente(), {'client_id': '1-a.apps.googleusercontent.com', 'client_secret': 's'})
        r = self.client.post('/configuracion/drive/conectar/', HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(r['Location'], 'http://localhost:8000/configuracion/?drive=localhost')
