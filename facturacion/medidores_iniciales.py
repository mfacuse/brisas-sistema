"""Asignación inicial de medidores/filas de las planillas de luz y gas a contratos.

Se armó a partir de las planillas de septiembre 2026 comparando local y nombre con el maestro. Todo queda como
«por confirmar» (confirmado=False) salvo lo que el propietario confirme en Admin → Medidores. Cuando el nombre de la
planilla no coincide con el nombre del contrato, la nota lo dice."""

# (servicio, «Nº Local» en la planilla, nombre en la planilla, tarifa, contrato, nota)
ELEC = [
    ('11-A', 'Via Lactea', 'BT 2', 'B-11', 'Local 11A (Farmacia San Daniel, entregado el 05-10-2026). Septiembre sin consumo; el nombre «Vía Láctea» es el ocupante anterior.'),
    ('1269', 'Inversiones Fox', 'BT 2', 'B-21', 'SchopDog (L22), contrato de Inversiones Fox Ltda.'),
    ('1257', 'Subway 1', 'BT 2', 'B-19', 'La planilla dice Subway pero el local 1257 es el L20 (hoy Comercializadora de Alimentos MP, B-20); Subway ocupa el L21 (1261).'),
    ('23', 'Brisa Salud', 'BT 2', 'B-22', ''),
    ('L 1', 'Mundo', 'BT 2', 'B-01', ''),
    ('Santa Isabel', 'Santa isabel', 'BT 4.3', 'B-36', ''),
    ('Local 1B', 'Ale Cosmeticos', 'BT 1', 'B-02', ''),
    ('Local 1210 (2)', 'Local MYM Gromer', 'BT 1', 'B-03', ''),
    ('Local 2 (3)', 'Local Chic Perfumeria', 'BT 1', 'B-05', ''),
    ('Local 1214 (4)', 'MYM PREMIUN', 'BT 1', 'B-04', 'Amimascota (el catastro lo llama «Caylo Premium»).'),
    ('Local 3 (5)', 'Local Fixstore', 'BT 1', 'B-06', ''),
    ('Local 6 (9)', 'Petunea', 'BT 1', 'B-09', 'Petunia.'),
    ('Local 7 (10)', 'Atico Libros', 'BT 1', 'B-10', ''),
    ('Local 8', 'Kay Shop', 'BT 1', 'B-08', ''),
    ('Local 1221 (11B)', 'DirecTV', 'BT 1', 'B-12', ''),
    ('Local 1225 (12)', 'L 1225 boba lola 2 nuevo ', 'BT 1', 'B-13', ''),
    ('Local 1233 (14)', 'Opticas Genesis', 'BT 1', 'B-14', ''),
    ('Local 1237 (15)', 'Euro Vision', 'BT 1', 'B-15', ''),
    ('Local 1241 (16)', 'Farmacia Vida Nueva', 'BT 1', 'B-16', ''),
    ('Local 216 (17)', 'Memos', 'BT 1', 'B-17', 'La planilla escribe «Local 216 (17)»; el 216 es el L25. Se asignó por nombre.'),
    ('Local 1257 (20)', 'Galletas nuevo', 'BT 1', 'B-20', 'Comercializadora de Alimentos MP (L20, 1257).'),
    ('Local 216 (25)', 'Emporio Lucila', 'BT 1', 'B-23', ''),
    ('Local 26', 'Curisa Niñez', 'BT 1', 'B-24', ''),
    ('Local 27', 'Kinesevic 2', 'BT 1', 'B-25', 'Exercise Science (L27); el nombre de la planilla es distinto.'),
    ('Local 38', 'Pilates', 'BT 1', 'B-28', 'Por local: L38 es Bravas 2.0 (B-28), pero la planilla dice Pilates.'),
    ('Local 39', 'Pilates', 'BT 1', 'B-29', 'Pilates (L39).'),
    ('L.211  LIMA RESTORANTE 1', 'Lima restorante', 'BT 1', 'B-26', 'Limeño (locales 30 y 31); dos medidores, un contrato.'),
    ('L.210  LIMA 2', 'Lima restorante 2', 'BT 1', 'B-26', 'Limeño (locales 30 y 31); dos medidores, un contrato.'),
    ('Local 209 (32)', 'Bravas Salon', 'BT 1', 'B-27', ''),
    ('Local S05 (S05)', 'Kanuky SpA', 'BT 1', 'B-35', 'Tanuki (S05); el nombre de la planilla es distinto.'),
    ('Local MOD A (A)', 'Tabaquería Kosss', 'BT 1', 'B-30', 'Koss (módulo A).'),
    ('Local MOD B (B)', 'Plata Fina 1', 'BT 1', 'B-31', 'Plata Fina (módulos B y C); dos medidores, un contrato.'),
    ('Local MOD C(C )', 'Plata Fina 2', 'BT 1', 'B-31', 'Plata Fina (módulos B y C); dos medidores, un contrato.'),
    ('Local MOD D (D)', 'Inversiones F', 'BT 1', 'B-32', 'Master Phone (módulo D); el nombre de la planilla es distinto.'),
    ('1253', 'Koishu', 'BT1', 'B-18', 'Bonlatte / Koishu (L18 y L19).'),
]
GAS = [
    ('', 'Cookies', '', 'B-20', 'Galletas / Comercializadora de Alimentos MP (L20); nombre distinto en la planilla.'),
    ('', 'Limeño', '', 'B-26', 'Se asignó a Limeño de los locales 30 y 31 porque ya tenía lectura desde julio; el Limeño nuevo (B-07, L6) se entregó el 14-09-2026.'),
    ('', 'Shopdog', '', 'B-21', 'SchopDog.'),
    ('', 'Memos', '', 'B-17', ''),
    ('', 'Sushi', '', 'B-18', 'Koishu (sushi), L18 y L19.'),
]
