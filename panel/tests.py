import os
import tempfile
from datetime import date
from decimal import Decimal as D

import openpyxl
from django.contrib.auth.models import Group, User
from django.test import TestCase

from facturacion.models import CargaPlanilla, CodigoServicioBsoft, ConsumoServicio, Documento, MedidorServicio, VentaMensual
from facturacion.tests import _planilla_luz
from indicadores.models import UF
from maestro.models import Arrendatario, Contrato, Propiedad, Sociedad, TramoRenta


class PanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for r in ('Administrador', 'Operación', 'Contabilidad'):
            Group.objects.create(name=r)
        cls.admin = User.objects.create_superuser('admin', password='x')
        cls.op = User.objects.create_user('op', password='x')
        cls.op.groups.add(Group.objects.get(name='Operación'))
        cls.cont = User.objects.create_user('cont', password='x')
        cls.cont.groups.add(Group.objects.get(name='Contabilidad'))
        cls.soc = Sociedad.objects.create(nombre='Inmobiliaria Prueba SpA', rut='76.000.000-0')
        prop = Propiedad.objects.create(sociedad=cls.soc, codigo='prueba', nombre='Centro Prueba', nombre_glosa='Centro Prueba Talca')
        arr = Arrendatario.objects.create(razon_social='Ale SpA', rut='11.111.111-1')
        cls.c1 = Contrato.objects.create(codigo='P-01', propiedad=prop, sociedad=cls.soc, arrendatario=arr, nombre_fantasia='Ale',
                                         inicio_vigencia=date(2025, 1, 1))
        TramoRenta.objects.create(contrato=cls.c1, desde=date(2025, 1, 1), monto=D('27'), unidad='UF')
        cls.c2 = Contrato.objects.create(codigo='P-02', propiedad=prop, sociedad=cls.soc, arrendatario=arr, nombre_fantasia='Variable',
                                         inicio_vigencia=date(2025, 1, 1), tipo_renta='MINVAR', pct_variable=D('0.02'), base_variable='V')
        TramoRenta.objects.create(contrato=cls.c2, desde=date(2025, 1, 1), monto=D('100'), unidad='UF')
        UF.objects.create(fecha=date(2026, 10, 1), valor=D('41065.38'))
        UF.objects.create(fecha=date(2026, 9, 1), valor=D('40875.09'))
        cls.med = MedidorServicio.objects.create(contrato=cls.c1, servicio='ELEC', etiqueta_local='Local 1B', nombre_planilla='Ale Cosmeticos')

    def entrar(self, user='op'):
        self.client.login(username=user, password='x')

    Q = '?sociedad={}&periodo=2026-10'

    def test_requiere_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r['Location'])

    def test_paginas_cargan(self):
        self.entrar()
        q = self.Q.format(self.soc.id)
        for url in ('/', '/facturacion/', '/cargas/', '/contratos/', '/alertas/', '/medidores/', '/indicadores/'):
            r = self.client.get(url + q)
            self.assertEqual(r.status_code, 200, url)
        self.assertContains(self.client.get('/contratos/P-01/' + q), 'Calendario de renta')
        self.assertEqual(self.client.get('/manifest.webmanifest').json()['short_name'], 'Facturación')
        self.assertIn('serviceWorker'.lower(), self.client.get('/').content.decode().lower())

    def test_flujo_generar_aprobar_exportar(self):
        self.entrar()
        r = self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'}, follow=True)
        self.assertContains(r, 'Se generaron 2 borradores')
        self.assertEqual(Documento.objects.count(), 2)
        d1 = Documento.objects.get(contrato=self.c1)
        self.assertEqual(d1.neto, 1108765)
        # el variable queda con advertencia (faltan ventas) → no se aprueba en bloque
        self.client.post('/facturacion/aprobar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        self.assertEqual(Documento.objects.get(contrato=self.c1).estado, 'A')
        d2 = Documento.objects.get(contrato=self.c2)
        self.assertEqual(d2.estado, 'B')
        # un operador no puede forzar
        self.client.post(f'/documento/{d2.pk}/accion/', {'accion': 'aprobar', 'forzar': '1'})
        self.assertEqual(Documento.objects.get(pk=d2.pk).estado, 'B')
        # ingresar ventas y regenerar
        self.client.post('/cargas/venta/', {'sociedad': self.soc.id, 'periodo': '2026-10', 'contrato': 'P-02', 'mes_ventas': '2026-09', 'monto': '900.000.000'})
        self.assertEqual(VentaMensual.objects.get().monto_neto, 900000000)
        self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        d2 = Documento.objects.get(contrato=self.c2)
        self.assertEqual([l.origen for l in d2.lineas.all()], ['RENTA', 'RDIF'])
        self.client.post(f'/documento/{d2.pk}/accion/', {'accion': 'aprobar'})
        self.assertEqual(Documento.objects.get(pk=d2.pk).estado, 'A')
        # Excel de revisión
        r = self.client.get('/facturacion/excel/' + self.Q.format(self.soc.id))
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        # XML sin códigos BSOFT: avisa y no marca como exportado
        r = self.client.get('/facturacion/xml/' + self.Q.format(self.soc.id), follow=True)
        self.assertContains(r, 'Faltan los códigos de servicio BSOFT')
        self.assertEqual(Documento.objects.filter(estado='X').count(), 0)
        CodigoServicioBsoft.objects.create(sociedad=self.soc, origen='RENTA', codigo='1002')
        CodigoServicioBsoft.objects.create(sociedad=self.soc, origen='RDIF', codigo='1003')
        r = self.client.get('/facturacion/xml/' + self.Q.format(self.soc.id))
        self.assertEqual(r['Content-Type'], 'application/zip')
        self.assertEqual(Documento.objects.filter(estado='X').count(), 2)

    def test_administrador_puede_forzar(self):
        self.entrar('admin')
        self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        d2 = Documento.objects.get(contrato=self.c2)
        self.client.post(f'/documento/{d2.pk}/accion/', {'accion': 'aprobar', 'forzar': '1'})
        self.assertEqual(Documento.objects.get(pk=d2.pk).estado, 'A')

    def test_contabilidad_solo_lee(self):
        self.entrar('cont')
        self.assertEqual(self.client.get('/facturacion/' + self.Q.format(self.soc.id)).status_code, 200)
        r = self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Documento.objects.count(), 0)

    def test_sin_uf_no_rompe(self):
        self.entrar()
        r = self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2027-03'}, follow=True)
        self.assertEqual(r.status_code, 200)

    def test_carga_de_luz_desde_la_web_y_medidor(self):
        self.entrar()
        with tempfile.TemporaryDirectory() as t:
            ruta = os.path.join(t, 'luz.xlsx')
            _planilla_luz(ruta)
            with open(ruta, 'rb') as f:
                r = self.client.post('/cargas/archivo/', {'tipo': 'electricidad', 'archivo': f, 'consumo': '2026-09', 'cobro': '2026-10',
                                                          'sociedad': self.soc.id, 'periodo': '2026-10'}, follow=True)
        # pantalla de revisión: la fila del medidor por confirmar viene propuesta; la otra está sin asignar
        self.assertContains(r, 'Revisar planilla de electricidad')
        self.assertContains(r, 'medidor por confirmar')
        self.assertContains(r, 'sin asignar')
        self.assertEqual(ConsumoServicio.objects.count(), 0)   # nada se carga sin confirmar
        carga = CargaPlanilla.objects.get()
        r = self.client.post(f'/cargas/planilla/{carga.pk}/', {'c_10': ''}, follow=True)
        self.assertContains(r, 'Faltan por asignar')
        r = self.client.post(f'/cargas/planilla/{carga.pk}/', {'c_9': 'P-01', 'c_10': 'NO'}, follow=True)
        self.assertContains(r, '1 cargos por $55.361')
        self.assertEqual(ConsumoServicio.objects.get().neto, 55361)
        self.med.refresh_from_db()
        self.assertTrue(self.med.confirmado)   # lo confirmado queda para los meses siguientes
        self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        d = Documento.objects.get(contrato=self.c1)
        self.assertEqual([l.origen for l in d.lineas.all()], ['RENTA', 'ELEC'])
        self.assertEqual(d.advertencias, [])

    def test_cargar_luz_despues_de_aprobar_avisa_y_se_puede_rehacer(self):
        """Caso real: se aprobó el mes antes de cargar luz/gas; el sistema debe avisar y permitir volver a borrador."""
        self.entrar()
        self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        self.client.post('/facturacion/aprobar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        self.assertEqual(Documento.objects.get(contrato=self.c1).estado, 'A')
        r = self.client.get(f'/facturacion/?sociedad={self.soc.id}&periodo=2026-10')
        self.assertContains(r, 'Aún no hay <b>electricidad</b>')
        with tempfile.TemporaryDirectory() as t:
            ruta = os.path.join(t, 'luz.xlsx')
            _planilla_luz(ruta)
            with open(ruta, 'rb') as f:
                self.client.post('/cargas/archivo/', {'tipo': 'electricidad', 'archivo': f, 'consumo': '2026-09', 'cobro': '2026-10',
                                                      'sociedad': self.soc.id, 'periodo': '2026-10'})
        r = self.client.post(f'/cargas/planilla/{CargaPlanilla.objects.get().pk}/', {'c_9': 'P-01', 'c_10': 'NO'}, follow=True)
        self.assertContains(r, 'ya estaban aprobados')
        r = self.client.get(f'/facturacion/?sociedad={self.soc.id}&periodo=2026-10')
        self.assertContains(r, 'no incluyen todos los cargos')
        r = self.client.post('/facturacion/volver/', {'sociedad': self.soc.id, 'periodo': '2026-10'}, follow=True)
        self.assertContains(r, 'volvieron a borrador')
        self.client.post('/facturacion/generar/', {'sociedad': self.soc.id, 'periodo': '2026-10'})
        d = Documento.objects.get(contrato=self.c1)
        self.assertEqual([l.origen for l in d.lineas.all()], ['RENTA', 'ELEC'])
        r = self.client.get(f'/facturacion/?sociedad={self.soc.id}&periodo=2026-10')
        self.assertNotContains(r, 'no incluyen todos los cargos')

    def test_archivo_invalido_se_informa(self):
        self.entrar()
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.client.post('/cargas/archivo/', {'tipo': 'gas', 'consumo': '2026-09', 'sociedad': self.soc.id, 'periodo': '2026-10',
                                                  'archivo': SimpleUploadedFile('x.xlsx', b'no es un excel')}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No se pudo')

    def test_simulacion_de_contrato(self):
        self.entrar()
        r = self.client.get('/contratos/P-01/?sim=2026-10')
        self.assertContains(r, '1.108.765')
        self.assertEqual(Documento.objects.count(), 0)  # simular no guarda nada
