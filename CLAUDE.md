# Brisas del Centro · contratos y facturación (sistema Django)

Sistema para controlar los contratos de arriendo y preparar la facturación mensual de dos propiedades de Grupo Inverco (Talca):
Brisas del Centro Boulevard (Inmobiliaria Boulevard Talca SpA, 76.388.311-6) y Plaza Motor (Inmobiliaria 15 Oriente SpA, 76.602.726-1).
Son unos 48 contratos y unos 70 documentos al mes. Panel web propio, en español, instalable como app (PWA).

## Cómo trabajar con Matías
- Matías Facuse es el dueño y no es programador: responde siempre en español, simple y sin jerga. Explica qué cambió y cómo comprobarlo en el panel.
- Los pasos técnicos (comandos, reinicios) los haces tú. Si algo debe hacerlo él, dile exactamente en qué botón o ventana.
- Antes de cambiar una regla de cobro, confírmala con él. Las reglas están en `docs/reglas-de-cobro-brisas-del-centro.md` y `docs/decisiones-fase1.md`.
- Toda regla nueva o cambiada lleva su prueba automática.

## Cómo está instalado hoy (importante)
- **Desde el 2026-10-14 el sistema de trabajo está en la NUBE (Render): https://brisas.onrender.com** (dominio sistema.invercochile.com
  pendiente: el DNS lo administra Hostname/INC, ns0X.inc.cl, no GoDaddy). Base PostgreSQL de Render; Drive conectado con la cuenta de Matías.
  Los cambios de código se suben a GitHub (mfacuse/brisas-sistema; el `git push` lo hace Matías) y Render los instala solo.
  El sistema del Mac quedó APAGADO y con datos antiguos (solo emergencias; el lanzador pide confirmar). Lo de abajo describe el modo oficina.
- El sistema corre en el MacBook de Matías, en esta misma carpeta, en «modo oficina»: doble clic en `Iniciar_Brisas.command` deja encendido waitress en el
  puerto 8000 con DEBUG apagado y hace respaldos de la base cada 6 horas en la subcarpeta `Respaldos/` de esta misma carpeta. Detalle en `README.md` y `ACCESO_REMOTO.md`.
- **Después de cambiar código hay que reiniciar el sistema** (cerrar la ventana negra del lanzador y volver a hacer doble clic); no se recarga solo.
- Para probar sin tocar el sistema encendido usa otro puerto: `python manage.py runserver 127.0.0.1:8001`. Ojo: comparte la misma base `db.sqlite3`.
- `db.sqlite3` tiene los datos de trabajo de Matías. Antes de cambiar datos o hacer una migración riesgosa: `python manage.py respaldar_bd --destino Respaldos`.
  Nunca borrar ni reemplazar `db.sqlite3`.
- Las demás personas entran por Tailscale (red privada) a `http://macbook-neo.tail0e201c.ts.net:8000/`. **No publiques el sistema abierto a internet**
  (túneles públicos, Funnel, puertos del router): hay datos de arrendatarios (RUT, rentas).
- Por decisión de Matías (2026-10-13) el sistema vive en Google Drive, **directo en Mi unidad › Sistema Facturacion** (sin subcarpeta «brisas»: él lo pidió así), con `db.sqlite3` incluida. Riesgo conocido: Drive sincronizando una base
  SQLite en uso puede corromperla. Por eso: un solo computador usa esta carpeta a la vez (el Mac servidor), no abrir ni editar `db.sqlite3` a mano, y respaldos cada 6 horas en `Sistema Facturacion/Respaldos`.
  Si algo falla con la base, restaurar el último respaldo.
- Ojo con Google Drive en este Mac: en `~/Library/CloudStorage` hay dos carpetas de la misma cuenta. La que **sí sincroniza** es `GoogleDrive-mfacuse@invercochile.com`;
  la que termina en «(26-06-26 7:25 p.m.)» es una copia vieja que Drive **no sube** (tiene el archivo `.drive_fs_ignore_preserved_domain`). Nunca usar esa.
- El entorno de Python **no** está en Drive sino en `~/Brisas_python` (así no se sincronizan miles de archivos que no son datos).
  No lleva datos; si se pierde, el lanzador lo recrea solo. Se enciende con `Iniciar_Brisas.command` o con el acceso «Encender Brisas» del Escritorio.
- `.clave_secreta` es la llave de seguridad de esta instalación: no mostrarla, no copiarla ni subirla a ningún repositorio.

## Comandos (primero: `source ~/Brisas_python/bin/activate`, y estar en la carpeta del sistema)
- Pruebas: `python manage.py test` (126 pruebas; deben pasar antes de dar algo por terminado).
- Del mes: `cargar_indicadores`, `cargar_consumos`, `generar_borradores AAAA-MM`, `aprobar_documentos AAAA-MM`, `exportar_excel AAAA-MM`, `exportar_bsoft AAAA-MM`, `alertas`.
  Los de facturación aceptan `--sociedad`. Ejemplos en `README.md`.
- Datos de prueba: `datos_prueba` y `quitar_datos_prueba` (todo queda con origen PRUEBA; nunca mezclar con UF/IPC reales).
- Roles: `crear_roles` (grupos Administrador, Operación y Contabilidad). Respaldo: `respaldar_bd`.
- Carpetas: `revisar_carpetas` (PDF de contratos nuevos/cambiados y facturas emitidas; corre al encender).
- Probar con una copia de la base sin tocar la de trabajo: `DATABASE_URL=sqlite:////ruta/copia.sqlite3 python manage.py ...`

## Nube (en preparación, 2026-10-14): Render, ver `docs/nube-render.md`
- Mismo código para Mac y nube. Carpetas vía `maestro/almacen.py` (Mac o `gdrive:<id>`). Drive se conecta con la cuenta Google de Matías
  (OAuth, solo lectura, botón en Carpetas y configuración; `panel/vistas_drive.py`): la política de Inverco bloquea claves de cuentas de servicio.
  Para conectar desde el Mac, abrir el sistema en http://localhost:8000 (no 127.0.0.1). `.google_*.json` son privados como `.clave_secreta`.
- `render.yaml`: web (gunicorn) + PostgreSQL + disco `/var/data` + tarea diaria `tareas_diarias`. Variables `DJANGO_HTTPS=1`, `DJANGO_2FA=1`.
- Verificación en dos pasos y bloqueo de ingreso en `panel/seguridad.py` (obligatoria solo si `DJANGO_2FA=1`). **Apagada en la nube desde el
  2026-10-14 por decisión de Matías mientras siga en desarrollo** (render.yaml `DJANGO_2FA=0`); reactivarla antes de pasar a uso normal.
- Respaldo diario (tarea 8:00 y botón «Respaldar ahora»): `maestro/respaldos.py` sube la base comprimida (.json.gz) a la carpeta «Respaldos sistema
  Brisas» de Mi unidad (permiso drive.file: solo archivos que crea el sistema; conserva 60). Se restaura con «Importar datos» en una base vacía.
  Permiso de Google, cliente y clave de IA se guardan en la base (`DatoSistema`) para que también los vea la tarea diaria.
- PostgreSQL (nube) rechaza textos más largos que su campo; SQLite no. `maestro/largos.py` recorta al guardar (y en las pruebas lanza
  `TextoMuyLargo` para descubrirlo). `bulk_create`/`.update()` no pasan por esa protección: usar `largos.ajustar()` si llevan textos de afuera.
- Mudanza de datos: `preparar_nube` (solo sobre una copia) + `loaddata`. Las claves privadas van en `BRISAS_SECRETOS_DIR`.

## Estructura
- `maestro/`: sociedades, propiedades, locales, arrendatarios, contratos, tramos de renta, descuentos y garantías. `importar_fase0` lee las planillas de `datos/`
  (desde el 2026-10-13 ya **no** corre al encender: Matías borró todos los contratos y documentos para partir desde cero y los contratos entran solo
  por la carpeta de PDF + IA o a mano; respaldo previo en `Respaldos/brisas_antes_de_borrar_todo_2026-10-13_2026.sqlite3`).
  `carpetas.py` revisa la carpeta de contratos de cada sociedad (elegida en el panel); `ia.py` lee PDF con Claude y propone cambios (nunca los aplica solo);
  `historial.py` registra todo cambio (señales + middleware). `.clave_anthropic` es privada, como `.clave_secreta`.
- `indicadores/`: UF e IPC oficiales. Banco Central (API BDE) si existe `.token_bcentral` (privado, como `.clave_secreta`); si no, o si falla, SII
  (publica la UF y el IPC del INE, sin registro). mindicador.cl se dejó de usar el 2026-10-13: no respondía y hacía lento el encendido.
- `facturacion/motor.py`: cálculo de rentas, **puro** (no toca la base de datos). `servicios.py` lo conecta con la base (borradores, aprobación, alertas).
  `lectores.py`, `cargas.py` y `medidores_iniciales.py` cargan luz, gas y «otros» desde las planillas. `exportar.py` genera el Excel y `bsoft.py` el XML.
  `nota_cobro.py` hace el PDF de las notas de cobro; `emitidas.py` lee los PDF de BSOFT y une n.º interno ↔ folio SII.
- `panel/`: pantallas, plantillas, roles (`permisos.py`) y PWA. `config/`: ajustes (variables de entorno `DJANGO_*`).

## Reglas que no se pueden romper (detalle en `docs/`)
- Renta en UF + IVA 19 %; UF del día 1 del mes (o del primer día hábil si el contrato lo dice, como Mundo). En Facturación se puede fijar a mano
  otra fecha de UF para una sociedad y mes (`FechaUFMes`): se aplica a TODOS sus contratos ese mes, incluso los de primer día hábil (Matías, 2026-10-14). Cálculo con `Decimal`, nunca `float`;
  redondeo al peso «mitad hacia arriba» (`peso()` en `motor.py`).
- Prorrata por días en el primer y el último mes y cuando la renta cambia a mitad de mes (modo PR; el modo IM aplica la renta vigente el día 1).
  Falta confirmar cuál corresponde a B-13 y B-20.
- Inicio de cobro (decisión de Matías, 2026-10-13): depende de cada contrato. Regla por contrato: según calendario, desde la entrega (+ días),
  desde la apertura, o «apertura o N días desde la entrega, lo primero». `fecha_inicio_cobro` se completa sola con la regla y las fechas
  (entrega/apertura) mientras nadie la fije a mano; antes de esa fecha no se cobra renta y el primer mes se prorratea por días.
- Código de contrato automático y correlativo por propiedad (B-01…, O-01…; letra en Propiedad.prefijo).
- Actas de entrega (Contratos › Actas de entrega): se suben una a una (PDF/foto), la IA rescata los datos, y «registrar» pasa la fecha de entrega al contrato.
- Renovación automática (confirmado 2026-10-13): terminado el último tramo, si el contrato tiene prórroga se sigue cobrando esa renta.
- Luz y gas: la planilla se lee con `lectores.py` (montos exactos, la IA nunca calcula dinero); cada fila se asigna por medidor confirmado y,
  si no hay, la IA propone el contrato (`asignacion.py`); se confirma en la pantalla «Revisar planilla» y queda como medidor confirmado.
  Las pruebas automáticas nunca usan la clave real de la IA (`settings.PRUEBAS`). Otros cargos: por archivo o a mano.
- Planillas: luz y gas aceptan el formato de Boulevard y, si no calza, el formato simple (`leer_generica`), que también usan agua y gastos
  comunes: detecta solo las columnas (local, nombre aunque no tenga título, «Nro cliente», consumo kWh/m³, lecturas y monto «$»/«Neto»).
  Si la hoja se llama como un mes («AGO26») y no coincide con el mes de consumo indicado, la carga se rechaza.
- Plano (menú «Plano»): `maestro/planos.py` lee los .dxf de la carpeta de planos de cada propiedad (al encender, solo si cambian): rótulo «LOCAL XX» +
  figura cerrada de la capa A-AUXILIAR. Verde ocupado, amarillo < 4 meses de vigencia, rojo vacío; clic → contrato. Boulevard: Sistema Facturacion/Boulevard/Planos
  (101 subterráneo y 201 elevaciones se omiten: sin locales). Plaza Motor: Sistema Facturacion/15 Oriente/Planos; su plano no trae contornos cerrados, se trazaron en `locales_plano.json` (misma carpeta). Vínculo contrato↔local en «Editar condiciones».
- Cargas: semáforo por local (luz/gas por consumo, otros por monto; mes vs anterior): verde ≤ 10 %, amarillo ≤ 20 %, rojo > 20 % (`comparacion.py`).
- Renta variable: el mes M cobra el mínimo de M más la diferencia entre (% × ventas netas de M-1) y el mínimo de M-1.
- Luz, gas y agua: el consumo del mes M se cobra en la factura de M+1, a costo, con IVA en facturas afectas; exentas y notas de cobro, sin IVA.
- Flujo Borrador → Aprobado → Exportado. Generar borradores solo recalcula los que están en Borrador: si se carga luz o gas después de aprobar,
  hay que usar «Volver aprobados a borrador» y regenerar. Una advertencia bloquea la aprobación (solo el Administrador la fuerza).
- Un documento por contrato y mes.
- Gastos comunes y agua (decisión de Matías, 2026-10-14): según cada contrato los cobra Megaservicios directo o la inmobiliaria en su factura
  (`Contrato.cobra_gastos_comunes` / `cobra_agua`, independientes; por defecto Megaservicios; pantalla «Quién cobra gastos comunes y agua»).
  Solo los de la inmobiliaria se cargan y facturan; los demás se marcan «lo cobra Megaservicios».
  Llegan en una planilla mensual, distinta por arrendatario; `lectores.leer_generica` detecta las columnas (local/nombre/neto; agua: m³ y lecturas).
  Se asignan como luz y gas (medidor confirmado + IA, con revisión). Con IVA igual que el arriendo; exentas y notas de cobro, sin IVA.
  Mes de la planilla → factura del mes siguiente (elegible al cargar). Faltan sus códigos de servicio BSOFT (AGUA, GGCC).
- Nota de cobro (tipo NC, definido en cada contrato y editable): sin IVA, no va al XML de BSOFT, se emite en PDF. Número interno correlativo por sociedad
  al aprobar (BT-F-0001 / BT-NC-0001), nunca se reutiliza.
- XML de BSOFT: cada `<Detalle>` lleva `<DscItem>` con el texto del cálculo (concepto + detalle, ASCII, máx. 1000; nombre en `bsoft.TAG_DETALLE`).
- La exportación XML a BSOFT quedó en pausa por instrucción de Matías (2026-10-09) hasta validar la facturación al 100 %; el código existe con códigos de servicio provisorios.

## Pendientes abiertos (ver `docs/decisiones-fase1.md`)
Ventas reales de septiembre de SchopDog (B-21) y Santa Isabel (B-36); confirmar los 40 medidores; regla de prorrata de B-13 y B-20; carga de ventas desde el Excel de RobFre;
Excel de Megaservicios; token del Banco Central (opcional); dudas del XML de BSOFT; clave de Anthropic para la IA;
carpetas de contratos de 15 Oriente y Camarico y carpetas de facturas emitidas (las elige Matías); validar la lectura del PDF de BSOFT con el primer mes real. Más adelante: correo (Gmail), WhatsApp, cobranza y pasar a la nube con PostgreSQL.
