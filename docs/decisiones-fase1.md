> Copia del documento «claude/decisiones-fase1.md» del Proyecto de claude.ai «Boulevard Talca», tomada el 2026-10-13.
> Si una decisión cambia, actualizarla aquí y en el Proyecto.

# Decisiones de la Fase 1 (facturación) · Brisas del Centro

Complementa «reglas-de-cobro-brisas-del-centro.md». Código y README en la carpeta `fase1/`.

## Electricidad, gas y otros cargos (confirmado por el propietario el 2026-10-09)

- El consumo de un mes se cobra en la factura del mes siguiente (consumo de septiembre → factura de octubre).
- Electricidad y gas se cobran a costo, sin recargo ni margen.
- Electricidad y gas llevan IVA como el arriendo, porque van como líneas de la misma factura afecta (en notas de cobro y facturas exentas siguen sin IVA).
- Además del arriendo, una factura puede llevar electricidad, gas y un «otro» genérico (concepto libre, con descuento en negativo). Se alimentan desde planillas mensuales:
  - Electricidad: «Facturacion_electrica_Brisas_<Mes>_<Año>.xlsx» (tres tablas: trifásicos BT-2, BT 4.3 y monofásicos BT 1; columna «A Facturar»).
  - Gas: «Facturación Gas Brisas <Mes> - <Año>.xls» (una hoja por mes; lecturas × 3,65 × tarifa más alta de Lipigas; columna «a facturar neto»).
  - Otros cargos: plantilla simple (Contrato, Concepto, Detalle, Neto, Mes de cobro).
- Cada fila de luz o gas se asigna a un contrato mediante la tabla de medidores; mientras un medidor esté «por confirmar», la factura queda con advertencia y no se aprueba sola.
- Septiembre 2026 (para octubre): electricidad $14.998.369 neto (34 medidores con cobro; Vía Láctea en $0) y gas $1.245.320 neto (5 contratos).

## Exportación a BSOFT

- Formato de entrega: XML «Arriendo_Automatico_V2.XML». Un `<Documento>` por factura: `Encabezado` con `RUTcliente` (sin puntos, con guion) y `glosaDocto`; luego un `<Detalle>` por línea con `NroLinDet`, `CodServicio`, `Cantidad` y `Valor`.
- Glosa del ejemplo: «Brisas del Centro Boulevard Talca Valor de la UF 41.065,38 del 01/10/2026 Octubre 2026 UF 9».
- 2026-10-09: el propietario pidió dejar la exportación al XML en pausa hasta tener la facturación 100 % validada.
- Pendiente para cerrarla: código de servicio por tipo de línea y sociedad (el ejemplo trae 1002 y 1003), significado de «UF 9» en la glosa, un archivo por factura o varias en uno, signo de los descuentos, cómo se elige afecta/exenta/nota de cobro al importar, y tildes en la glosa.

## Maestro de locales v3 (2026-10-09)

- Locales disponibles confirmados: L07, L13, L24, L33, L36 y L37.
- Sin aclarar: el propietario marcó «No» sin comentario en L02, L03, L28 y L41 (Supermercado); L04 quedó sin marcar.

## Hito 3 · Panel web y datos de prueba (2026-10-09)

- Instrucción del propietario: lo importante es que el sistema entienda la lógica; el cálculo exacto se valida después con datos de prueba.
- Panel propio (no el admin de Django): Inicio, Facturación (generar → revisar → aprobar → Excel → XML), Cargas (luz, gas, otros, ventas), Contratos (ficha + simulador de cualquier mes sin guardar), Alertas, Medidores, UF/IPC. Instalable como app (PWA).
- Roles: Administrador (todo; fuerza aprobaciones con advertencias y anula), Operación (genera, carga, aprueba, exporta), Contabilidad (solo ve y descarga).
- Datos de prueba (comandos `datos_prueba` / `quitar_datos_prueba`): UF diaria ficticia, IPC faltante y ventas de B-21, B-36 y B-40, todo con origen PRUEBA, separado de lo real.
- Lógica comprobada con datos de prueba: noviembre 2026, B-21 = 11 % × ventas octubre $66.960.000 = $7.365.600 menos mínimo octubre $5.749.153 → diferencia $1.616.447; B-36 diferencia $1.215.677. Enero 2027, B-39 semestral $2.500.000 × factor IPC 1,033499 = $2.583.749; B-40 variable recién desde 2027-01-01 (sin diferencia en enero).
- Octubre 2026 contra Fase 0: coinciden 42 de 48 contratos; las diferencias se explican por prorrata (B-13, B-20), gracia (B-07, B-11, O-06) y B-39 (semestral, no corresponde a octubre).
- Los borradores se calculan con lo que esté cargado en ese momento: si la luz o el gas se cargan después de aprobar, los documentos aprobados no los incluyen. El panel lo avisa (Cargas y Facturación) y ofrece «Volver aprobados a borrador» y luego «Regenerar borradores» (el regenerado solo toca documentos en borrador).
- 40 pruebas automáticas pasan. Entrega: `brisas_fase1_hito3.zip`.

## Modo oficina y acceso remoto (2026-10-09)

- Mientras dure la etapa de pruebas el sistema corre en un computador de la oficina (el MacBook de Matías, «macbook-neo»): opción B elegida por el propietario. La nube con PostgreSQL (opción A) queda para cuando terminen las pruebas.
- Se enciende con doble clic en `Iniciar_Brisas.command`: servidor de producción (waitress), DEBUG apagado y el Mac no se duerme mientras la ventana esté abierta. Si se cierra la ventana o se apaga el Mac, nadie puede entrar.
- Respaldo automático de la base al encender y cada 6 horas en Google Drive → Sistema Facturacion → Respaldos (se conservan las últimas 60 copias). La carpeta del sistema y `db.sqlite3` no van dentro de Drive porque la base se puede corromper.
- Acceso desde fuera de la oficina: red privada Tailscale (`macbook-neo.tail0e201c.ts.net`, puerto 8000) con la cuenta del propietario; no se publica abierto a internet (ni túneles públicos, ni Funnel, ni puertos del router), porque el sistema guarda datos de los arrendatarios. A cada persona del equipo se le comparte solo el Mac («Share…» en la consola de Tailscale) y se le crea su usuario con un rol. Guía en `fase1/ACCESO_REMOTO.md`.
- Según su página, el plan gratuito de Tailscale es para uso no comercial y hasta 6 usuarios: antes de sumar a todo el equipo conviene revisar el plan que corresponde.
- https (necesario para instalar el sistema como app en celulares) es opcional más adelante: requiere activar los certificados HTTPS en Tailscale y ejecutar `tailscale serve`.

## Estado de la Fase 1 al 2026-10-09

- Hecho: modelo de datos, importador de las planillas v2, motor de renta (UF, prorrata, gracia, renta variable, semestral con IPC, descuentos), borradores y aprobación con advertencias, Excel de revisión por sociedad, alertas, XML BSOFT (con códigos provisorios), carga de luz, gas y otros, panel web con roles y PWA.
- Octubre 2026, Boulevard: 37 facturas, neto $78.497.504 (arriendo $62.253.815, electricidad $14.998.369, gas $1.245.320). Plaza Motor: 7 facturas, neto $16.124.322. UF del 01-10-2026: $41.065,38.
- Pendientes: ventas reales de septiembre de SchopDog (B-21) y Santa Isabel (B-36); cargar en el panel la luz y el gas de septiembre (consumo 2026-09 → factura de octubre) y regenerar los borradores; confirmar la asignación de los 40 medidores (planilla «Revision_Medidores_2026-10-09.xlsx»); regla de prorrata cuando la renta cambia a mitad de mes (B-13 y B-20 en octubre); carga de ventas desde el Excel de RobFre; Excel de Megaservicios (facturado, pagado, en mora).
- IPC real: mindicador.cl devuelve 0 registros de IPC (la UF carga bien). Solo afecta a B-39 en enero 2027, y por ahora se usa el IPC de prueba.
- 2026-10-13: mindicador.cl dejó de responder (el encendido esperaba hasta 2 minutos). UF e IPC pasan a cargarse desde el Banco Central (si hay token)
  o, si no, desde el SII, que publica la UF y el IPC oficial del INE. Resuelto el IPC real: enero–septiembre 2026 y todo 2025 ya cargados con origen SII;
  octubre–diciembre 2026 siguen con el IPC de prueba hasta que el INE los publique. Los valores de UF del SII coinciden día a día con los que había.

## Carpetas de contratos, IA, notas de cobro y folios (2026-10-13)

- La carpeta de contratos de cada sociedad se elige desde el panel (no es una ruta fija) y se revisa al encender y con un botón: PDF nuevos,
  cambiados, movidos o eliminados. Boulevard: «Archivos Brisas del Centro › CONTRATOS › Contratos Vigentes» (57 PDF; 56 asociados solos por nombre,
  el de Megaservicios no es arriendo). 15 Oriente y Camarico: carpeta por elegir.
- Decisión del propietario: la IA (Claude, de Anthropic) lee los PDF y propone los datos; una persona aprueba campo por campo. El propietario aceptó
  que el texto de los contratos se envíe a Anthropic y el costo por lectura (≈ US$ 0,2–0,3 por contrato con Claude Opus 5.5).
- Debe quedar todo el historial de contratos y cambios: registro automático de cada cambio (quién, cuándo, desde dónde, antes → después) y de cada
  movimiento de archivos. Nada se borra.
- El tipo de documento (factura afecta, exenta o nota de cobro) va especificado en cada contrato y se puede editar en el panel. La nota de cobro se
  emite en PDF, sin IVA, y no va al XML de BSOFT (antes el XML las habría incluido).
- Numeración interna correlativa por sociedad al aprobar: BT-F-0001 (facturas) y BT-NC-0001 (notas de cobro). Siglas BT, QO (15 Oriente), IC (Camarico).
- Facturas emitidas: los PDF de BSOFT se dejan en una carpeta por sociedad; el sistema los lee y vincula n.º interno ↔ folio SII por RUT + total.
  El propietario aún no sabe cómo entrega BSOFT los PDF (uno por factura o todas juntas): el sistema acepta ambos; se valida con el primer mes real.
- 2026-10-13 (más tarde): a pedido del propietario se borraron todos los datos de contratos y facturación del sistema de trabajo para partir desde cero
  (48 contratos, 39 documentos de octubre, cargos, ventas, medidores, historial). Se conservaron usuarios, sociedades con sus carpetas, propiedades,
  locales y códigos BSOFT. La planilla de la Fase 0 ya no se importa al encender. Respaldo: `Respaldos/brisas_antes_de_borrar_todo_2026-10-13_2026.sqlite3`;
  archivos exportados de octubre en `Respaldos/salidas_antes_de_borrar_todo_2026-10-13/`.

- 2026-10-14: la fecha de la UF del mes se puede elegir a mano en Facturación (por sociedad y mes); por defecto el día 1. La fecha elegida se aplica a todos los contratos de la sociedad ese mes, incluidos los de «primer día hábil» (decisión del propietario).
- 2026-10-14: nuevos conceptos de cobro «Gastos comunes» y «Agua». La inmobiliaria los cobra en su factura (antes los gastos comunes los facturaba Megaservicios directo). Montos variables por arrendatario desde una planilla Excel mensual; con IVA igual que el arriendo. Para el agua se supuso la misma regla que luz y gas (consumo de M en la factura de M+1); pendiente confirmar con una planilla real.
- 2026-10-14: quién cobra gastos comunes y agua se define por contrato y por separado (Megaservicios directo o la inmobiliaria en su factura). Mientras no se marque, se asume Megaservicios (para evitar cobros dobles).
