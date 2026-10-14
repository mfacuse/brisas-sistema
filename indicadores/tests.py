import json
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase

from . import servicio
from .models import IPC, UF

# Recortes con el mismo formato que las páginas del SII (uf2026.htm y utm2026.htm)
UF_SII = """﻿<div class='meses' id='mes_noviembre'><table><tbody>
<tr><th colspan='6'><h2>Noviembre</h2></th></tr>
<tr><th width='40'><strong>1</strong></th><td width='200'>41.252,94</td>
<th width='40'><strong>11</strong></th><td width='200'></td></tr></tbody></table></div>
<div class='meses' id='mes_octubre'><table><tbody>
<tr><th width='40'><strong>1</strong></th><td width='200'>41.065,38</td>
<th width='40'><strong>31</strong></th><td width='200'>41.247,63</td></tr></tbody></table></div>
<div class='meses' id='mes_febrero'><table><tbody>
<tr><th width='40'><strong>29</strong></th><td width='200'></td></tr></tbody></table></div>"""

IPC_SII = """<table><thead><tr><th>2026</th><th>UTM (1)</th></tr></thead><tbody>
<tr>
  <th>Enero</th><td>69.751</td><td>837.012</td><td align='center'>109,71</td>
  <td align='center'>0,4</td><td align='center'>0,4</td><td align='center'>2,8</td>
</tr>
<tr>
  <th>Junio</th><td>71.506</td><td>858.072</td><td align='center'>112,35</td>
  <td align='center'>-0,2</td><td align='center'>2,8</td><td align='center'>4,3</td>
</tr>
<tr>
  <th>Octubre</th><td>72.151</td><td>865.812</td><td align='center'>&nbsp;</td>
  <td align='center'>&nbsp;</td><td align='center'>&nbsp;</td><td align='center'>&nbsp;</td>
</tr></tbody></table>"""


def bcch(obs, codigo=0):
    return json.dumps({'Codigo': codigo, 'Descripcion': 'Success' if codigo == 0 else 'Invalid username or password',
                       'Series': {'Obs': obs}})


class LecturaSIITest(TestCase):
    def test_uf_por_dia_y_mes(self):
        v = servicio.leer_uf_sii(UF_SII, 2026)
        self.assertEqual(v, {date(2026, 11, 1): D('41252.94'), date(2026, 10, 1): D('41065.38'), date(2026, 10, 31): D('41247.63')})

    def test_ipc_columna_mensual_con_negativos_y_meses_sin_publicar(self):
        v = servicio.leer_ipc_sii(IPC_SII, 2026)
        self.assertEqual(v, {(2026, 1): D('0.40'), (2026, 6): D('-0.20')})


class CargaTest(TestCase):
    def setUp(self):
        p = mock.patch.object(servicio, 'token_bcentral', return_value=None)
        self.token = p.start()
        self.addCleanup(p.stop)

    def test_sin_token_usa_sii_y_reemplaza_valores_de_prueba(self):
        UF.objects.create(fecha=date(2026, 11, 1), valor=D('40000'), origen='PRUEBA')
        IPC.objects.create(anio=2026, mes=1, variacion_pct=D('0.30'), origen='PRUEBA')
        IPC.objects.create(anio=2026, mes=12, variacion_pct=D('0.30'), origen='PRUEBA')
        with mock.patch.object(servicio, '_get', side_effect=lambda url: UF_SII if '/uf/' in url else IPC_SII):
            c = servicio.cargar_uf_anio(2026)
            self.assertEqual((c.fuente, c.total, c.nuevos), ('SII', 3, 3))
            servicio.cargar_ipc_anio(2026)
        self.assertEqual((UF.objects.get(fecha=date(2026, 11, 1)).valor, UF.objects.get(fecha=date(2026, 11, 1)).origen), (D('41252.94'), 'SII'))
        self.assertEqual(servicio.variacion_ipc(2026, 1), D('0.40'))
        self.assertEqual(IPC.objects.get(anio=2026, mes=1).origen, 'SII')
        self.assertEqual(IPC.objects.get(anio=2026, mes=12).origen, 'PRUEBA')   # diciembre aún no se publica: queda el de prueba

    def test_segunda_carga_no_reescribe_nada(self):
        with mock.patch.object(servicio, '_get', return_value=UF_SII):
            servicio.cargar_uf_anio(2026)
            self.assertEqual(servicio.cargar_uf_anio(2026).nuevos, 0)

    def test_con_token_usa_banco_central(self):
        self.token.return_value = 'abc'
        obs = [{'indexDateString': '01-10-2026', 'value': '41065.38', 'statusCode': 'OK'},
               {'indexDateString': '02-10-2026', 'value': 'NaN', 'statusCode': 'ND'}]
        with mock.patch.object(servicio, '_get', return_value=bcch(obs)) as g:
            c = servicio.cargar_uf_anio(2026)
        self.assertIn('token=abc', g.call_args[0][0])
        self.assertEqual((c.fuente, c.total), ('Banco Central', 1))
        self.assertEqual(UF.objects.get(fecha=date(2026, 10, 1)).origen, 'BCCH')

    def test_si_banco_central_falla_usa_sii(self):
        self.token.return_value = 'malo'
        with mock.patch.object(servicio, '_get', side_effect=lambda url: bcch(None, -5) if 'bcentral' in url else IPC_SII):
            c = servicio.cargar_ipc_anio(2026)
        self.assertEqual(c.fuente, 'SII')
        self.assertEqual(IPC.objects.get(anio=2026, mes=6).variacion_pct, D('-0.20'))

    def test_año_no_publicado_y_sin_red(self):
        with mock.patch.object(servicio, '_get', side_effect=servicio.AunNoPublicado('404')):
            with self.assertRaises(servicio.AunNoPublicado):
                servicio.cargar_uf_anio(2027)
        with mock.patch.object(servicio, '_get', side_effect=OSError('sin red')):
            with self.assertRaisesMessage(RuntimeError, 'SII: sin red'):
                servicio.cargar_uf_anio(2026)
        self.assertFalse(UF.objects.exists())

    def test_años_por_defecto(self):
        self.assertEqual(servicio.años_por_defecto(date(2026, 10, 13)), [2026])
        self.assertEqual(servicio.años_por_defecto(date(2027, 1, 5)), [2026, 2027])
        self.assertEqual(servicio.años_por_defecto(date(2026, 12, 20)), [2026, 2027])
