import json
import os
import shutil
import tempfile
import time
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from . import carpetas, historial, ia
from .models import (ArchivoContrato, Arrendatario, Contrato, EventoArchivo, PropuestaIA, Propiedad, RegistroCambio, Sociedad,
                     TramoRenta)


def _pdf(ruta: Path, texto='contrato'):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b'%PDF-1.4\n% ' + texto.encode() + b'\n%%EOF\n')


class Base(TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix='brisas_carpetas_')).resolve()
        self.addCleanup(shutil.rmtree, self.raiz, ignore_errors=True)
        o = override_settings(CARPETAS_RAIZ=[self.raiz])
        o.enable()
        self.addCleanup(o.disable)
        self.carpeta = self.raiz / 'Contratos Vigentes'
        self.carpeta.mkdir()
        self.soc = Sociedad.objects.create(nombre='Inmobiliaria Prueba SpA', rut='76.000.000-0', sigla='IP', carpeta_contratos=str(self.carpeta))
        self.prop = Propiedad.objects.create(sociedad=self.soc, codigo='prueba', nombre='Centro Prueba')
        self.arr = Arrendatario.objects.create(razon_social='Ale SpA', rut='11.111.111-1')
        self.c1 = Contrato.objects.create(codigo='P-01', propiedad=self.prop, sociedad=self.soc, arrendatario=self.arr, nombre_fantasia='Ale',
                                          inicio_vigencia=date(2025, 1, 1),
                                          documentos_fuente='Contrato Local 1 Ale.pdf; …Ale Anexo.pdf; …Ale (Cesión).pdf y (Cesión) 2.pdf (duplicados)')
        TramoRenta.objects.create(contrato=self.c1, desde=date(2025, 1, 1), monto=D('27'), unidad='UF')


class CarpetasTest(Base):
    def test_nombres_de_fuente(self):
        completos, sufijos = carpetas._fuentes(self.c1.documentos_fuente)
        self.assertEqual(completos, ['contrato local 1 ale.pdf'])
        self.assertEqual(sufijos, ['ale anexo.pdf', 'ale (cesión).pdf', '(cesión) 2.pdf'])

    def test_primera_revision_asocia_por_nombre_y_avisa_lo_desconocido(self):
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf')
        _pdf(self.carpeta / 'Contrato Local 1 Ale Anexo.pdf')
        _pdf(self.carpeta / 'Contrato Local 9 Nuevo.pdf')
        _pdf(self.carpeta / 'notas.txt')
        r = carpetas.revisar(self.soc)
        self.assertEqual(r.total, 3)
        self.assertEqual([a.nombre for a in r.nuevos], ['Contrato Local 9 Nuevo.pdf'])
        a = ArchivoContrato.objects.get(nombre='Contrato Local 1 Ale Anexo.pdf')
        self.assertEqual((a.contrato, a.estado), (self.c1, 'R'))
        # una segunda revisión sin cambios no avisa nada
        r = carpetas.revisar(self.soc)
        self.assertEqual((r.nuevos, r.cambiados, r.eliminados), ([], [], []))

    def test_detecta_cambios_movidos_eliminados_y_reaparecidos(self):
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf')
        _pdf(self.carpeta / 'Otro.pdf')
        carpetas.revisar(self.soc)
        # cambia el contenido (otro tamaño y fecha)
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf', 'contrato firmado con anexo')
        os.utime(self.carpeta / 'Contrato Local 1 Ale.pdf', (time.time() + 60, time.time() + 60))
        # se mueve a una subcarpeta y otro se borra
        (self.carpeta / 'Antiguos').mkdir()
        shutil.move(self.carpeta / 'Otro.pdf', self.carpeta / 'Antiguos' / 'Otro.pdf')
        r = carpetas.revisar(self.soc)
        self.assertEqual([a.nombre for a in r.cambiados], ['Contrato Local 1 Ale.pdf'])
        self.assertEqual([a.nombre for a in r.movidos], ['Otro.pdf'])
        self.assertEqual(ArchivoContrato.objects.get(nombre='Contrato Local 1 Ale.pdf').estado, 'C')
        os.remove(self.carpeta / 'Antiguos' / 'Otro.pdf')
        r = carpetas.revisar(self.soc)
        self.assertEqual([a.nombre for a in r.eliminados], ['Otro.pdf'])
        _pdf(self.carpeta / 'Antiguos' / 'Otro.pdf')
        r = carpetas.revisar(self.soc)
        self.assertEqual([a.nombre for a in r.cambiados], ['Otro.pdf'])
        tipos = list(EventoArchivo.objects.filter(archivo__nombre='Otro.pdf').order_by('id').values_list('tipo', flat=True))
        self.assertEqual(tipos, ['NUEVO', 'MOVIDO', 'ELIMINADO', 'REAPARECIDO'])

    def test_carpeta_inexistente_no_marca_eliminados(self):
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf')
        carpetas.revisar(self.soc)
        self.soc.carpeta_contratos = str(self.raiz / 'no existe')
        r = carpetas.revisar(self.soc)
        self.assertIn('no se encuentra', r.error)
        self.assertFalse(ArchivoContrato.objects.filter(estado='E').exists())

    def test_solo_carpetas_permitidas(self):
        with self.assertRaises(carpetas.CarpetaNoPermitida):
            carpetas.validar('/etc')
        with self.assertRaises(carpetas.CarpetaNoPermitida):
            carpetas.validar(str(self.carpeta / '..' / '..'))
        self.assertEqual(carpetas.validar(str(self.carpeta)), str(self.carpeta))


class HistorialTest(Base):
    def test_registra_quien_cuando_y_que_cambio(self):
        with historial.con_origen('panel', 'matias'):
            self.c1.tipo_documento = 'NC'
            self.c1.aviso_dias = 60
            self.c1.save()
            TramoRenta.objects.create(contrato=self.c1, desde=date(2026, 1, 1), monto=D('30'), unidad='UF')
        r = RegistroCambio.objects.filter(contrato=self.c1, objeto='Contrato', accion='modificado').get()
        self.assertEqual((r.usuario, r.origen), ('matias', 'panel'))
        self.assertEqual(r.cambios['tipo documento'], ['FA', 'NC'])
        self.assertEqual(r.cambios['aviso de no renovación (días)'], ['', '60'])
        t = RegistroCambio.objects.filter(contrato=self.c1, objeto='Tramo de renta', accion='creado').first()
        self.assertEqual(t.cambios['monto'], ['', '30'])
        # guardar sin cambios no deja registro
        n = RegistroCambio.objects.count()
        self.c1.save()
        self.assertEqual(RegistroCambio.objects.count(), n)

    def test_cambio_de_carpeta_queda_registrado(self):
        self.soc.carpeta_contratos = str(self.raiz)
        self.soc.save()
        r = RegistroCambio.objects.filter(objeto='Sociedad').first()
        self.assertEqual(r.cambios['carpeta de contratos'], [str(self.carpeta), str(self.raiz)])


# ------------------------------------------------------------------ IA (con un cliente falso: no se llama a Anthropic)
RESPUESTA = {
    'tipo_documento_fuente': 'anexo', 'resumen': 'Anexo que sube la renta y pasa el cobro a nota de cobro.', 'contrato_existente_codigo': 'P-01',
    'arrendatario_razon_social': 'Ale SpA', 'arrendatario_rut': '11.111.111-1', 'representante': '', 'nombre_fantasia': '', 'locales': 'Local 1',
    'direccion_contrato': '', 'fecha_contrato': '2026-09-01', 'inicio_vigencia': '', 'plazo_meses': '', 'fin_pactado': '', 'prorroga_meses': '',
    'aviso_dias': '90', 'fecha_termino_real': '', 'tipo_documento': 'NC', 'tipo_documento_motivo': 'cláusula 5: sin factura',
    'regla_uf': '', 'tipo_renta': '', 'pct_variable': '', 'base_variable': '', 'periodicidad': '', 'meses_cobro': '', 'reajuste_ipc': '',
    'm2_contrato': '', 'garantia_uf': '', 'garantia_clp': '', 'gastos_comunes': '', 'condiciones': '',
    'tramos': [{'desde': '2025-01-01', 'hasta': '2026-08-31', 'monto': '27', 'unidad': 'UF', 'tipo': 'fija', 'nota': ''},
               {'desde': '2026-09-01', 'hasta': '', 'monto': '30.5', 'unidad': 'UF', 'tipo': 'fija', 'nota': 'anexo'}],
    'dudas': ['La fecha de firma no es legible.'], 'evidencia': [{'campo': 'renta', 'pagina': '2', 'cita': '30,5 UF'}],
}


class ClienteFalso:
    def __init__(self, datos=RESPUESTA, stop='end_turn', error=None):
        self.datos, self.stop, self.error, self.llamadas = datos, stop, error, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error
        msg = SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type='text', text=json.dumps(self.datos))],
                              usage=SimpleNamespace(input_tokens=50_000, output_tokens=4_000))
        cm = mock.MagicMock()
        cm.__enter__.return_value.get_final_message.return_value = msg
        return cm


@mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-prueba'})
class IATest(Base):
    def setUp(self):
        super().setUp()
        _pdf(self.carpeta / 'Contrato Local 1 Ale Anexo.pdf')
        carpetas.revisar(self.soc)
        self.archivo = ArchivoContrato.objects.get()
        self.p = PropuestaIA.objects.create(archivo=self.archivo, contrato=self.c1, modelo='claude-opus-5-5', pedida_por='op')

    def test_lee_el_pdf_y_deja_la_propuesta_lista(self):
        cli = ClienteFalso()
        p = ia.ejecutar(self.p.pk, cliente=cli)
        self.assertEqual(p.estado, 'L')
        self.assertEqual(p.costo_usd, D('0.28'))   # 50.000 × 4 + 4.000 × 20 por millón
        kw = cli.llamadas[0]
        self.assertEqual(kw['model'], 'claude-opus-5-5')
        self.assertEqual(kw['fallbacks'], 'default')
        self.assertEqual(kw['output_config']['format']['type'], 'json_schema')
        self.assertEqual(kw['messages'][0]['content'][0]['type'], 'document')
        self.assertIn('P-01', kw['messages'][0]['content'][1]['text'])
        filas = {f['clave']: f for f in ia.diferencias(p)}
        self.assertTrue(filas['tipo_documento']['cambia'])
        self.assertTrue(filas['tramos']['cambia'])
        self.assertFalse(filas['arrendatario']['cambia'])

    def test_aplicar_solo_lo_marcado_y_queda_en_el_historial(self):
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso())
        ia.aplicar(p, ['tipo_documento', 'tramos'], 'matias')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tipo_documento, 'NC')
        self.assertIsNone(self.c1.aviso_dias)  # no se marcó
        self.assertEqual([(t.desde, t.monto) for t in self.c1.tramos.all()], [(date(2025, 1, 1), D('27')), (date(2026, 9, 1), D('30.5'))])
        self.assertIn('Contrato Local 1 Ale Anexo.pdf', self.c1.documentos_fuente)
        r = RegistroCambio.objects.filter(contrato=self.c1, origen='IA', objeto='Contrato').first()
        self.assertEqual((r.usuario, r.cambios['tipo documento']), ('matias', ['FA', 'NC']))
        self.archivo.refresh_from_db()
        self.assertEqual(self.archivo.estado, 'R')
        with self.assertRaises(ValueError):
            ia.aplicar(p, ['tipo_documento'], 'matias')  # ya aplicada

    def _aplicar_y_borrar_el_archivo(self):
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso())
        ia.aplicar(p, ['tipo_documento', 'tramos'], 'matias')
        (self.carpeta / 'Contrato Local 1 Ale Anexo.pdf').unlink()
        carpetas.revisar(self.soc)
        self.archivo.refresh_from_db()
        self.assertEqual(self.archivo.estado, 'E')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tramos.count(), 2)   # borrar el archivo no cambia el contrato
        p.refresh_from_db()
        return p

    def test_deshacer_un_archivo_borrado_devuelve_la_renta_anterior(self):
        p = self._aplicar_y_borrar_el_archivo()
        self.assertEqual(ia.deshacible(self.archivo), p)
        plan = ia.plan_deshacer(p)
        self.assertEqual(plan['tramos_vuelven'], '01-01-2025 → sin término: 27 UF')
        ia.deshacer(p, 'matias')
        self.c1.refresh_from_db()
        self.assertEqual([(t.desde, t.hasta, t.monto) for t in self.c1.tramos.all()], [(date(2025, 1, 1), None, D('27'))])
        self.assertEqual(self.c1.tipo_documento, 'FA')
        self.assertNotIn('Contrato Local 1 Ale Anexo.pdf', self.c1.documentos_fuente)   # vuelve la lista de fuentes anterior
        p.refresh_from_db()
        self.assertEqual(p.estado, 'X')
        self.assertIsNone(ia.deshacible(self.archivo))
        self.assertTrue(RegistroCambio.objects.filter(contrato=self.c1, origen='deshacer archivo', usuario='matias').exists())
        with self.assertRaises(ValueError):
            ia.deshacer(p, 'matias')   # ya deshecha

    def test_deshacer_lo_aplicado_antes_de_esta_version_usa_el_historial(self):
        p = self._aplicar_y_borrar_el_archivo()
        PropuestaIA.objects.filter(pk=p.pk).update(antes={})   # propuestas aplicadas antes de guardar la foto
        p.refresh_from_db()
        self.assertTrue(ia.plan_deshacer(p)['antes']['desde_historial'])
        ia.deshacer(p, 'matias')
        self.c1.refresh_from_db()
        self.assertEqual([(t.desde, t.monto, t.unidad) for t in self.c1.tramos.all()], [(date(2025, 1, 1), D('27'), 'UF')])
        self.assertEqual(self.c1.tipo_documento, 'FA')

    def test_no_se_deshace_si_despues_se_aplico_otro_archivo(self):
        p = self._aplicar_y_borrar_el_archivo()
        _pdf(self.carpeta / 'Contrato Local 1 Ale Anexo 2.pdf')
        carpetas.revisar(self.soc)
        p2 = PropuestaIA.objects.create(archivo=ArchivoContrato.objects.get(nombre='Contrato Local 1 Ale Anexo 2.pdf'), contrato=self.c1)
        ia.aplicar(ia.ejecutar(p2.pk, cliente=ClienteFalso()), ['tramos'], 'matias')
        self.assertIn('Anexo 2.pdf', ia.plan_deshacer(p)['error'])
        with self.assertRaises(ValueError):
            ia.deshacer(p, 'matias')

    def test_no_se_deshace_un_archivo_que_creo_el_contrato(self):
        datos = dict(RESPUESTA, contrato_existente_codigo='', arrendatario_razon_social='Nueva Ltda', arrendatario_rut='22.222.222-2',
                     inicio_vigencia='2026-11-01')
        self.p.contrato = None
        self.p.save()
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso(datos))
        ia.aplicar(p, ['tramos'], 'matias', propiedad_id=self.prop.pk)
        self.assertIn('creó el contrato', ia.plan_deshacer(p)['error'])
        PropuestaIA.objects.filter(pk=p.pk).update(antes={})
        p.refresh_from_db()
        self.assertIn('creó el contrato', ia.plan_deshacer(p)['error'])

    def test_alerta_del_pdf_borrado_con_cambios_aplicados(self):
        from facturacion import servicios
        p = self._aplicar_y_borrar_el_archivo()
        self.assertTrue(any('Contrato Local 1 Ale Anexo.pdf' in t for *_, t in servicios.alertas_vigentes(date(2026, 10, 19), sociedad=self.soc)))
        ia.deshacer(p, 'matias')
        self.assertEqual(servicios.archivos_borrados_con_cambios(self.soc), [])

    def test_pantalla_deshacer(self):
        p = self._aplicar_y_borrar_el_archivo()
        Group.objects.get_or_create(name='Operación')
        u = User.objects.create_user('op', password='x')
        u.groups.add(Group.objects.get(name='Operación'))
        self.client.force_login(u)
        r = self.client.get(f'/contratos/archivos/?sociedad={self.soc.id}')
        self.assertContains(r, 'Deshacer sus cambios')
        self.assertContains(r, 'no deshace')
        r = self.client.get(f'/contratos/archivos/{self.archivo.pk}/deshacer/')
        self.assertContains(r, '01-01-2025 → sin término: 27 UF')
        r = self.client.post(f'/contratos/archivos/{self.archivo.pk}/deshacer/')
        self.assertRedirects(r, '/contratos/P-01/', fetch_redirect_response=False)
        self.assertEqual(self.c1.tramos.count(), 1)
        p.refresh_from_db()
        self.assertEqual(p.estado, 'X')
        self.assertNotContains(self.client.get(f'/contratos/archivos/?sociedad={self.soc.id}'), 'Deshacer sus cambios')

    def test_crear_contrato_nuevo_desde_la_propuesta(self):
        datos = dict(RESPUESTA, contrato_existente_codigo='', arrendatario_razon_social='Nueva Ltda', arrendatario_rut='22.222.222-2',
                     nombre_fantasia='Nueva', inicio_vigencia='2026-11-01')
        self.p.contrato = None
        self.p.save()
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso(datos))
        c = ia.aplicar(p, ['tramos', 'tipo_documento'], 'matias', propiedad_id=self.prop.pk)
        self.assertEqual((c.codigo, c.arrendatario.rut, c.inicio_vigencia, c.tipo_documento), ('C-01', '22.222.222-2', date(2026, 11, 1), 'NC'))
        self.assertTrue(RegistroCambio.objects.filter(contrato=c, accion='creado', origen='IA').exists())

    def test_sin_inicio_de_la_ia_se_pide_a_mano(self):
        datos = dict(RESPUESTA, contrato_existente_codigo='', arrendatario_razon_social='RobFre SpA', arrendatario_rut='33.333.333-3',
                     inicio_vigencia='', fecha_entrega='2026-09-15')
        self.p.contrato = None
        self.p.save()
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso(datos))
        with self.assertRaisesMessage(ValueError, 'ingréselo a mano'):
            ia.aplicar(p, ['tramos'], 'matias', propiedad_id=self.prop.pk)
        c = ia.aplicar(p, ['tramos', 'fecha_entrega'], 'matias', propiedad_id=self.prop.pk,
                       fechas={'inicio_vigencia': '2026-10-01', 'fecha_apertura': '2026-10-20', 'fecha_entrega': ''})
        self.assertEqual((c.inicio_vigencia, c.fecha_entrega, c.fecha_apertura), (date(2026, 10, 1), date(2026, 9, 15), date(2026, 10, 20)))

    def test_fechas_a_mano_mandan_sobre_la_ia(self):
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso(dict(RESPUESTA, fecha_apertura='2026-01-01')))
        ia.aplicar(p, ['fecha_apertura'], 'matias', fechas={'fecha_apertura': '2026-02-01'})
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.fecha_apertura, date(2026, 2, 1))

    def test_codigo_automatico_y_correlativo(self):
        self.prop.prefijo = 'B'
        self.prop.save()
        self.assertEqual(self.prop.siguiente_codigo(), 'B-01')
        Contrato.objects.create(codigo='B-40', propiedad=self.prop, sociedad=self.soc, arrendatario=self.arr, inicio_vigencia=date(2025, 1, 1))
        c = Contrato.objects.create(propiedad=self.prop, sociedad=self.soc, arrendatario=self.arr, inicio_vigencia=date(2025, 1, 1))
        self.assertEqual(c.codigo, 'B-41')
        self.assertEqual(self.prop.siguiente_codigo(), 'B-42')

    def test_errores_quedan_en_la_propuesta(self):
        p = ia.ejecutar(self.p.pk, cliente=ClienteFalso(error=OSError('sin red')))
        self.assertEqual((p.estado, p.error), ('E', 'sin red'))
        p2 = PropuestaIA.objects.create(archivo=self.archivo, contrato=self.c1, modelo='claude-opus-5-5')
        self.assertEqual(ia.ejecutar(p2.pk, cliente=ClienteFalso(stop='refusal')).estado, 'E')

    def test_sin_clave_no_se_lee(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.object(ia, '_ruta_clave', return_value=self.raiz / 'no'):
            with self.assertRaises(ia.SinClave):
                ia.iniciar(self.archivo, 'op')

    def test_clave_se_guarda_en_la_base_y_no_se_muestra(self):
        from .models import DatoSistema
        ruta = self.raiz / '.clave_anthropic'
        ruta.write_text('sk-ant-prueba-antigua-9999')   # clave de la versión anterior (archivo): se traslada a la base
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.object(ia, '_ruta_clave', return_value=ruta):
            self.assertEqual(ia.clave_configurada(), '…9999')
            self.assertTrue(DatoSistema.objects.filter(clave='clave_anthropic').exists())
            ia.guardar_clave('sk-ant-prueba-secreta-1234')
            self.assertEqual(ia.clave_configurada(), '…1234')
            self.assertFalse(ruta.exists())
            ia.guardar_clave('')
            self.assertEqual(ia.clave_configurada(), '')


# ------------------------------------------------------------------ pantallas y permisos
class PantallasTest(Base):
    def setUp(self):
        super().setUp()
        for r in ('Administrador', 'Operación', 'Contabilidad'):
            Group.objects.get_or_create(name=r)
        self.op = User.objects.create_user('op', password='x')
        self.op.groups.add(Group.objects.get(name='Operación'))
        self.admin = User.objects.create_superuser('admin', password='x')
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf')
        _pdf(self.carpeta / 'Estatutos.pdf')

    def test_contratos_con_enlaces_a_los_pdf(self):
        self.client.force_login(self.op)
        r = self.client.post('/contratos/archivos/revisar/', {'sociedad': self.soc.id})
        self.assertEqual(r.status_code, 302)
        a = ArchivoContrato.objects.get(nombre='Contrato Local 1 Ale.pdf')
        r = self.client.get(f'/contratos/?sociedad={self.soc.id}')
        self.assertContains(r, f'/contratos/archivos/{a.pk}/pdf/')
        self.assertContains(r, '1 archivo(s) nuevos o cambiados')
        r = self.client.get(f'/contratos/archivos/{a.pk}/pdf/')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertContains(self.client.get('/contratos/P-01/'), 'Contrato Local 1 Ale.pdf')
        self.assertEqual(self.client.get(f'/contratos/archivos/?sociedad={self.soc.id}').status_code, 200)

    def test_pdf_fuera_de_las_carpetas_no_se_entrega(self):
        self.client.force_login(self.op)
        a = ArchivoContrato.objects.create(sociedad=self.soc, ruta='/etc/hosts', nombre='hosts')
        self.assertEqual(self.client.get(f'/contratos/archivos/{a.pk}/pdf/').status_code, 404)

    def test_solo_el_administrador_cambia_carpetas(self):
        self.client.force_login(self.op)
        datos = {'sociedad': self.soc.id, 'accion': 'carpeta', 'tipo': 'facturas', 'ruta': str(self.raiz)}
        self.assertEqual(self.client.post('/configuracion/guardar/', datos).status_code, 403)
        self.assertEqual(self.client.get(f'/configuracion/elegir-carpeta/?sociedad={self.soc.id}').status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f'/configuracion/elegir-carpeta/?sociedad={self.soc.id}&tipo=facturas').status_code, 200)
        self.client.post('/configuracion/guardar/', datos)
        self.soc.refresh_from_db()
        self.assertEqual(self.soc.carpeta_facturas, str(self.raiz))
        self.client.post('/configuracion/guardar/', dict(datos, ruta='/etc'))
        self.soc.refresh_from_db()
        self.assertEqual(self.soc.carpeta_facturas, str(self.raiz))  # rechazada
        self.assertTrue(RegistroCambio.objects.filter(objeto='Sociedad', usuario='admin', origen='panel').exists())

    def test_editar_tipo_de_documento_desde_el_panel(self):
        self.client.force_login(self.op)
        r = self.client.get('/contratos/P-01/editar/')
        datos = {k: v for k, v in r.context['form'].initial.items() if v is not None}
        datos.update(tipo_documento='NC', inicio_vigencia='2025-01-01', activo='on', autoriza_avisos='on')
        r = self.client.post('/contratos/P-01/editar/', datos)
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tipo_documento, 'NC')
        h = RegistroCambio.objects.filter(contrato=self.c1, objeto='Contrato').first()
        self.assertEqual((h.usuario, h.origen, h.cambios['tipo documento']), ('op', 'panel', ['FA', 'NC']))
        self.assertContains(self.client.get('/contratos/P-01/'), 'Historial de cambios')

    def test_ignorar_y_asociar_archivo(self):
        self.client.force_login(self.op)
        carpetas.revisar(self.soc)
        a = ArchivoContrato.objects.get(nombre='Estatutos.pdf')
        self.client.post(f'/contratos/archivos/{a.pk}/accion/', {'accion': 'ignorar'})
        a.refresh_from_db()
        self.assertTrue(a.ignorar)
        self.assertFalse(a.pendiente)
        self.client.post(f'/contratos/archivos/{a.pk}/accion/', {'accion': 'asociar', 'contrato': self.c1.pk})
        a.refresh_from_db()
        self.assertEqual(a.contrato, self.c1)


# ------------------------------------------------------------------ inicio de cobro y actas de entrega
class InicioCobroTest(Base):
    def test_reglas_calculan_el_inicio_de_cobro(self):
        c = self.c1
        c.regla_inicio_cobro, c.dias_inicio_cobro, c.fecha_entrega = 'ENT', 60, date(2026, 9, 1)
        c.save()
        self.assertEqual(c.fecha_inicio_cobro, date(2026, 10, 31))
        c.regla_inicio_cobro, c.fecha_apertura = 'PRI', date(2026, 10, 15)   # apertura antes de los 60 días: manda la apertura
        c.save()
        self.assertEqual(c.fecha_inicio_cobro, date(2026, 10, 15))
        c.regla_inicio_cobro = 'APE'
        c.save()
        self.assertEqual((c.fecha_inicio_cobro, c.inicio_cobro_auto), (date(2026, 10, 15), True))

    def test_fecha_a_mano_no_se_pisa(self):
        c = self.c1
        c.fecha_inicio_cobro, c.inicio_cobro_auto = date(2026, 12, 1), False
        c.regla_inicio_cobro, c.fecha_apertura = 'APE', date(2026, 10, 15)
        c.save()
        self.assertEqual(c.fecha_inicio_cobro, date(2026, 12, 1))

    def test_la_renta_se_cobra_desde_el_inicio_de_cobro_con_prorrata(self):
        from facturacion import servicios
        from indicadores.models import UF
        for m in (9, 10):
            UF.objects.create(fecha=date(2026, m, 1), valor=D('40000'))
        self.c1.fecha_inicio_cobro, self.c1.inicio_cobro_auto = date(2026, 10, 17), False
        self.c1.save()
        r, lineas = servicios.calcular_contrato(self.c1, 2026, 9)
        self.assertEqual(lineas, [])
        r, lineas = servicios.calcular_contrato(self.c1, 2026, 10)
        self.assertEqual(lineas[0].monto, D('13.0645'))   # 27 UF × 15/31 días (17 al 31 de octubre)
        self.assertIn('15/31', lineas[0].detalle)

    def test_regla_sin_fechas_avisa(self):
        from facturacion import servicios
        from indicadores.models import UF
        UF.objects.create(fecha=date(2026, 10, 1), valor=D('40000'))
        self.c1.regla_inicio_cobro = 'ENT'
        self.c1.save()
        r, _ = servicios.calcular_contrato(self.c1, 2026, 10)
        self.assertTrue(any('inicio de cobro' in a for a in r.advertencias))


ACTA = {'resumen': 'Entrega del Local 1 a Ale SpA.', 'contrato_existente_codigo': 'P-01', 'fecha_entrega': '2026-09-01', 'locales': 'Local 1',
        'arrendatario_razon_social': 'Ale SpA', 'arrendatario_rut': '11.111.111-1', 'entrega_por': 'Juan Pérez (administrador)',
        'recibe': 'Ana Soto', 'lecturas': [{'servicio': 'luz', 'medidor': '123', 'lectura': '4567'}], 'observaciones': 'Local en buen estado.', 'dudas': []}


@mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-prueba'})
class ActasTest(Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name='Operación')
        self.op = User.objects.create_user('op', password='x')
        self.op.groups.add(Group.objects.get(name='Operación'))
        self.c1.regla_inicio_cobro, self.c1.dias_inicio_cobro = 'ENT', 60
        self.c1.save()
        o = override_settings(MEDIA_ROOT=str(self.raiz / 'media'))
        o.enable()
        self.addCleanup(o.disable)

    def test_subir_leer_con_ia_y_registrar_en_el_contrato(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.op)
        with mock.patch.object(ia, 'EN_SEGUNDO_PLANO', False), mock.patch.object(ia, '_cliente', return_value=ClienteFalso(ACTA)):
            r = self.client.post('/contratos/actas/subir/', {'sociedad': self.soc.id,
                                 'archivo': SimpleUploadedFile('Acta Local 1.pdf', b'%PDF-1.4 acta', content_type='application/pdf')})
        from .models import ActaEntrega
        a = ActaEntrega.objects.get()
        self.assertRedirects(r, f'/contratos/actas/{a.pk}/')
        self.assertEqual((a.estado, a.contrato, a.fecha_entrega, a.recibe), ('L', self.c1, date(2026, 9, 1), 'Ana Soto'))
        self.assertIn('luz 123: 4567', a.lecturas)
        self.assertEqual(self.client.get(f'/contratos/actas/{a.pk}/archivo/')['Content-Type'], 'application/pdf')
        datos = {'contrato': self.c1.pk, 'fecha_entrega': '2026-09-02', 'locales': a.locales, 'entrega_por': a.entrega_por, 'recibe': a.recibe,
                 'lecturas': a.lecturas, 'observaciones': a.observaciones, 'accion': 'registrar'}
        self.client.post(f'/contratos/actas/{a.pk}/', datos)
        self.c1.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual((a.estado, self.c1.fecha_entrega, self.c1.fecha_inicio_cobro), ('R', date(2026, 9, 2), date(2026, 11, 1)))
        self.assertTrue(RegistroCambio.objects.filter(contrato=self.c1, objeto='Contrato', usuario='op').exists())
        self.assertContains(self.client.get(f'/contratos/actas/?sociedad={self.soc.id}'), 'Acta Local 1.pdf')
        self.assertContains(self.client.get('/contratos/P-01/'), 'Inicio de cobro')

    def test_sin_clave_queda_para_completar_a_mano(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import ActaEntrega
        self.client.force_login(self.op)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.object(ia, '_ruta_clave', return_value=self.raiz / 'no'):
            self.client.post('/contratos/actas/subir/', {'sociedad': self.soc.id, 'archivo': SimpleUploadedFile('acta.jpg', b'jpg', content_type='image/jpeg')})
        self.assertEqual(ActaEntrega.objects.get().estado, 'S')
        r = self.client.post('/contratos/actas/subir/', {'sociedad': self.soc.id, 'archivo': SimpleUploadedFile('acta.exe', b'x')})
        self.assertEqual(ActaEntrega.objects.count(), 1)   # formato rechazado

    def test_carpeta_de_actas_y_equipamiento(self):
        from .models import ActaEntrega
        actas = self.raiz / 'Actas'
        _pdf(actas / 'Acta Entrega Local 1.pdf')
        (actas / 'foto acta.jpg').write_bytes(b'jpg')
        (actas / 'leeme.txt').write_text('x')
        self.soc.carpeta_actas = str(actas)
        self.soc.save()
        self.assertIn('2 nuevas', carpetas.revisar_actas(self.soc))
        self.assertIn('0 nuevas', carpetas.revisar_actas(self.soc))
        datos = dict(ACTA, numero='E-12', inicio_gastos_comunes='2026-10-01',
                     equipamiento=[{'elemento': 'Tablero eléctrico', 'estado': 'si'}, {'elemento': 'Baño', 'estado': 'no'}])
        with mock.patch.object(ia, 'EN_SEGUNDO_PLANO', False), mock.patch.object(ia, '_cliente', return_value=ClienteFalso(datos)):
            self.assertEqual(ia.leer_actas_pendientes(self.soc), 2)
        a = ActaEntrega.objects.get(nombre='Acta Entrega Local 1.pdf')
        self.assertEqual((a.estado, a.numero, a.inicio_gastos_comunes, a.equipamiento[1]['estado']), ('L', 'E-12', date(2026, 10, 1), 'no'))
        self.client.force_login(self.op)
        self.assertEqual(self.client.get(f'/contratos/actas/{a.pk}/archivo/')['Content-Type'], 'application/pdf')
        self.assertContains(self.client.get(f'/contratos/actas/{a.pk}/'), 'Tablero eléctrico')
        os.remove(actas / 'foto acta.jpg')
        self.assertIn('1 ya no están', carpetas.revisar_actas(self.soc))
        self.assertTrue(ActaEntrega.objects.get(nombre='foto acta.jpg').ya_no_esta)


    def _acta_registrada(self):
        from .models import ActaEntrega
        actas = self.raiz / 'Actas'
        _pdf(actas / 'Acta Local 1.pdf')
        self.soc.carpeta_actas = str(actas)
        self.soc.save()
        carpetas.revisar_actas(self.soc)
        a = ActaEntrega.objects.get()
        a.contrato, a.fecha_entrega, a.estado = self.c1, date(2026, 9, 2), 'L'
        a.save()
        ia.registrar_acta(a, 'op')
        self.c1.refresh_from_db()
        self.assertEqual((self.c1.fecha_entrega, self.c1.fecha_inicio_cobro), (date(2026, 9, 2), date(2026, 11, 1)))
        return a

    def test_deshacer_el_registro_de_un_acta_borrada(self):
        from facturacion import servicios
        a = self._acta_registrada()
        os.remove(self.raiz / 'Actas' / 'Acta Local 1.pdf')
        carpetas.revisar_actas(self.soc)
        alertas = [t for *_, t in servicios.archivos_borrados_con_cambios(self.soc)]
        self.assertTrue(any('Acta Local 1.pdf' in t for t in alertas))
        self.client.force_login(self.op)
        self.assertContains(self.client.get(f'/contratos/actas/{a.pk}/'), 'Deshacer el registro')
        self.client.post(f'/contratos/actas/{a.pk}/', {'accion': 'deshacer'})
        self.c1.refresh_from_db()
        a.refresh_from_db()
        self.assertEqual((a.estado, self.c1.fecha_entrega, self.c1.fecha_inicio_cobro), ('L', None, None))
        self.assertTrue(RegistroCambio.objects.filter(contrato=self.c1, origen='deshacer acta').exists())
        self.assertEqual(servicios.archivos_borrados_con_cambios(self.soc), [])

    def test_deshacer_un_acta_registrada_antes_de_este_cambio(self):
        from .models import ActaEntrega
        a = self._acta_registrada()
        ActaEntrega.objects.filter(pk=a.pk).update(antes={})
        a.refresh_from_db()
        self.assertTrue(ia.plan_deshacer_acta(a)['antes']['desde_historial'])
        ia.deshacer_acta(a, 'op')
        self.c1.refresh_from_db()
        self.assertIsNone(self.c1.fecha_entrega)

    def test_no_se_deshace_si_la_fecha_cambio_despues(self):
        a = self._acta_registrada()
        self.c1.fecha_entrega = date(2026, 9, 10)
        self.c1.save()
        self.assertIn('cambió después', ia.plan_deshacer_acta(a)['error'])


# ------------------------------------------------------------------ plano de locales
class PlanoTest(Base):
    def test_importar_dxf_y_colores_del_plano(self):
        import ezdxf
        from datetime import timedelta
        from django.utils import timezone
        from . import planos
        from .models import Local, ContratoLocal, PlanoPiso
        carpeta = self.raiz / 'Planos'
        carpeta.mkdir()
        doc = ezdxf.new()
        doc.header['$INSUNITS'] = 5   # centímetros
        msp = doc.modelspace()
        for i, x in enumerate((0, 600, 1200), start=1):   # tres locales de 6 × 4 m = 24 m²
            if i != 3:   # al local 3 le falta el contorno: se copia del vecino de igual tamaño
                msp.add_lwpolyline([(x, 0), (x + 600, 0), (x + 600, 400), (x, 400)], close=True, dxfattribs={'layer': 'A-AUXILIAR'})
            msp.add_text(f'LOCAL {i:02d}', dxfattribs={'layer': 'TEXTO', 'insert': (x + 300, 250)})
            msp.add_text('24.0 m²', dxfattribs={'layer': 'TEXTO', 'insert': (x + 300, 150)})
        msp.add_line((0, 0), (1800, 0), dxfattribs={'layer': 'Muros'})
        doc.saveas(carpeta / 'piso1.dxf')
        ezdxf.new().saveas(carpeta / 'elevacion.dxf')   # sin locales: se omite
        locs = [Local.objects.create(propiedad=self.prop, codigo_plano=f'L0{i}', piso='Primer piso', m2_oficial=D('24')) for i in (1, 2, 3)]
        ContratoLocal.objects.create(contrato=self.c1, local=locs[0])
        self.prop.carpeta_planos = str(carpeta)
        self.prop.save()
        r = planos.importar_propiedad(self.prop)
        self.assertIn('Primer piso (3 locales)', r)
        self.assertIn('elevacion.dxf', r)
        piso = PlanoPiso.objects.get()
        lp = {x.etiqueta: x for x in piso.locales_plano.all()}
        self.assertEqual((lp['1'].m2_plano, lp['3'].m2_plano, lp['3'].aproximado), (D('24.0'), D('24.0'), True))
        self.assertEqual(list(lp['2'].locales.all()), [locs[1]])
        hoy = timezone.localdate()
        self.c1.fin_pactado = hoy + timedelta(days=400)
        self.c1.save()
        self.assertEqual(planos.estado(lp['1'], hoy)['color'], 'verde')
        self.assertEqual(planos.estado(lp['2'], hoy)['color'], 'rojo')
        self.c1.fin_pactado, self.c1.prorroga_meses = hoy + timedelta(days=60), 0
        self.c1.save()
        self.assertEqual(planos.estado(lp['1'], hoy)['color'], 'amarillo')
        self.assertIn('sin cambios', planos.importar_propiedad(self.prop))   # no se vuelve a leer si no cambió
        u = User.objects.create_user('ver', password='x')
        self.client.force_login(u)
        r = self.client.get(f'/plano/?propiedad={self.prop.pk}')
        self.assertContains(r, 'href="/contratos/P-01/"')
        self.assertContains(r, '<polygon', count=3)
        self.assertContains(r, 'Disponible')

    def test_local_dividido_en_a_y_b(self):
        """Boulevard 1 y 11 se arriendan en dos partes (1A/1B, 11A/11B): se dividen con «divisiones» de locales_plano.json."""
        import ezdxf, json
        from . import planos
        from .models import Local, PlanoPiso
        carpeta = self.raiz / 'Planos'
        carpeta.mkdir()
        doc = ezdxf.new()
        doc.header['$INSUNITS'] = 5
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 1000), (0, 1000)], close=True, dxfattribs={'layer': 'A-AUXILIAR'})
        msp.add_text('LOCAL 01', dxfattribs={'layer': 'TEXTO', 'insert': (500, 500)})
        doc.saveas(carpeta / 'piso1.dxf')
        (carpeta / 'locales_plano.json').write_text(json.dumps({'piso1.dxf': {'divisiones': {'1': {
            '1A': [[0, 0], [10, 0], [10, 6], [0, 6]], '1B': [[0, 6], [10, 6], [10, 10], [0, 10]]}}}}))
        a = Local.objects.create(propiedad=self.prop, codigo_plano='L01-A (1A)', piso='Primer piso')
        b = Local.objects.create(propiedad=self.prop, codigo_plano='L01-B (1B)', piso='Primer piso')
        self.prop.carpeta_planos = str(carpeta)
        self.prop.save()
        planos.importar_propiedad(self.prop)
        lp = {x.etiqueta: x for x in PlanoPiso.objects.get().locales_plano.all()}
        self.assertEqual(sorted(lp), ['1A', '1B'])
        self.assertEqual((lp['1A'].m2_plano, lp['1B'].m2_plano), (D('60.0'), D('40.0')))
        self.assertEqual((list(lp['1A'].locales.all()), list(lp['1B'].locales.all())), ([a], [b]))
        self.assertEqual(planos.locales_para(self.prop, '1'), [a, b])   # sin letra: ambos


# ------------------------------------------------------------------ Google Drive (con un Drive simulado: no se conecta a Google)
class DriveFalso:
    """Imita lo justo de la API de Google Drive v3 que usa almacen.py."""
    def __init__(self, archivos):
        self.a = {f['id']: f for f in archivos}

    def files(self):
        return self

    def list(self, q='', pageToken=None, **kw):
        import re
        m = re.match(r"'([^']+)' in parents", q)
        if m:
            fs = [f for f in self.a.values() if m.group(1) in f.get('parents', [])]
        else:
            fs = [f for f in self.a.values() if f.get('compartido')]
        return mock.Mock(execute=lambda: {'files': fs})

    def get(self, fileId, **kw):
        return mock.Mock(execute=lambda: self.a[fileId])

    def get_media(self, fileId, **kw):
        return ('media', fileId)


CARPETA = 'application/vnd.google-apps.folder'


@mock.patch.dict(os.environ, {'GOOGLE_SERVICE_ACCOUNT_JSON': '{"client_email": "brisas@proyecto.iam.gserviceaccount.com"}'})
class DriveTest(Base):
    def drive(self):
        t = '2026-10-01T10:00:00.000Z'
        return DriveFalso([
            {'id': 'raiz', 'name': 'Contratos Vigentes', 'mimeType': CARPETA, 'modifiedTime': t, 'compartido': True},
            {'id': 'sub', 'name': 'Antiguos', 'mimeType': CARPETA, 'parents': ['raiz'], 'modifiedTime': t},
            {'id': 'f1', 'name': 'Contrato Local 1 Ale.pdf', 'mimeType': 'application/pdf', 'size': '40', 'parents': ['raiz'], 'modifiedTime': t},
            {'id': 'f2', 'name': 'Viejo.pdf', 'mimeType': 'application/pdf', 'size': '10', 'parents': ['sub'], 'modifiedTime': t},
            {'id': 'at', 'name': 'atajo.pdf', 'mimeType': 'application/vnd.google-apps.shortcut', 'parents': ['raiz'], 'modifiedTime': t,
             'shortcutDetails': {'targetId': 'f3'}},
            {'id': 'f3', 'name': 'Anexo real.pdf', 'mimeType': 'application/pdf', 'size': '5', 'modifiedTime': t},
            {'id': 'n1', 'name': 'notas.txt', 'mimeType': 'text/plain', 'size': '1', 'parents': ['raiz'], 'modifiedTime': t},
        ])

    def test_listar_seguir_atajos_y_raices(self):
        from . import almacen
        with mock.patch.object(almacen, '_drive', return_value=self.drive()):
            nombres = sorted(e.nombre for e in almacen.listar('gdrive:raiz', {'.pdf'}))
            self.assertEqual(nombres, ['Anexo real.pdf', 'Contrato Local 1 Ale.pdf', 'Viejo.pdf'])
            self.assertEqual(almacen.validar_carpeta('gdrive:raiz'), 'gdrive:raiz')
            with self.assertRaises(almacen.CarpetaNoPermitida):
                almacen.validar_carpeta('gdrive:f1')   # un archivo no es carpeta
            self.assertIn(('Drive · Compartido conmigo · Contratos Vigentes', 'gdrive:raiz'), almacen.raices())
            self.assertEqual(almacen.subcarpetas('gdrive:raiz'), [('Antiguos', 'gdrive:sub')])
        self.assertEqual(almacen.correo_cuenta_servicio(), 'brisas@proyecto.iam.gserviceaccount.com')

    def test_pasar_del_mac_a_drive_conserva_contratos_e_historial(self):
        from . import almacen
        _pdf(self.carpeta / 'Contrato Local 1 Ale.pdf', 'x' * 30)   # 40 bytes, igual que en Drive
        carpetas.revisar(self.soc)
        a = ArchivoContrato.objects.get(nombre='Contrato Local 1 Ale.pdf')
        a.drive_id = 'f1'
        a.save()
        self.soc.carpeta_contratos = 'gdrive:raiz'
        self.soc.save()
        with mock.patch.object(almacen, '_drive', return_value=self.drive()):
            r = carpetas.revisar(self.soc)
        a.refresh_from_db()
        self.assertEqual((a.ruta, a.contrato, a.estado), ('gdrive:f1', self.c1, 'R'))
        self.assertEqual([x.nombre for x in r.movidos], ['Contrato Local 1 Ale.pdf'])
        self.assertEqual(sorted(x.nombre for x in r.nuevos), ['Anexo real.pdf', 'Viejo.pdf'])
        self.assertEqual(ArchivoContrato.objects.get(nombre='Viejo.pdf').url_drive, 'https://drive.google.com/file/d/f2/view')


class TodosLosPdfSeLeenTest(Base):
    """Caso O-01 (2026-10-15): un anexo que fijaba la renta 2026 se leyó, pero se marcó «revisado» sin aplicar la propuesta."""
    def _usuario(self):
        from django.contrib.auth.models import Group
        Group.objects.get_or_create(name='Operación')
        u = User.objects.create_user('op9', password='x')
        u.groups.add(Group.objects.get(name='Operación'))
        self.client.force_login(u)

    def test_no_se_marca_revisado_con_propuesta_sin_resolver(self):
        from .models import ArchivoContrato, PropuestaIA
        a = ArchivoContrato.objects.create(sociedad=self.soc, ruta=str(self.carpeta / 'anexo.pdf'), nombre='anexo.pdf', contrato=self.c1, estado='N')
        p = PropuestaIA.objects.create(archivo=a, contrato=self.c1, estado='L', datos={'resumen': 'fija renta 2026'})
        self._usuario()
        r = self.client.post(f'/contratos/archivos/{a.pk}/accion/', {'accion': 'revisado'})
        a.refresh_from_db()
        self.assertEqual(a.estado, 'N')
        self.assertTrue(a.pendiente)
        self.assertRedirects(r, f'/contratos/propuesta/{p.pk}/', fetch_redirect_response=False)
        # aunque el archivo ya figure como revisado, sigue pendiente mientras la propuesta no se aplique ni descarte
        ArchivoContrato.objects.filter(pk=a.pk).update(estado='R')
        a.refresh_from_db()
        self.assertTrue(a.pendiente)
        p.estado = 'D'
        p.save()
        self.assertFalse(a.pendiente)

    def test_revisar_la_carpeta_lee_con_ia_todos_los_pdf_nuevos(self):
        from unittest import mock
        from . import ia
        from .models import ArchivoContrato
        _pdf(self.carpeta / 'CONTRATO ARR. FIJO PLAZA MOTOR AUOPLANET  MODIFICACION PRUEBA.pdf')
        _pdf(self.carpeta / 'Otro anexo.pdf')
        carpetas.revisar(self.soc)
        with mock.patch.object(ia, 'clave_api', return_value='sk-ant-prueba'), mock.patch.object(ia, 'ejecutar') as ejecutar:
            self.assertEqual(ia.leer_pendientes(self.soc, 'prueba', segundo_plano=False), 2)
            self.assertEqual(ejecutar.call_count, 2)
            self.assertEqual(ia.leer_pendientes(self.soc, 'prueba', segundo_plano=False), 0)   # ya tienen lectura en curso
        self.assertEqual(ArchivoContrato.objects.filter(propuestas__isnull=False).distinct().count(), 2)
        with mock.patch.object(ia, 'clave_api', return_value=None):
            self.assertEqual(ia.leer_pendientes(self.soc), 0)   # sin clave no hace nada
