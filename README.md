# Brisas del Centro · Control de contratos y facturación (Fase 1, hito 3: panel web · modo oficina)

Sistema Django (Python) para controlar los 48 contratos de Boulevard y Plaza Motor y preparar la facturación mensual.
Funciona en Windows, macOS y Linux; se usa desde el navegador con un panel propio (también se instala como app en celular: PWA); el admin de Django queda para datos maestros.

## Encender el sistema en el Mac (sin usar Terminal)
Doble clic en `Iniciar_Brisas.command` (la primera vez, si macOS lo bloquea: clic derecho → Abrir). El archivo hace todo solo: crea el entorno
de Python si falta, instala los componentes, actualiza la base de datos, descarga UF e IPC, revisa las carpetas de contratos y de facturas emitidas,
hace un respaldo y deja el sistema encendido con un
servidor de producción (waitress). Al terminar, la ventana muestra «SISTEMA ENCENDIDO» con las direcciones para entrar.
- **Hay que mantener esa ventana abierta**: al cerrarla el sistema se apaga. El Mac no se duerme mientras esté encendido (`caffeinate`).
- Corre con `DEBUG` apagado; los estilos e íconos los sirve whitenoise. La clave secreta propia de la instalación queda en `.clave_secreta`
  (no se comparte; si se borra solo se cierran las sesiones abiertas, y el aviso «Session data corrupted» en la ventana es normal).
- Los errores del sistema quedan escritos en esa misma ventana.

## Entrar desde otros equipos y celulares
Detalle paso a paso en `ACCESO_REMOTO.md`. El Mac es el «servidor»; los demás entran por el navegador con su usuario y clave.
- Misma red (wifi o cable): la dirección con la IP del Mac o con `NombreDelMac.local`, ambas impresas en la ventana de encendido.
- Desde cualquier lugar: red privada **Tailscale**, `http://macbook-neo.tail0e201c.ts.net:8000/`. No se publica a internet abierto.
- Cada persona necesita su usuario (menú Administración → Usuarios) y un grupo: Administrador, Operación o Contabilidad. Sin grupo, solo ve.

## Respaldos
`python manage.py respaldar_bd --destino <carpeta> --conservar 60` guarda una copia consistente de la base SQLite
(`brisas_AAAA-MM-DD_HHMM.sqlite3`) y deja las últimas 60. El archivo de encendido hace un respaldo al partir y otro cada 6 horas en
la subcarpeta `Respaldos` de la carpeta del sistema (en Google Drive: Mi unidad → Sistema Facturacion → Respaldos).
Para restaurar: apagar el sistema, copiar el respaldo elegido como `db.sqlite3` y volver a encender.
Por decisión del propietario (2026-10-13) el sistema vive en Google Drive, directo en Mi unidad › Sistema Facturacion (sin subcarpetas extra), incluida la base. Riesgo conocido: sincronizar una base SQLite en uso puede
corromperla; por eso solo un computador (el servidor) debe usar esa carpeta y los respaldos de cada 6 horas son la red de seguridad. El entorno de Python queda aparte, en `~/Brisas_python` (no lleva datos y se recrea solo). En el Mac, la carpeta de Drive que sincroniza es `~/Library/CloudStorage/GoogleDrive-mfacuse@invercochile.com`; la que termina en «(26-06-26 7:25 p.m.)» es una copia vieja que Drive no sube.
Con PostgreSQL (producción) el respaldo se hace con `pg_dump`.

## Puesta en marcha manual (Windows/Linux o desarrollo)
```
python -m venv .venv
.venv\Scripts\activate          # Windows      |  source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py crear_roles             # grupos Administrador, Operación y Contabilidad
python manage.py importar_fase0          # (opcional) carga los contratos de las planillas v2 de datos/; ya no corre al encender
python manage.py cargar_indicadores      # UF e IPC oficiales: Banco Central si hay token, si no SII (necesita internet)
python manage.py runserver               # panel: http://127.0.0.1:8000/   admin: /admin/
```
Para dejarlo como servidor (varios usuarios): `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `python manage.py collectstatic`
y `python -m waitress --listen=0.0.0.0:8000 config.wsgi:application` (es lo que hace `Iniciar_Brisas.command`).

## Cada mes
```
python manage.py cargar_indicadores                       # UF del día
python manage.py generar_borradores 2026-11               # calcula todas las facturas del mes (ambas sociedades)
python manage.py aprobar_documentos 2026-11 --usuario matias   # los que tienen advertencias quedan pendientes
python manage.py exportar_bsoft 2026-11                   # XML para BSOFT (uno por factura + .zip) en salidas/bsoft/  (en pausa hasta validar la facturación)
python manage.py revisar_carpetas                         # PDF de contratos nuevos/cambiados y facturas emitidas por BSOFT (también al encender)
python manage.py exportar_excel 2026-11                   # Excel de revisión por sociedad en salidas/facturacion/
python manage.py alertas                                  # vencimientos, plazos de aviso, cambios de renta
```
Todos aceptan `--sociedad Boulevard` / `--sociedad "15 Oriente"` y, los de cálculo, `--contratos B-07 B-11`.
Las ventas netas de los locales con renta variable (B-21, B-36, B-40) se ingresan en Admin → Ventas mensuals
(el mes M factura la diferencia de las ventas de M‑1).

## Luz, gas y otros cargos
Cada mes se cargan desde las planillas que ya se arman (la de luz en .xlsx, la de gas en .xls). En el panel: **Cargas** → botón de cada tipo.
Por línea de comandos:
```
python manage.py cargar_consumos electricidad Facturacion_electrica_Brisas_Septiembre_2026.xlsx --consumo 2026-09 --sembrar
python manage.py cargar_consumos gas "Facturación Gas Brisas Septiembre - 2026.xls" --consumo 2026-09
python manage.py cargar_consumos otros datos/Plantilla_Otros_Cargos.xlsx      # cargos sueltos: Contrato | Concepto | Detalle | Neto | Mes de cobro
```
- El consumo de un mes se cobra en la factura del mes siguiente (cambie con `--cobro AAAA-MM`). Volver a cargar la misma planilla reemplaza lo anterior.
- `--sembrar` (solo la primera vez) crea la asignación de cada medidor a su contrato; se corrige y se confirma en Medidores (panel) o Admin → Medidores.
  Mientras un medidor no esté confirmado, el documento queda con advertencia y no se aprueba.
- Filas que no se pueden asignar o están en $0 se informan al cargar; nunca se pierden en silencio.
- Cada línea de la factura muestra el detalle auditable (medidor, lecturas, factor, kWh o litros) y que se cobra a costo.
- **Orden importante**: los borradores se calculan con lo que esté cargado en ese momento. Si la luz o el gas se cargan *después* de aprobar, los documentos
  aprobados no los incluyen (el panel lo avisa en Cargas y en Facturación). Solución: en Facturación, «Volver aprobados a borrador» y luego «Regenerar borradores»
  (el regenerado solo toca documentos en borrador).

## Reglas implementadas
- UF del día 1 del mes (o del primer día hábil en Mundo); redondeo al peso, mitad hacia arriba.
- Renta por tramos (UF o pesos), gracia como tramo en 0, prorrata por días en el primer/último mes y cuando la renta cambia a mitad de mes.
- Renta variable: el mes M cobra el mínimo de M más la diferencia entre (% × ventas netas de M‑1) y el mínimo de M‑1.
- Renta semestral en pesos con reajuste IPC cada enero (Bimedia: meses 1 y 6).
- Electricidad, gas y «otros» a costo, como líneas adicionales de la misma factura (ver sección anterior).
- IVA 19 % a nivel de documento; exentas y notas de cobro sin IVA. Un documento por contrato y mes.
- Estados: Borrador → Aprobado → Exportado; la aprobación se bloquea si hay advertencias (p. ej. faltan ventas, IPC o UF).
- Gastos comunes: los factura Megaservicios Talca SpA; el sistema solo mostrará lo facturado/pagado/en mora (hito siguiente).

## XML de BSOFT (en pausa)
Formato del archivo «Arriendo_Automatico_V2.XML»: un `<Documento>` por factura con `RUTcliente`, `glosaDocto` y un `<Detalle>`
por línea (`NroLinDet`, `CodServicio`, `Cantidad`=1, `Valor`=neto en pesos). Los códigos de servicio se cargan en
Admin → Códigos de servicio BSOFT (por sociedad y tipo de línea); si falta alguno la exportación se detiene y lo indica.
La exportación está en pausa por decisión del propietario hasta que la facturación esté 100 % validada (ver `decisiones-fase1.md`).

## Contratos: carpetas, archivos originales, IA e historial
- **Carpetas por sociedad** (Contratos › Carpetas y configuración, solo Administrador): se elige navegando las carpetas de Google Drive de este Mac
  la carpeta de contratos y la de facturas emitidas de cada sociedad; se pueden cambiar cuando se quiera (p. ej. una nueva para Camarico).
  Solo se aceptan carpetas dentro de Google Drive / OneDrive del Mac (no la copia vieja de Drive que no sincroniza). Boulevard usa
  `Mi unidad › Archivos Brisas del Centro › CONTRATOS › Contratos Vigentes`.
- **Revisión de la carpeta**: al encender y con el botón «Actualizar desde la carpeta». Mira nombre, tamaño y fecha (no descarga los PDF),
  así que tarda menos de un segundo. Marca cada PDF como *nuevo*, *cambiado*, *movido* o *ya no está*; nada se borra y cada movimiento queda registrado.
  Al configurar una carpeta por primera vez, los PDF cuyo nombre ya figura en «documentos fuente» de un contrato quedan al día y asociados.
- **Archivos originales**: la lista de contratos y la ficha de cada contrato tienen enlaces 📄 que abren el PDF (servido por el sistema, con usuario)
  y «abrir en Drive».
- **Lectura con IA** (Claude, de Anthropic): en Contratos › Archivos de contratos, «Leer con IA» envía el PDF y los datos actuales del contrato;
  la IA devuelve una propuesta (datos, calendario de renta completo, tipo de documento, dudas y la página de donde sale cada dato). Una persona
  marca qué datos aplicar o descarta la propuesta; también puede crear un contrato nuevo. Costo ≈ US$ 0,2–0,3 por contrato (queda guardado en
  cada propuesta). La clave de Anthropic la ingresa el Administrador en Carpetas y configuración (queda en `.clave_anthropic`, privada, no se muestra).
  El modelo se cambia con la variable `BRISAS_IA_MODELO` (por defecto `claude-opus-5-5`).
- **Historial**: todo cambio a contratos, rentas, descuentos, garantías, saldos, locales asignados y a la configuración de cada sociedad queda en
  «Historial de cambios» (ficha del contrato y Administración), con fecha, usuario, desde dónde (panel, administración, importador, IA) y antes → después.
  El historial no se puede editar ni borrar desde la administración.
- **Editar condiciones**: botón en la ficha (rol Operación o Administrador), incluido el **tipo de documento** (factura afecta, exenta o nota de cobro).

## Inicio de cobro y actas de entrega
- Cada contrato indica **desde cuándo se cobra la renta**: según el calendario de renta, desde la entrega del local (+ días), desde la apertura,
  o «apertura o N días desde la entrega, lo que ocurra primero». Con esa regla y las fechas de entrega y apertura, el sistema completa solo el
  **inicio de cobro**; se puede cambiar a mano en «Editar condiciones» (una fecha escrita a mano no se recalcula; si se borra, vuelve a calcularse).
  Antes de esa fecha no se cobra renta y el primer mes se prorratea por días. Si la regla pide una fecha que falta, el documento queda con advertencia.
- **Actas de entrega** (Contratos › Actas de entrega): se sube cada acta (PDF o foto); la IA rescata fecha, locales, quién entrega y recibe,
  lecturas de medidores y observaciones. Se revisan y con «Guardar y registrar la entrega en el contrato» la fecha pasa al contrato. El archivo queda
  guardado en `salidas/actas_entrega/` y enlazado desde el acta y la ficha del contrato.
- Los códigos de contrato se asignan solos por propiedad: B-01, B-02… (Boulevard) y O-01… (Plaza Motor).

## Notas de cobro (contratos sin factura)
Si el contrato tiene tipo de documento «Nota de cobro», el documento del mes se calcula sin IVA, **no va al XML de BSOFT** y se emite en PDF
desde el sistema: botón «Notas de cobro (PDF)» en Facturación (descarga un .zip del mes y las marca como emitidas; copia en `salidas/notas_cobro/`)
o el enlace en cada documento. La nota lleva los datos de pago de la sociedad (Carpetas y configuración).

## Numeración interna y folios del SII
Al aprobar, cada documento recibe un número interno correlativo por sociedad: facturas `BT-F-0001`, notas de cobro `BT-NC-0001`
(siglas: BT Boulevard Talca, QO 15 Oriente, IC Camarico; se cambian en Carpetas y configuración). El número no se reutiliza: si un documento
vuelve a borrador y se regenera, conserva su número. Después de emitir en BSOFT, se dejan los PDF de las facturas en la carpeta de facturas emitidas
de la sociedad; el sistema los lee (al encender o con «Leer carpeta ahora» en Facturación › Facturas emitidas), saca folio, RUT, fecha y montos
y los vincula con su documento por RUT + total. Lo que no calza queda «para revisar» y se vincula a mano. Así quedan unidos el n.º interno y el folio SII.
El formato exacto del PDF de BSOFT se confirma con el primer mes real (las reglas de lectura están en `facturacion/emitidas.py`).

## Panel web (uso diario)
Entrar a `http://127.0.0.1:8000/` (o la dirección de acceso remoto) con el usuario creado. Menú: **Inicio** (estado del mes y alertas) · **Facturación** (flujo
Generar → Revisar → Aprobar → Excel → XML) · **Cargas** (luz, gas, otros cargos y ventas netas) · **Contratos** (ficha con calendario de renta
y *simulador* de cualquier mes sin guardar nada) · **Alertas** · **Medidores** (confirmar asignaciones) · **UF / IPC** · **Administración** (solo staff: usuarios y datos maestros).
Roles: *Administrador* (todo, incluye forzar aprobaciones con advertencias y anular), *Operación* (genera, carga, aprueba, exporta),
*Contabilidad* (solo ver y descargar). Asignar el grupo a cada usuario en Administración → Usuarios.
Instalar como app: en Chrome/Edge «Instalar», en Android «Añadir a pantalla de inicio», en iOS Safari → Compartir → «Añadir a inicio».
(La instalación como app necesita https; por `http` solo se obtiene un acceso directo. Ver «https» en `ACCESO_REMOTO.md`.)

## UF e IPC: de dónde salen
`cargar_indicadores` (y el botón «Actualizar UF e IPC» del panel) prueba las fuentes en este orden y usa la primera que responda:
1. **Banco Central** (API de la Base de Datos Estadísticos), solo si existe el archivo `.token_bcentral` en la carpeta del sistema
   con el «API Key Token» personal (gratis: crear cuenta en si3.bcentral.cl, habilitar la API e ir a «Mi Cuenta»). Ese archivo es privado: no compartirlo.
2. **SII** (sii.cl › Valores y fechas): publica la UF diaria y el IPC oficial del INE. No necesita registro.
Cada consulta espera como máximo 10 segundos; la carga completa toma menos de un segundo. Por defecto carga el año actual
(en enero también el anterior y en diciembre también el siguiente). En la columna «Origen» queda `BCCH` o `SII` (`API` = mindicador.cl, la fuente antigua).

## Probar con datos de prueba
```
python manage.py datos_prueba            # (antes cargar al menos una UF real con cargar_indicadores)
#  UF diaria ficticia hasta 2027-06-30, IPC faltante y ventas de B-21/B-36/B-40 (todo marcado PRUEBA)
python manage.py quitar_datos_prueba     # borra solo lo marcado PRUEBA
```
Con eso se pueden generar noviembre 2026 (diferencia de renta variable de B-21 y B-36) y enero 2027 (semestral de B-39 con IPC) desde el panel,
y comparar cada documento con su cálculo a mano en la ficha del contrato (Simular). Los datos de prueba nunca se mezclan con UF/IPC reales (origen `PRUEBA`).
El IPC real se carga desde el SII (cifra oficial del INE) o el Banco Central y reemplaza al de prueba mes a mes, a medida que se publica
(el 8 de cada mes sale el del mes anterior). Los meses aún no publicados siguen con el valor de prueba.

## Pruebas
`python manage.py test` (105 pruebas: motor, flujo de borradores/aprobación, XML, luz, gas y otros cargos, vistas del panel, carga de UF e IPC,
carpetas de contratos, historial, lectura con IA (con un cliente simulado), numeración, notas de cobro y facturas emitidas).

## Producción en la nube (Render)
Guía completa en `docs/nube-render.md` (render.yaml, Google Drive por cuenta de servicio, verificación en dos pasos, mudanza de datos).

## Producción (nube + PostgreSQL) · notas anteriores
Variables de entorno: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_ORIGINS` (https del dominio) y `DATABASE_URL`
(`postgres://usuario:clave@host:5432/base`; instalar `psycopg[binary]`, ver `requirements.txt`). SQLite sirve para pruebas y modo oficina.
