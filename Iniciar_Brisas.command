#!/bin/bash
# Doble clic para encender el sistema de Brisas del Centro en modo OFICINA:
# queda accesible para otras personas de la misma red (wifi/cable) y hace respaldos automáticos.
cd "$(dirname "$0")" || exit 1
clear
echo "=============================================="
echo "  Brisas del Centro · contratos y facturación"
echo "=============================================="
PUERTO=8000

# El entorno de Python vive fuera de Google Drive (Python no puede crearlo en una ruta con «:» y no lleva datos: se recrea solo).
VENV="${BRISAS_VENV:-$HOME/Brisas_python}"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "Preparando el sistema por primera vez (puede tardar unos minutos)..."
  python3 -m venv "$VENV" || { echo "No se pudo crear el entorno de Python en $VENV."; read -r -p "Presione Enter para cerrar"; exit 1; }
fi
source "$VENV/bin/activate"
export PYTHONDONTWRITEBYTECODE=1   # no llenar la carpeta de Drive con archivos temporales de Python

echo "Instalando/actualizando componentes..."
pip install -q -r requirements.txt

# Clave secreta propia de esta instalación (se crea una vez y se conserva)
if [ ! -f .clave_secreta ]; then
  python -c "import secrets; print(secrets.token_urlsafe(60))" > .clave_secreta
  chmod 600 .clave_secreta
fi
export DJANGO_SECRET_KEY="$(cat .clave_secreta)"
export DJANGO_DEBUG=0
export DJANGO_ALLOWED_HOSTS="*"

echo "Actualizando base de datos..."
python manage.py migrate -v0
python manage.py collectstatic --noinput -v0
python manage.py crear_roles >/dev/null
# Desde el 13-10-2026 los contratos entran solo por la carpeta de PDF (+ IA o a mano); la planilla de la Fase 0 ya no se importa al encender.
# Para volver a cargarla a mano: python manage.py importar_fase0

echo "Cargando UF e IPC oficiales (Banco Central o SII; necesita internet)..."
python manage.py cargar_indicadores 2>&1 | tail -6

echo "Revisando carpetas de contratos y de facturas emitidas..."
python manage.py revisar_carpetas 2>&1 | tail -8

# Respaldos: carpeta «Respaldos» dentro de la carpeta del sistema (en Google Drive: Mi unidad › Sistema Facturacion › Respaldos)
DEST="$PWD/Respaldos"
mkdir -p "$DEST"
echo "Respaldos en: $DEST"
python manage.py respaldar_bd --destino "$DEST" 2>&1 | tail -1

# Respaldo automático cada 6 horas mientras el sistema esté encendido
( while true; do sleep 21600; python manage.py respaldar_bd --destino "$DEST" >/dev/null 2>&1; done ) &
RESPALDOS_PID=$!
trap 'kill $RESPALDOS_PID 2>/dev/null' EXIT

# Si quedó encendida una copia anterior del sistema, se apaga
for pid in $(lsof -ti tcp:$PUERTO 2>/dev/null); do
  if ps -p "$pid" -o command= | grep -q -E "manage.py|waitress"; then kill "$pid" 2>/dev/null; fi
done
sleep 1

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
NOMBRE="$(scutil --get LocalHostName 2>/dev/null)"
echo
echo "=============================================="
echo "  SISTEMA ENCENDIDO"
echo "  En este computador:        http://127.0.0.1:$PUERTO/"
[ -n "$IP" ] && echo "  Desde otros equipos/celulares de la misma red:"
[ -n "$IP" ] && echo "                             http://$IP:$PUERTO/"
[ -n "$NOMBRE" ] && echo "                       o     http://$NOMBRE.local:$PUERTO/"
echo "  Mantenga esta ventana abierta; al cerrarla se apaga."
echo "  El computador no se dormirá mientras esté encendido."
echo "=============================================="
echo
(sleep 3; open "http://127.0.0.1:$PUERTO/") &
caffeinate -is python -m waitress --listen=0.0.0.0:$PUERTO --threads=8 config.wsgi:application
