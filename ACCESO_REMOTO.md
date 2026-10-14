# Acceso al sistema desde otros equipos y desde fuera de la oficina

Estado al 2026-10-09 (tarde): el sistema corre en un solo computador (el «servidor», el MacBook Neo). Los demás entran por el navegador con su
usuario y clave. Los datos (contratos, RUT, rentas) quedan en ese computador; no se copian a los demás equipos.

## Lo que ya está listo
- El sistema está encendido en modo oficina (ventana negra «Iniciar_Brisas.command» abierta en el Mac) y el Mac no se duerme mientras esté así.
- El sistema y sus respaldos automáticos (cada 6 horas) están en Google Drive: Mi unidad → Sistema Facturacion (respaldos en la subcarpeta Respaldos).
- Tailscale (red privada) está instalado en el Mac con la sesión de mfacuse@gmail.com. El Mac aparece como «macbook-neo»:
  - Nombre: `macbook-neo.tail0e201c.ts.net`
  - Dirección: `100.78.125.82`
- Por lo tanto, cualquier equipo que esté en esa red privada puede abrir:
  **http://macbook-neo.tail0e201c.ts.net:8000/**   (o http://100.78.125.82:8000/)
  Desde ahí se entra con el usuario y la clave del sistema. Nadie fuera de esa red puede ver el sistema.

## Cómo conectar tu celular o tu otro computador (tú)
1. Instala la app **Tailscale** (iPhone: App Store · Android: Play Store · Windows/Mac: tailscale.com/download).
2. Inicia sesión con **la misma cuenta del Mac** (mfacuse@gmail.com). El Mac aparecerá en la lista de dispositivos.
3. Abre el navegador del equipo y entra a `http://macbook-neo.tail0e201c.ts.net:8000/`
4. Ingresa con tu usuario y clave del sistema.
En el celular puedes dejar un acceso directo: en el navegador, «Añadir a pantalla de inicio».
(La instalación como app «de verdad» necesita https; es un paso opcional más abajo.)

## Cómo darle acceso a otra persona del equipo
La forma más ordenada es **compartir solo el MacBook** con esa persona (no toda su red):
1. Entra a https://login.tailscale.com/admin/machines (con mfacuse@gmail.com).
2. En la fila de `macbook-neo`, menú «…» → **Share…** → copiar el enlace de invitación y enviárselo a esa persona.
3. La persona instala Tailscale, inicia sesión con su propia cuenta, acepta la invitación y abre la dirección de arriba.
4. Dentro del sistema, créale su usuario (Administración → Usuarios) y asígnale un grupo: Administrador, Operación o Contabilidad.
(Los pasos pueden variar un poco según la versión de la página de Tailscale. El plan gratuito de Tailscale indica ser solo para uso no comercial
y hasta 6 usuarios; para una empresa conviene revisar el plan que corresponde en https://tailscale.com/pricing.)

## Si alguien no logra entrar
1. ¿El Mac está encendido, con internet y con la ventana negra abierta? Si se cerró, se apagó el sistema: doble clic otra vez en Iniciar_Brisas.command.
2. ¿La persona tiene Tailscale abierto y «Connected»?
3. ¿El Mac bloquea conexiones entrantes? Ajustes del Sistema → Red → Firewall → Opciones: si el firewall está activado, debe permitir las
   conexiones entrantes de «python».
4. Mensaje «Session data corrupted» en la ventana negra: es normal después del cambio de clave de seguridad; basta con volver a iniciar sesión.

## Opcional más adelante: https (para instalar como app en celulares)
Requiere activar «HTTPS Certificates» en https://login.tailscale.com/admin/dns (Tailscale lo informa como un cambio que hace públicos en un
registro de certificados los nombres de los equipos de la red) y luego, en el Mac, `tailscale serve --bg 8000`
(`tailscale serve --help` muestra la sintaxis de su versión). La dirección pasaría a ser `https://macbook-neo.tail0e201c.ts.net/`.
Para apagar: `tailscale serve reset`.

## Lo que NO se recomienda
- Publicar el sistema abierto a todo internet (túneles públicos, «Funnel», abrir puertos del router): quedaría protegido solo por usuario y clave,
  y el sistema tiene datos sensibles de arrendatarios.
- Usar la carpeta del sistema (que está en Google Drive, con `db.sqlite3`) desde varios computadores a la vez: la base se puede corromper. El sistema se enciende solo en el
  Mac servidor y los demás entran por el navegador. Si algo falla, se restaura el último respaldo (Mi unidad › Sistema Facturacion › Respaldos).

## Límites de este modo
- Si el Mac servidor se apaga, se queda sin internet o se cierra la ventana negra, nadie entra.
- Es una etapa de pruebas. Para operar con todo el equipo conviene pasar a un servidor en la nube con PostgreSQL.
