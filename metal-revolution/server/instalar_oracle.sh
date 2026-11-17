#!/usr/bin/env bash
# Instala (o actualiza) el servidor de Metal Revolution en una maquina Linux de Oracle Cloud (Ubuntu u Oracle Linux).
#
#   curl -fsSLO https://raw.githubusercontent.com/Brilox/Escaner-de-puertos/claude/metal-revolution-multiplayer-server-kode3a/metal-revolution/server/instalar_oracle.sh
#   sudo bash instalar_oracle.sh                 # detecta la IP publica sola
#   sudo bash instalar_oracle.sh 123.45.67.89    # o se la dices tu
#
# Volver a ejecutarlo actualiza el codigo a la ultima version de la rama y reinicia el servidor.
# Las cuentas (cuentas.db) no se tocan.
set -euo pipefail

REPO="${MR_REPO:-https://github.com/Brilox/Escaner-de-puertos.git}"
RAMA="${MR_RAMA:-claude/metal-revolution-multiplayer-server-kode3a}"
PUERTO="${MR_PUERTO:-8080}"                  # TCP del juego y UDP de la pelea
PUERTO_PING=$((PUERTO - 1))                  # el juego hace el ping previo a la pelea a este puerto (UDP)
SERVICIO=metal-revolution

if [ "$(id -u)" -ne 0 ]; then echo "Ejecutalo con sudo:  sudo bash $0"; exit 1; fi
USUARIO="${SUDO_USER:-}"
if [ -z "$USUARIO" ] || [ "$USUARIO" = root ]; then
  if id ubuntu >/dev/null 2>&1; then USUARIO=ubuntu; elif id opc >/dev/null 2>&1; then USUARIO=opc; else USUARIO=root; fi
fi
CASA="$(getent passwd "$USUARIO" | cut -d: -f6)"
DESTINO="$CASA/mr-servidor"
SERVER_DIR="$DESTINO/metal-revolution/server"

echo "== 1/5 Paquetes (git, python3, cortafuegos)"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3 curl iptables-persistent >/dev/null
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q git python3 curl >/dev/null
else
  echo "No reconozco esta distribucion (ni apt-get ni dnf). Usa una imagen Ubuntu."; exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 8), sys.version' \
  || { echo "Hace falta Python 3.8 o mas nuevo"; exit 1; }

echo "== 2/5 Codigo del servidor (solo las carpetas server y datos de la rama $RAMA)"
if [ -d "$DESTINO/.git" ]; then
  sudo -u "$USUARIO" git -C "$DESTINO" fetch -q --depth 1 origin "$RAMA"
  sudo -u "$USUARIO" git -C "$DESTINO" reset -q --hard FETCH_HEAD
else
  # sin checkout primero: el repositorio tiene archivos grandes en la raiz que el servidor no necesita
  sudo -u "$USUARIO" git clone -q --depth 1 --filter=blob:none --no-checkout -b "$RAMA" "$REPO" "$DESTINO"
  sudo -u "$USUARIO" git -C "$DESTINO" config core.sparseCheckout true
  sudo -u "$USUARIO" git -C "$DESTINO" config core.sparseCheckoutCone false
  printf '/metal-revolution/server/\n/metal-revolution/datos/\n' | sudo -u "$USUARIO" tee "$DESTINO/.git/info/sparse-checkout" >/dev/null
  sudo -u "$USUARIO" git -C "$DESTINO" checkout -q "$RAMA"
fi
echo "   version: $(git -C "$DESTINO" log -1 --format='%h %s' | cut -c1-90)"

echo "== 3/5 IP publica"
IP="${1:-}"
if [ -z "$IP" ]; then
  IP="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)"
fi
if ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "No pude averiguar la IP publica. Pasala a mano:  sudo bash $0 TU.IP.PUBLICA"; exit 1
fi
echo "   los telefonos se conectaran a $IP:$PUERTO"

echo "== 4/5 Cortafuegos de la maquina: TCP $PUERTO, UDP $PUERTO_PING y UDP $PUERTO"
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd -q --permanent --add-port="$PUERTO/tcp" --add-port="$PUERTO_PING-$PUERTO/udp"
  firewall-cmd -q --reload
else
  abrir() { iptables -C INPUT -p "$1" --dport "$2" -j ACCEPT 2>/dev/null || iptables -I INPUT -p "$1" --dport "$2" -j ACCEPT; }
  abrir tcp "$PUERTO"; abrir udp "$PUERTO_PING"; abrir udp "$PUERTO"
  if command -v netfilter-persistent >/dev/null 2>&1; then netfilter-persistent save >/dev/null 2>&1 || true
  else mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.v4; fi
fi

echo "== 5/5 Servicio $SERVICIO (arranca solo al encender la maquina y se reinicia si se cae)"
cat > "/etc/systemd/system/$SERVICIO.service" <<EOF
[Unit]
Description=Servidor privado de Metal Revolution
After=network-online.target
Wants=network-online.target

[Service]
User=$USUARIO
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/env python3 mr_server.py --host $IP --port $PUERTO --log $SERVER_DIR/mr_server.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q "$SERVICIO"
systemctl restart "$SERVICIO"
sleep 3
if systemctl is-active --quiet "$SERVICIO"; then
  echo
  echo "LISTO: el servidor esta funcionando en $IP (TCP $PUERTO, UDP $PUERTO_PING y $PUERTO)."
  echo "  Ver el log en vivo:   tail -f $SERVER_DIR/mr_server.log"
  echo "  Reiniciar:            sudo systemctl restart $SERVICIO"
  echo "  Parar:                sudo systemctl stop $SERVICIO"
  echo "  Actualizar:           sudo bash $SERVER_DIR/instalar_oracle.sh"
  echo "Recuerda abrir esos mismos puertos en la Security List de Oracle (paso 4 de la guia)."
else
  echo "El servidor no arranco. Ultimas lineas:"; journalctl -u "$SERVICIO" -n 30 --no-pager; exit 1
fi
