> Copia del documento «claude/reglas-de-cobro-brisas-del-centro.md» del Proyecto de claude.ai «Boulevard Talca», tomada el 2026-10-13.
> Si una regla cambia, actualizarla aquí y en el Proyecto.

# Reglas de cobro Brisas del Centro (levantadas el 2026-10-07; actualizadas el 2026-10-09)

Fuente: contrato Local 25 (Emporio de Lucía), planillas de facturación de la carpeta compartida, respuestas del propietario a las 24 preguntas iniciales, a 6 preguntas adicionales (N1 a N6) y a los 33 hallazgos de la Fase 0, y lectura de los 67 contratos vigentes. Documento completo con propuesta de sistema, decisiones y hoja de ruta: https://claude.ai/artifact/6Y5vTu7fwpUwxkMbL5rCYu

## Reglas de cobro

- Renta base en UF + IVA, mes adelantado, dentro de los 5 primeros días (algunos contratos: 10 días, o 5 días hábiles con la UF del primer día hábil, como Mundo); UF del día 1 del mes.
- Renta escalonada por año de contrato (ej. Vía Láctea 60/70/80 UF; Bonlatte 53,5/62,75/70 UF).
- Inicio de renta: apertura o 60 días tras la entrega, lo primero; primer mes prorrateado por días. Cada contrato nuevo fija su propia regla (San Daniel: apertura o 90 días tras poner a disposición 5 documentos; +56 Food y Limeño: período de gracia con primer pago el 01-11-2026), por lo que el sistema debe guardar fecha de entrega, fecha de apertura y fecha de primer cobro por contrato.
- Renta variable: mayor entre mínimo UF y % de ventas netas (Santa Isabel 2% de las ventas netas del mes anterior; SchopDog 11% con mínimo 140 UF; RobFre estacionamientos Boulevard 50% de los ingresos netos con mínimo $2.000.000 + IVA). Hoy Santa Isabel paga el mínimo (333,33 UF) porque el 2% no lo supera.
- Renta variable, mecánica (confirmada): cada local informa sus ventas por correo; en el mes M se factura el mínimo de M más la diferencia, si la hay, entre el variable calculado con las ventas de M-1 y el mínimo de M-1.
- Ventas informadas (respuestas del 09-10-2026): el sistema debe permitir ingresar las ventas netas mensuales de Santa Isabel (para compararlas con el mínimo) y cargar la planilla Excel auditable de ingresos que RobFre informa en los primeros 10 días de cada mes.
- Gastos de administración (GGCC): los factura y cobra directamente Megaservicios Talca SpA a cada arrendatario, mes vencido, con monto variable (referencia contractual 0,12 a 0,16 UF/m² + IVA según contrato; Brisas Salud paga costo real). El sistema no los emite: muestra lo facturado, pagado y en mora que informe Megaservicios (confirmado de nuevo el 09-10-2026), a partir de un Excel básico. Por contrato de administración (01-12-2017) la inmobiliaria asume hasta 2 meses de mora por local y entregó una provisión de 450 UF.
- m² de base para cobro y gastos comunes: el m² del contrato (decisión del 09-10-2026); los m² de fichas y catastro son referencia.
- Electricidad (tarifas CGE BT-1, BT-2, AT 4.3) y gas (m³, factura Lipigas) por medidor, un medidor por local; llegan en un Excel del proveedor y se cobran a costo.
- Reajuste: la mayoría de los contratos se pacta en UF (ya incorpora IPC). Debe existir la opción de renta en pesos reajustable por IPC mensual, trimestral o anual (Bimedia: IPC cada enero, pago semestral el 1 de enero y el 1 de junio). El sistema debe permitir programar reajustes y alertas.
- Descuentos y reajustes: se definen por períodos determinados y el sistema los aplica solo (ej. acuerdos de renta temporal: Ale Cosméticos 27 UF jul–dic 2026; Amimascota 27 UF sep-2026 a feb-2027).
- Mora: multa 5% del impago, que se cobra muy excepcionalmente (se agrega a mano); dos atrasos en un año permiten terminar el contrato. El sistema muestra la cláusula de mora de cada contrato y avisa según lo que establezca cada uno.
- Garantía: una renta mínima mensual, reajustable por UF; varios contratos no tienen garantía (Brisas Salud, Santa Isabel, Bimedia, AutoPlanet y RobFre Plaza Motor, confirmado).
- Plazo 36 meses, renovación anual automática salvo aviso certificado a 60 días; el plazo de aviso varía por contrato y las alertas lo usan.
- Estados de cuenta: por contrato (no por grupo de arrendatarios relacionados). Se factura con el RUT del contrato.

## Documentos y sociedades

- Documentos: factura afecta (19%), factura exenta y nota de crédito. Los contratos de propiedades menores o habitacionales van sin factura: se emite una nota de cobro sin IVA (no DTE), con detalle similar a una factura, en PDF y por correo.
- Sociedades que facturan, con sesiones separadas en BSOFT: Inmobiliaria Boulevard Talca SpA (76.388.311-6) e Inmobiliaria 15 Oriente SpA (76.602.726-1).
- Propiedades: Brisas del Centro Boulevard (Inmobiliaria Boulevard Talca SpA) y Plaza Motor (Inmobiliaria 15 Oriente SpA; en los planos «StripCenter 1 Norte 15 Oriente»). Sistema multi-sociedad y multi-propiedad. El sistema debe permitir subir contratos nuevos.
- Volumen: unos 70 contratos y 70 facturas al mes.
- Formato real de la factura de Boulevard (visto en el Drive): «FACTURA ELECTRONICA Inmobiliaria Boulevard SpA», giro «Arriendo Inmuebles Amoblados», líneas ARRIENDO y ENERGIA ELECTRICA, encabezado «Mes UF xx, valor de la UF del 01/mm/aaaa», dirección tipo «1 NORTE 1209 LOCALES 210 211 BOULEVARD». Además Boulevard factura cada mes a Megaservicios «energía eléctrica, área común» (≈ $1,3 a 2,1 millones netos); por confirmar.

## Decisiones de alcance

- 2026-10-07: el formato de importación de BSOFT queda para una segunda etapa. La primera etapa entrega un Excel de facturación genérico, una línea por concepto, por sociedad.
- Prioridad declarada: llevar el control de los contratos y generar la facturación.
- Correo por Gmail de Google Workspace, con plantillas editables. WhatsApp mediante enlace con mensaje preparado (sin API). Los contratos autorizan los avisos por correo y WhatsApp.
- Usuarios: 3 o 4, con roles de administrador, operación (facturación, cobranza, registros y contratos) y contabilidad. Acceso de arrendatarios no solicitado por ahora.
- Migración: contratos vigentes, saldos abiertos y últimos 24 meses de facturación.
- 2026-10-07: el propietario entregó las plantas de Boulevard (3 pisos), el certificado de numeración municipal, las fichas de venta de los locales y, para Plaza Motor, la planta de arquitectura y el Excel de características. El sistema las usará como base de locales y para un mapa interactivo por piso, coloreado por estado (arrendado, disponible, en mora, por vencer).
- 2026-10-09: el maestro de locales se construye a partir de los contratos (no del catastro); Megaservicios se incluye en el maestro de contratos como contrato de servicio.

## Fase 0: lectura de los contratos vigentes (versión 2, 2026-10-09)

- Se leyeron 67 PDF (57 de Boulevard y 10 de Plaza Motor) más facturas y contratos del Drive para verificar. Resultado: planilla «Revision_Contratos_Brisas_2026-10-09_v2.xlsx» con 48 contratos (40 Boulevard y 8 Plaza Motor), 116 tramos de renta, contraste con el catastro de junio 2025, 44 hallazgos (los 33 originales con las respuestas del propietario: 25 resueltos y 8 parciales; más 11 preguntas nuevas: 3 altas, 7 medias y 1 baja), hojas Saldos y Servicios.
- Renta fija o mínima vigente al 09-10-2026: 1.860 UF/mes (Boulevard 1.467 UF, Plaza Motor 393 UF) más $2.000.000 mensuales de los estacionamientos de Boulevard; unos $79 millones al mes sin IVA con la UF del 01-10-2026 ($41.065,38). Baja respecto de la v1 (2.137 UF) por las respuestas: Brisas Salud paga 140 UF (no 237,3), Subway 40 UF (ocupa solo el Local 21, 46,4 m²), y San Daniel, Limeño Local 6 y +56 Food aún no devengan renta.
- Respuestas aplicadas del propietario: Amimascota (B-04) 27 UF sep-2026 a feb-2027 y 32 UF después, garantía 28 UF; Ale Cosméticos 27 UF jul–dic 2026 y 33 UF desde ene-2027; Subway 38 UF (2024), 39 (2025), 40 (2026), RUT 76.624.561-7; Kai Shop y Ático Libros 20 UF el 2.º año; AutoPlanet 478 m² con entrega 02-06-2017; 56 Market 40 UF desde nov-2025; Bimedia 47 meses con pagos el 1 de enero y el 1 de junio; SchopDog renovado sin opción de compra del leasing; Exercise Science en el Local 27 (39,3 m²); Boba Lola solo en el Local 12; Kasian (L7) y Brown Barber (L36) ya no operan; La Fontana ya no está en el centro; direcciones L16 = 1241, L17 = 1245, L32 = 209, L33 = 208. Fechas de entrega: San Daniel 05-10-2026, Limeño Local 6 14-09-2026, +56 Food 15-09-2026, RobFre Boulevard 23-09-2026.
- Saldos adeudados informados: Brisas Salud 1.960 UF; Bonlatte/Koishu $13.422.598 (contrato vigente).
- Tipos de renta que el sistema debe soportar: fija en UF escalonada por año, mínimo en UF o % de ventas, mínimo en UF por m² o % de ventas (Santa Isabel), mínimo en pesos o % de ingresos (RobFre), fija en pesos por semestre con IPC anual (Bimedia) y pesos que pasan a UF (RobFre Plaza Motor). También cesiones de contrato (Locales 2, 4 y 15), anexos, modificaciones y acuerdos de renta temporal sin documento.
- Plazos de aviso de no renovación: 30, 60, 90, 120, 180 y 365 días; AutoPlanet es plazo fijo de 20 años sin renovación.
- Local 4 (Amimascota): los tres archivos de la cesión no son idénticos; el definitivo es «ULTIMO» (firmado el 26-03-2026). Los dos PDF de Santa Isabel son escaneos sin texto (14 MB) que no se pudieron comparar.
- Contrato Megaservicios Talca SpA (01-12-2017, vigencia indefinida, 6 meses de aviso, honorario $1.100.000 + IVA inicial): factura gastos comunes directo a cada arrendatario; la inmobiliaria asume hasta 2 meses de mora por local; provisión de 450 UF; informe mensual en los primeros 5 días.
- Preguntas abiertas (ronda 2): Factura N° 5148 de RobFre (05-10-2026, $2.000.000 + IVA) vs «aún no se emite la primera factura»; fecha del acuerdo de 140 UF de Brisas Salud; fecha de entrega de documentos y apertura de San Daniel (renta desde ≈03-01-2027 si los documentos se entregaron el 05-10); gracia de Limeño y años de +56 Food; renta de Subway entre 06-2022 y 12-2023; versiones del contrato Santa Isabel y fecha de entrega (18-07-2016 catastro vs 01-08-2016 modificación); rentas de B-06, B-26, B-31, B-33, B-34, B-35, B-38 y O-04 sin respuesta; confirmar Locales 7, 13, 24, 33 y 36 disponibles; plazo renovado de SchopDog; flujo real con Megaservicios.

## Maestro de locales: fuentes y numeración (versión 2, 2026-10-09)

Archivo: «Maestro_Locales_2026-10-09_v2.xlsx» (hojas Boulevard y Plaza_Motor, cruzadas con la planilla de contratos). Reemplaza al catastro de junio 2025, que queda solo como referencia.

- Boulevard, fuentes: certificado de numeración municipal N° 31492 (Dirección de Obras de Talca, 07-10-2016; rol matriz 742-1; permiso N° 187 del 10-07-2015; recepción parcial N° 68 del 09-06-2016) con 49 unidades (26 en el primer piso, 18 en el segundo y 5 en el subterráneo, incluidos 3 accesos peatonales), y fichas de venta INGECO del 08-06-2016 con los m² oficiales. El maestro cuadra con el certificado.
- Cada local tiene dos números que el sistema debe guardar: el del plano (L01 a L40, S01 a S05) y el municipal (calle y número, «Lc interior N» o «Local 2NN»). En el segundo piso, Local 2NN = plano L(41 − NN). Los contratos usan la designación municipal, no el número de plano.
- Fuera del certificado: supermercado (Local 41, 1.554 m²), módulos A a E bajo la escalera, módulos del pasillo central, pantalla LED y estacionamiento subterráneo. L01 está subdividido en 1A (100,8 m²) y 1B (38,5 m²).
- Aclarado en v2: Subway ocupa solo el L21 y Comercializadora de Alimentos MP el L20; Bravas en el L32 (dirección 209); Boba Lola solo en el L12; Exercise Science en el L27. Disponibles sin contrato: L7 y L36 (confirmado), L13, L24 y L33 (por confirmar).
- Plaza Motor, fuentes: planta de arquitectura 16862ARPL04 (NUDO Ingenieros, 1:100, 08-02-2017; el DWG no se pudo abrir) y Excel «Resumen características de locales comerciales 15 Oriente». 10 locales en el plano (L4 y L5 son un solo recinto de 356,59 m²), 1.268,87 m² as built; la hoja de requerimientos trae amperaje, potencia y tarifa eléctrica por local.
- Plaza Motor, numeración: los contratos usan 101 a 110 = 111 − número del plano (confirmado en seis contratos). Global Truck dice «Local 8» y se asignó el 103 por la superficie, por confirmar. Los m² de los contratos son los as built.
- Plaza Motor, pendientes: el recinto L4 + L5 y el L6 no tienen contrato en la carpeta; el plano numera unos 39 estacionamientos y el contrato de RobFre no indica cantidad.

## Pendiente

- El propietario debe responder las 11 preguntas nuevas (hojas «Hallazgos» N° 34 a 44) y cerrar los 8 hallazgos parciales; con eso queda el maestro depurado (versión 3).
- Contratos adicionales de Plaza Motor (L4 + L5 y L6), si los hay.
- DXF o DWG legible de las plantas de Boulevard y Plaza Motor, si se quiere el contorno exacto de cada local en el mapa; mientras tanto el mapa se arma con los PDF.
- Muestras para la Fase 1: Excel de Megaservicios, Excel de electricidad y gas, correos de ventas, cartola bancaria.
- Formato de importación de BSOFT (segunda etapa).
