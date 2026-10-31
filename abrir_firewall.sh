#!/usr/bin/env bash
# ==========================================================================
#  Clase en Vivo UNACHI - reglas de firewall para Linux (ufw o firewalld)
#  Puertos: TCP 8080, 8889, 8189 · UDP 8189.  macOS: use el aviso del sistema.
# ==========================================================================
set -euo pipefail
if command -v ufw >/dev/null 2>&1; then
  for p in 8080/tcp 8889/tcp 8189/tcp 8189/udp; do
    sudo ufw allow from 192.168.0.0/16 to any port "${p%/*}" proto "${p#*/}" comment "Clase en Vivo UNACHI"
    sudo ufw allow from 10.0.0.0/8     to any port "${p%/*}" proto "${p#*/}" comment "Clase en Vivo UNACHI"
    sudo ufw allow from 172.16.0.0/12  to any port "${p%/*}" proto "${p#*/}" comment "Clase en Vivo UNACHI"
  done
  sudo ufw status | grep -i "clase" || true
elif command -v firewall-cmd >/dev/null 2>&1; then
  for p in 8080/tcp 8889/tcp 8189/tcp 8189/udp; do sudo firewall-cmd --add-port="$p"; done
  echo "Reglas temporales (hasta reiniciar). Para hacerlas permanentes: sudo firewall-cmd --runtime-to-permanent"
elif [[ "$(uname)" == "Darwin" ]]; then
  echo "macOS: al iniciar la clase, acepte el aviso 'Permitir conexiones entrantes' para mediamtx y python3."
else
  echo "No se detectó ufw ni firewalld; si usa iptables/nftables abra TCP 8080,8889,8189 y UDP 8189."
fi
