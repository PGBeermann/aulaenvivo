#!/usr/bin/env bash
# ==========================================================================
#  Clase en Vivo UNACHI - arranque para Linux y macOS
#  Requiere Python 3.8+.  Parametros: --ip 192.168.1.50 --puerto-web 8081 --sin-navegador
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
  echo "[ERROR] Se requiere Python 3.8 o superior."
  echo "  Debian/Ubuntu: sudo apt install python3     macOS: xcode-select --install  (o brew install python)"
  exit 1
fi

echo
echo " Iniciando Clase en Vivo UNACHI..."
echo " (La primera vez se descarga MediaMTX; se necesita Internet solo en ese momento.)"
echo " En macOS, si aparece el aviso del firewall para 'mediamtx' o 'python', pulse 'Permitir'."
echo
exec "$PY" servidor_clase.py "$@"
