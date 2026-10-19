#!/bin/bash
# Sesiones de Claude Code en la nube (app de Claude en iPad/iPhone o claude.ai/code): instala lo que el sistema
# necesita para correr las pruebas. En el Mac de Matías no hace nada (allí se usa ~/Brisas_python).
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-.}"
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
  || python3 -m pip install --quiet --disable-pip-version-check --user -r requirements.txt >/dev/null 2>&1 \
  || echo "Aviso: no se pudieron instalar las dependencias (pip install -r requirements.txt)." >&2
exit 0
