# Metal Online en Vultr: guía paso a paso

Servidor recomendado para la beta: **Vultr Cloud Compute, High Performance (AMD), 1 vCPU, 2 GB de RAM, 50 GB NVMe,
3 TB de transferencia: US$12 al mes** (alternativa más barata: Regular Performance 1 vCPU / 2 GB / 55 GB, US$10).
Sobra para la beta: el relay en Go aguantó 200 peleas a la vez con 26 % de CPU. Revisa el precio en vultr.com/pricing
antes de contratar: cambia con el tiempo.

## 1. Cuenta y forma de pago
1. Entra a **vultr.com** → Sign up, con tu correo, y confirma el correo.
2. **Billing** → agrega una tarjeta con la opción **"link my credit card – $0.00 deposit"**. Vultr hace una retención
   temporal pequeña para verificarla (no es un cobro): la tarjeta necesita cupo para eso.
3. Se cobra por hora con tope mensual: el día 1 de cada mes se carga lo usado el mes anterior. **Apagar el servidor no
   detiene el cobro: para dejar de pagar hay que destruirlo.**

## 2. Crear el servidor
1. **Deploy +** → **Deploy New Server**.
2. Tipo: **Cloud Compute – Shared CPU**.
3. Ubicación: **Santiago** si la mayoría de los jugadores son de Chile, Argentina, Perú o Bolivia; **Miami** si hay
   muchos de México, Centroamérica, Colombia o Venezuela. Mira las banderas de la inscripción en #postulación-beta para
   decidir. (Después de la beta, `red_partidas.csv` dirá si conviene otra región.)
4. Imagen: **Ubuntu 24.04 LTS x64**.
5. Plan: **High Performance (AMD) – 1 vCPU, 2 GB, 50 GB NVMe – US$12/mes**.
6. **Auto Backups: desactivado** (cuesta un 20 % más; los respaldos los hacemos nosotros).
7. Server Hostname: `metal-online`. → **Deploy Now**.
8. Espera a que diga **Running** (1 o 2 minutos). En la ficha del servidor copia la **IP** y la **contraseña de root**
   (el ojo junto a Password). **La contraseña no se comparte con nadie, tampoco en el chat.**

## 3. Entrar al servidor desde tu PC
En Windows, abre **PowerShell** y escribe (con tu IP):
```
ssh root@TU.IP
```
- La primera vez pregunta si confías en el equipo: escribe `yes`.
- Pega la contraseña con **clic derecho** (no se ve mientras la escribes) y Enter.
- Quedas dentro cuando el cursor dice `root@metal-online:~#`.

## 4. Instalar Metal Online (un solo comando, unos 2 minutos)
Dentro del servidor:
```
curl -fsSLO https://raw.githubusercontent.com/Brilox/Escaner-de-puertos/claude/metal-revolution-multiplayer-server-kode3a/metal-revolution/server/instalar_vps.sh
sudo bash instalar_vps.sh
```
Hace todo solo: instala Python y git, crea 2 GB de memoria de respaldo, descarga solo lo del servidor (unos 10 MB),
abre los puertos (TCP 8080 y 8081, UDP 8079 y 8080; el panel no queda abierto a internet), pone la hora de Chile y deja
el servidor como servicio: arranca solo al encender y se reinicia si se cae.
Al final muestra **LISTO**, la **clave del panel** (guárdala) y si falta el OBB.

## 5. Subir el OBB (para las actualizaciones automáticas)
Desde **otra** ventana de PowerShell en tu PC (no dentro del servidor), con la ruta de tu OBB:
```
scp "C:\Users\BriloxSaw\Desktop\...\server\main.1300.com.gtarcade.next.mrglo.obb" root@TU.IP:/home/mo/mr-servidor/metal-revolution/server/
```
Son unos 870 MB: tarda según tu internet. Después, en la ventana del servidor:
```
systemctl restart metal-online
```

## 6. Panel de administración
El panel se conecta por un **túnel SSH** (más seguro que abrirlo a internet):
1. En PowerShell, en tu PC, deja esta ventana abierta mientras uses el panel:
   ```
   ssh -N -L 8090:127.0.0.1:8090 root@TU.IP
   ```
   (pide la contraseña y se queda "quieta": así funciona.)
2. Abre el panel como siempre (`tools\admin\abrir_panel.bat`): dirección `http://127.0.0.1:8090` y la clave del paso 4.
   Si el panel recuerda la clave de tu PC, cámbiala por la nueva.
3. Pestaña **Actualizaciones** → sube `metal_online_v7.mrupd` y espera **"paquete listo"**.

## 7. APK con la dirección del servidor
El APK actual apunta a tu PC. Con la IP del servidor se arma el APK nuevo (y el `MetalOnline.xapk`) que se conecta a
Vultr: pásale la IP a Claude. Se instala encima del anterior (misma firma).

## 8. Prueba
Con el APK nuevo, en el teléfono **con datos móviles** (no con el WiFi de la casa): entrar, ver que baje la
actualización, jugar una partida. Si algo falla, desde el servidor:
```
tail -n 200 /home/mo/mr-servidor/metal-revolution/server/mr_server.log
```

## Uso diario
| Para | Comando (dentro del servidor) |
|---|---|
| Ver el log en vivo (Ctrl+C para salir) | `tail -f /home/mo/mr-servidor/metal-revolution/server/mr_server.log` |
| Reiniciar | `systemctl restart metal-online` |
| Parar | `systemctl stop metal-online` |
| Estado | `systemctl status metal-online` |
| Actualizar a la última versión de la rama | `sudo bash /home/mo/mr-servidor/metal-revolution/server/instalar_vps.sh` |
| Respaldar cuentas a tu PC (en PowerShell del PC) | `scp root@TU.IP:/home/mo/mr-servidor/metal-revolution/server/cuentas.db .` |

Actualizar nunca borra `cuentas.db`, `clave_admin.txt`, la carpeta `actualizaciones/` ni el OBB.
