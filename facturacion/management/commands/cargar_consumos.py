from datetime import date

from django.core.management.base import BaseCommand, CommandError

from facturacion import cargas, lectores

from ._comun import leer_periodo


class Command(BaseCommand):
    help = ('Carga electricidad, gas u otros cargos desde las planillas mensuales.\n'
            '  cargar_consumos electricidad Facturacion_electrica_Brisas_Septiembre_2026.xlsx --consumo 2026-09\n'
            '  cargar_consumos gas "Facturación Gas Brisas Septiembre - 2026.xls" --consumo 2026-09\n'
            '  cargar_consumos otros cargos.xlsx   (plantilla: Contrato | Concepto | Detalle | Neto | Mes de cobro)\n'
            'Por defecto el consumo de un mes se cobra en la factura del mes siguiente (cambie con --cobro).')

    def add_arguments(self, p):
        p.add_argument('tipo', choices=['electricidad', 'gas', 'otros'])
        p.add_argument('archivo')
        p.add_argument('--consumo', help='mes consumido AAAA-MM (obligatorio para electricidad y gas)')
        p.add_argument('--cobro', help='mes de la factura AAAA-MM (por defecto, el mes siguiente al consumo)')
        p.add_argument('--sembrar', action='store_true', help='crear antes la asignación inicial de medidores')

    def handle(self, *a, **o):
        if o['sembrar']:
            self.stdout.write(f'Medidores creados: {cargas.sembrar_medidores()}')
        try:
            if o['tipo'] == 'otros':
                res = cargas.cargar_otros(lectores.leer_otros(o['archivo']), o['archivo'].split('/')[-1])
            else:
                if not o['consumo']:
                    raise CommandError('Indique el mes consumido con --consumo AAAA-MM.')
                año, mes = leer_periodo(o['consumo'])
                consumo = date(año, mes, 1)
                cobro = date(*leer_periodo(o['cobro']), 1) if o['cobro'] else cargas.mes_siguiente(consumo)
                if o['tipo'] == 'electricidad':
                    mes_txt, filas = lectores.leer_electricidad(o['archivo'])
                    if mes_txt and lectores.norm(mes_txt) != lectores.MESES[mes - 1]:
                        raise CommandError(f'La planilla es de «{mes_txt}» pero pidió consumo {o["consumo"]}.')
                else:
                    _, filas = lectores.leer_gas(o['archivo'], año, mes)
                res = cargas.cargar_filas(filas, consumo, cobro, o['archivo'].split('/')[-1])
        except lectores.PlanillaInvalida as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f'{res.cargados} cargos cargados por ${res.total:,.0f} neto'
                                             + (f' (se reemplazaron {res.reemplazados} anteriores)' if res.reemplazados else '')))
        if o['tipo'] != 'otros':
            self.stdout.write(f'   Se cobrarán en la factura de {cobro:%m-%Y}.')
        for n in res.en_cero:
            self.stdout.write(f'   sin cobro (0): {n}')
        for n, et, neto, fila in res.sin_medidor:
            self.stdout.write(self.style.WARNING(f'   SIN ASIGNAR: {n} ({et}) ${neto:,.0f} · fila {fila}. Agréguelo en Admin → Medidores.'))
        if res.por_confirmar:
            self.stdout.write(self.style.WARNING(f'   {len(res.por_confirmar)} medidores aún por confirmar (los documentos quedarán con advertencia).'))
