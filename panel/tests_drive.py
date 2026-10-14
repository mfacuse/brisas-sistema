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
        self.assertEqual(almacen.cliente_oauth()['client_id'], '123-abc.apps.googleusercontent.com')
        r = self.client.post('/configuracion/drive/conectar/')
        url = urlparse(r['Location'])
        q = parse_qs(url.query)
        self.assertEqual(url.netloc, 'accounts.google.com')
        self.assertIn('drive.readonly', q['scope'][0])
        self.assertIn('drive.file', q['scope'][0])   # permiso acotado para los respaldos
        self.assertEqual(q['access_type'], ['offline'])
        # un regreso con otro «state» se rechaza
        self.client.get('/configuracion/drive/volver/', {'state': 'otro', 'code': 'x'})
        self.assertFalse(almacen.drive_configurado())
        self.client.post('/configuracion/drive/conectar/')
        estado = self.client.session['drive_estado']
        carga = base64.urlsafe_b64encode(json.dumps({'email': 'mfacuse@invercochile.com'}).encode()).decode().rstrip('=')
        alc = 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.file openid'
        with mock.patch.object(vistas_drive, '_post', return_value={'refresh_token': 'rt', 'id_token': f'a.{carga}.b', 'scope': alc}) as post:
            r = self.client.get('/configuracion/drive/volver/', {'state': estado, 'code': 'codigo'}, follow=True)
        self.assertEqual(post.call_args[0][1]['grant_type'], 'authorization_code')
        self.assertContains(r, 'conectado con mfacuse@invercochile.com')
        self.assertTrue(almacen.drive_configurado())
        self.assertTrue(almacen.puede_respaldar())
        with mock.patch.object(vistas_drive, '_post', return_value={}):
            self.client.post('/configuracion/drive/desconectar/')
        self.assertFalse(almacen.drive_configurado())

    def test_solo_administradores(self):
        u = User.objects.create_user('op', password='x')
        self.client.force_login(u)
        self.assertEqual(self.client.post('/configuracion/drive/conectar/').status_code, 403)

    def test_desde_127_0_0_1_lleva_a_localhost(self):
        almacen.guardar_cliente({'client_id': '1-a.apps.googleusercontent.com', 'client_secret': 's'})
        r = self.client.post('/configuracion/drive/conectar/', HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(r['Location'], 'http://localhost:8000/configuracion/?drive=localhost')



class RespaldoTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', password='x')
        self.client.force_login(self.admin)

    def test_respaldo_en_drive_conserva_60_y_se_puede_restaurar(self):
        import gzip
        from maestro import respaldos
        from maestro.models import Sociedad
        Sociedad.objects.create(nombre='Soc Respaldo', rut='9-9', sigla='SR')
        almacen.guardar_cliente({'client_id': 'x.apps.googleusercontent.com', 'client_secret': 's'})
        almacen.guardar_token({'refresh_token': 'rt', 'alcances': almacen.ALCANCE + ' ' + almacen.ALCANCE_RESPALDOS})
        subidos, borrados = [], []
        viejos = [{'id': f'v{i}', 'name': f'brisas_2026-01-{i:02d}.json.gz'} for i in range(1, 63)]
        with mock.patch.object(almacen, 'carpeta_respaldos', return_value='car'), \
                mock.patch.object(almacen, 'subir', side_effect=lambda c, n, b: subidos.append((c, n, b))), \
                mock.patch.object(almacen, 'archivos_de', return_value=viejos), \
                mock.patch.object(almacen, 'borrar', side_effect=borrados.append):
            r = self.client.post('/configuracion/respaldar/', follow=True)
        self.assertContains(r, 'guardado en Google Drive')
        carpeta, nombre, contenido = subidos[0]
        self.assertTrue(nombre.startswith('brisas_') and nombre.endswith('.json.gz'))
        self.assertEqual(len(borrados), 2)   # quedan 60
        self.assertIn(b'Soc Respaldo', gzip.decompress(contenido))
        self.assertEqual(respaldos.ultimo()['nombre'], nombre)
        self.assertContains(self.client.get('/configuracion/'), nombre)

    def test_sin_permiso_de_escritura_avisa(self):
        almacen.guardar_cliente({'client_id': 'x.apps.googleusercontent.com', 'client_secret': 's'})
        almacen.guardar_token({'refresh_token': 'rt', 'alcances': almacen.ALCANCE})   # conexión antigua: solo lectura
        r = self.client.post('/configuracion/respaldar/', follow=True)
        self.assertContains(r, 'Volver a conectar Google Drive')


class BorrarFacturacionTest(TestCase):
    def test_borra_solo_con_confirmacion_y_respaldo(self):
        from unittest import mock
        from django.contrib.auth.models import User
        from facturacion.models import CargaPlanilla
        from datetime import date
        from maestro.models import Sociedad
        soc = Sociedad.objects.create(nombre='S', rut='76.000.000-0', sigla='S')
        CargaPlanilla.objects.create(sociedad=soc, servicio='AGUA', archivo='a.xlsx', periodo_consumo=date(2026, 9, 1), periodo_cobro=date(2026, 10, 1))
        u = User.objects.create_superuser('jefe', password='x')
        self.client.force_login(u)
        with mock.patch('maestro.respaldos.respaldar', return_value={'nombre': 'r.json.gz', 'kb': 1}) as resp:
            self.client.post('/configuracion/borrar-facturacion/', {'confirmar': 'no'})
            resp.assert_not_called()
            self.client.post('/configuracion/borrar-facturacion/', {'confirmar': 'BORRAR'})
            resp.assert_called_once()
        self.assertFalse(CargaPlanilla.objects.exists())
        with mock.patch('maestro.respaldos.respaldar', side_effect=RuntimeError('sin Drive')), \
             mock.patch('facturacion.limpieza.borrar_facturacion') as borrar:
            self.client.post('/configuracion/borrar-facturacion/', {'confirmar': 'BORRAR'})
            borrar.assert_not_called()   # sin respaldo no se borra
