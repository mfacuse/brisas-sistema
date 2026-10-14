# Sistema en la nube (Render) · guía de mudanza

Decisión del propietario (2026-10-14): el sistema pasa a Render, accesible desde cualquier navegador (Windows, macOS, iPhone/iPad,
Android) en `https://sistema.invercochile.com`, con verificación en dos pasos obligatoria.

## Qué queda en la nube
| Pieza | Plan Render | US$/mes aprox. |
|---|---|---|
| Sistema web (`brisas`, gunicorn) | Starter | 7 |
| Disco permanente 1 GB (`/var/data`: PDF generados, actas subidas, claves) | — | 0,25 |
| Base PostgreSQL 17 (`brisas-db`) | Basic 256 MB | ~6 |
| Tarea diaria (`brisas-diario`: UF/IPC + revisar carpetas, 8:00 de Chile) | Starter (cobro por minuto) | < 1 |
| **Total hosting** | | **≈ 15** (crece si se elige un plan mayor) |
Todo está descrito en `render.yaml` (Blueprint). Precios a confirmar en render.com/pricing al contratar.

## Diferencias con el modo oficina (Mac)
- Las carpetas (contratos, actas, planos, facturas emitidas) se leen de **Google Drive por internet** con la cuenta de Google de un
  administrador, autorizada una vez con «Conectar Google Drive» (solo lectura; Carpetas y configuración). Se eligió así porque la
  política de Inverco bloquea las claves de cuentas de servicio (`iam.disableServiceAccountKeyCreation`, 2026-10-14) y no se cambió.
  App OAuth «Brisas del Centro» (interna) en el proyecto Google Cloud «Sistema Facturacion», cliente web «Sistema Brisas» con
  regresos `http://localhost:8000/configuracion/drive/volver/` y `https://sistema.invercochile.com/configuracion/drive/volver/`.
  Ver `maestro/almacen.py` y `panel/vistas_drive.py`. (La cuenta de servicio sigue soportada como alternativa.)
- Las rutas guardadas pasan de `/Users/…` a `gdrive:<id>`; los vínculos archivo↔contrato y el historial se conservan
  (el sistema ya tenía el id de Drive de cada archivo).
- Ingreso: clave + código de 6 dígitos de una app del celular (Google/Microsoft Authenticator). Bloqueo 15 min tras 5 fallas.
- Respaldos: los de PostgreSQL de Render (diarios). `respaldar_bd` es solo para SQLite (Mac).

## Pasos
1. **Matías:** crear cuenta en github.com y un repositorio **privado** vacío (p. ej. `brisas-sistema`). Claude sube el código
   (sin datos: ver `.gitignore`).
2. ✅ (2026-10-14) Google Cloud: app OAuth interna + cliente web. Conectado en el Mac con mfacuse@invercochile.com; probado: lee por
   internet 57 contratos, 97 actas y los planos. En Render se vuelve a pegar el ID/secreto del cliente y se pulsa «Conectar» una vez
   (o se definen GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET en Render).
3. **Matías:** crear cuenta en render.com, registrar la tarjeta, «New › Blueprint» y elegir el repositorio. Pegar en el grupo
   `brisas-config` la clave de Anthropic (`ANTHROPIC_API_KEY`) y el ID/secreto del cliente de Google (`GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`).
4. **Claude:** exportar los datos (`preparar_nube` sobre una copia), cargarlos en Render (`loaddata` desde el «Shell» del servicio),
   revisar carpetas y planos desde Drive y probar todo con la dirección `xxxx.onrender.com`.
5. **Matías (5 min, con guía):** en GoDaddy › DNS agregar un registro CNAME `sistema` → la dirección que entregue Render;
   en Render › Settings › Custom Domains agregar `sistema.invercochile.com` (el certificado https es automático).
6. Cada usuario entra la primera vez y configura su verificación en dos pasos. El Mac deja de ser el servidor
   (se puede seguir usando como respaldo de consulta, sin cargar datos en ambos lados).

## Exportar e importar los datos
```
sqlite3 db.sqlite3 ".backup '/tmp/copia.sqlite3'"
DATABASE_URL=sqlite:////tmp/copia.sqlite3 python manage.py migrate
DATABASE_URL=sqlite:////tmp/copia.sqlite3 python manage.py preparar_nube --salida /tmp/brisas_nube.json
# en Render (Shell del servicio brisas), con el archivo subido al disco /var/data:
python manage.py loaddata /var/data/brisas_nube.json && python manage.py revisar_carpetas
```
Probado el 2026-10-14 con una base vacía: 1.956 registros, 48 contratos, 52 vínculos de locales, 537 cambios de historial,
69 archivos y 97 actas, idénticos al original.

## Simulación completa (2026-10-14)
Copia → `preparar_nube` → base nueva → `loaddata` → `revisar_carpetas` solo por Drive (`DJANGO_CARPETAS_RAIZ=""`): 0 archivos nuevos o
perdidos por la mudanza, 65 archivos con su contrato, 97 actas, planos reconstruidos (27 + 19 + 10 locales). ~47 s la primera vez
(descarga el plano de 250 MB); después solo relee lo que cambia.
