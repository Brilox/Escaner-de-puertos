#!/usr/bin/env bash
# Instala (o actualiza) el servidor de Metal Online en un VPS con Ubuntu (Vultr; probado para Ubuntu 24.04 LTS).
#
#   (copia este archivo al servidor con scp desde tu PC: el repositorio es privado)
#   sudo bash instalar_vps.sh                 # detecta la IP publica sola
#   sudo bash instalar_vps.sh 123.45.67.89    # o se la dices tu
#
# Repositorio PRIVADO: el codigo se descarga con una llave de solo lectura del propio servidor ("deploy key").
# La primera vez el script crea la llave, la muestra y se detiene: la agregas en GitHub (repositorio -> Settings ->
# Deploy keys -> Add deploy key, SIN marcar "Allow write access") y vuelves a ejecutar el mismo comando.
# Para un repositorio publico sin llave:  sudo MR_REPO=https://github.com/Brilox/Escaner-de-puertos.git bash instalar_vps.sh
#
# Volver a ejecutarlo actualiza el codigo a la ultima version de la rama y reinicia el servidor.
# No toca lo que es tuyo: cuentas.db, clave_admin.txt, la carpeta actualizaciones/, el .obb ni los registros.
# Guia paso a paso: GUIA_VULTR.md
set -euo pipefail

REPO="${MR_REPO:-git@github.com:Brilox/Escaner-de-puertos.git}"
RAMA="${MR_RAMA:-claude/metal-revolution-multiplayer-server-kode3a}"
PUERTO="${MR_PUERTO:-8080}"                  # TCP del juego y UDP de la pelea
PUERTO_PING=$((PUERTO - 1))                  # el juego hace el ping previo a la pelea a este puerto (UDP)
PUERTO_HTTP="${MR_PUERTO_HTTP:-8081}"        # TCP: descargas de las actualizaciones automaticas
ZONA="${MR_ZONA:-America/Santiago}"          # hora de los registros
SERVICIO=metal-online

if [ "$(id -u)" -ne 0 ]; then echo "Ejecutalo con sudo:  sudo bash $0"; exit 1; fi
USUARIO="${SUDO_USER:-}"
if [ -z "$USUARIO" ] || [ "$USUARIO" = root ]; then
  if id mo >/dev/null 2>&1; then USUARIO=mo
  elif id ubuntu >/dev/null 2>&1; then USUARIO=ubuntu
  else
    # en Vultr se entra como root: el servidor corre con un usuario propio, sin permisos de administrador
    useradd -m -s /bin/bash mo; USUARIO=mo
  fi
fi
CASA="$(getent passwd "$USUARIO" | cut -d: -f6)"
DESTINO="$CASA/mr-servidor"
SERVER_DIR="$DESTINO/metal-revolution/server"

echo "== 1/6 Paquetes (git, python3) y hora ($ZONA)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 curl openssh-client >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3, 8), sys.version' || { echo "Hace falta Python 3.8 o mas nuevo"; exit 1; }
timedatectl set-timezone "$ZONA" 2>/dev/null || true

echo "== 2/6 Memoria de respaldo (swap de 2 GB, por si arma una actualizacion con poca RAM)"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "   swap creada"
else
  echo "   ya habia swap"
fi

if [[ "$REPO" == git@* ]]; then
  LLAVE="$CASA/.ssh/id_ed25519"
  if [ ! -f "$LLAVE" ]; then
    sudo -u "$USUARIO" mkdir -p "$CASA/.ssh"; chmod 700 "$CASA/.ssh"
    sudo -u "$USUARIO" ssh-keygen -q -t ed25519 -N "" -C "metal-online-vps" -f "$LLAVE"
  fi
  sudo -u "$USUARIO" touch "$CASA/.ssh/known_hosts"
  grep -q '^github.com ' "$CASA/.ssh/known_hosts" || { ssh-keyscan -t ed25519 github.com 2>/dev/null | sudo -u "$USUARIO" tee -a "$CASA/.ssh/known_hosts" >/dev/null; } || true
  if ! sudo -u "$USUARIO" git ls-remote -q "$REPO" "$RAMA" >/dev/null 2>&1; then
    echo
    echo "FALTA UN PASO: este servidor todavia no tiene permiso para leer el repositorio."
    echo "En GitHub: repositorio Escaner-de-puertos -> Settings -> Deploy keys -> Add deploy key"
    echo "  Title: vultr-metal-online     Key: copia la linea de abajo completa     NO marques 'Allow write access'"
    echo
    cat "$LLAVE.pub"
    echo
    echo "Despues vuelve a ejecutar:  sudo bash $0 ${1:-}"
    exit 2
  fi
fi

echo "== 3/6 Codigo del servidor (solo server, datos y tools/ifs de la rama $RAMA)"
if [ -d "$DESTINO/.git" ]; then
  printf '/metal-revolution/server/\n/metal-revolution/datos/\n/metal-revolution/tools/ifs/\n' > "$DESTINO/.git/info/sparse-checkout"
  sudo -u "$USUARIO" git -C "$DESTINO" fetch -q --depth 1 origin "$RAMA"
  sudo -u "$USUARIO" git -C "$DESTINO" reset -q --hard FETCH_HEAD
else
  # sin checkout primero: el repositorio tiene archivos grandes que el servidor no necesita
  sudo -u "$USUARIO" git clone -q --depth 1 --filter=blob:none --no-checkout -b "$RAMA" "$REPO" "$DESTINO"
  sudo -u "$USUARIO" git -C "$DESTINO" config core.sparseCheckout true
  sudo -u "$USUARIO" git -C "$DESTINO" config core.sparseCheckoutCone false
  printf '/metal-revolution/server/\n/metal-revolution/datos/\n/metal-revolution/tools/ifs/\n' | sudo -u "$USUARIO" tee "$DESTINO/.git/info/sparse-checkout" >/dev/null
  sudo -u "$USUARIO" git -C "$DESTINO" checkout -q "$RAMA"
fi
chmod +x "$SERVER_DIR"/bin/relay_go* 2>/dev/null || true
echo "   version: $(git -C "$DESTINO" log -1 --format='%h %s' | cut -c1-90)"

echo "== 4/6 IP publica"
IP="${1:-}"
if [ -z "$IP" ]; then
  IP="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)"
fi
if ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "No pude averiguar la IP publica. Pasala a mano:  sudo bash $0 TU.IP.PUBLICA"; exit 1
fi
echo "   los telefonos se conectaran a $IP:$PUERTO"

echo "== 5/6 Cortafuegos: SSH, TCP $PUERTO y $PUERTO_HTTP, UDP $PUERTO_PING-$PUERTO (el panel NO se abre: va por tunel SSH)"
if curl -fsS --max-time 3 -H "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/ >/dev/null 2>&1; then
  # Oracle Cloud: sus imagenes traen reglas iptables propias y Oracle recomienda NO usar ufw. Se agregan reglas antes
  # del REJECT final y se guardan. Ademas hay que abrir los mismos puertos en la Security List de la VCN (ver la guia).
  echo "   Oracle Cloud detectado: reglas iptables (sin ufw)"
  apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
  abrir() {   # la regla va justo antes del primer REJECT de INPUT (o al principio si no hay)
    iptables -C INPUT -p "$1" -m state --state NEW --dport "$2" -j ACCEPT 2>/dev/null && return 0
    local pos; pos=$(iptables -L INPUT --line-numbers -n | awk '$2=="REJECT"{print $1; exit}')
    iptables -I INPUT "${pos:-1}" -p "$1" -m state --state NEW --dport "$2" -j ACCEPT
  }
  abrir tcp "$PUERTO"; abrir tcp "$PUERTO_HTTP"; abrir udp "$PUERTO_PING"; abrir udp "$PUERTO"
  if command -v netfilter-persistent >/dev/null 2>&1; then netfilter-persistent save >/dev/null 2>&1 || true
  else mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.v4; fi
  ES_ORACLE=1
else
  if ! command -v ufw >/dev/null 2>&1; then apt-get install -y -qq ufw >/dev/null; fi
  ufw allow 22/tcp >/dev/null
  ufw allow "$PUERTO/tcp" >/dev/null
  ufw allow "$PUERTO_HTTP/tcp" >/dev/null
  ufw allow "$PUERTO_PING:$PUERTO/udp" >/dev/null
  ufw --force enable >/dev/null
  ufw status | sed 's/^/   /'
  ES_ORACLE=0
fi

echo "== 6/6 Servicio $SERVICIO (arranca solo al encender la maquina y se reinicia si se cae)"
systemctl disable --now metal-revolution 2>/dev/null || true      # nombre del instalador viejo
cat > "/etc/systemd/system/$SERVICIO.service" <<EOF
[Unit]
Description=Servidor de Metal Online
After=network-online.target
Wants=network-online.target

[Service]
User=$USUARIO
WorkingDirectory=$SERVER_DIR
ExecStart=/usr/bin/env python3 mr_server.py --host $IP --port $PUERTO --puerto-http $PUERTO_HTTP --log $SERVER_DIR/mr_server.log
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q "$SERVICIO"
systemctl restart "$SERVICIO"
sleep 4
if ! systemctl is-active --quiet "$SERVICIO"; then
  echo "El servidor no arranco. Ultimas lineas:"; journalctl -u "$SERVICIO" -n 30 --no-pager; exit 1
fi
OBB=$(ls "$SERVER_DIR"/*.obb 2>/dev/null | head -1 || true)
echo
echo "LISTO: Metal Online funcionando en $IP"
echo "  Juego: TCP $PUERTO   Pelea: UDP $PUERTO_PING y $PUERTO   Actualizaciones: http://$IP:$PUERTO_HTTP"
grep -h "relay Go\|relay en Python\|interruptores" "$SERVER_DIR/mr_server.log" 2>/dev/null | tail -3 | sed 's/^/  /' || true
if [ -z "$OBB" ]; then
  echo "  FALTA el OBB para las actualizaciones: subelo a $SERVER_DIR/ (paso 6 de GUIA_VULTR.md) y reinicia."
else
  echo "  OBB: $OBB"
fi
echo "  Clave del panel (pegala en el panel de administracion):"
echo "      $(cat "$SERVER_DIR/clave_admin.txt" 2>/dev/null || echo '(se crea al primer arranque: vuelve a mirar en unos segundos)')"
echo "  Ver el log en vivo:  tail -f $SERVER_DIR/mr_server.log"
echo "  Reiniciar / parar:   systemctl restart $SERVICIO   /   systemctl stop $SERVICIO"
echo "  Actualizar:          sudo bash $SERVER_DIR/instalar_vps.sh $IP"
if [ "${ES_ORACLE:-0}" = 1 ]; then
  echo "  ORACLE: abre tambien TCP $PUERTO,$PUERTO_HTTP y UDP $PUERTO_PING-$PUERTO en la Security List de la VCN (GUIA_ORACLE.md)."
fi
cp -f "$SERVER_DIR/instalar_vps.sh" /root/instalar_vps.sh 2>/dev/null || true
