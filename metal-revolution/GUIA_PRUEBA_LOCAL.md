# Guía: prueba local con amigos (opción 1)

Objetivo: que el juego arranque contra nuestro servidor corriendo en tu PC, con los teléfonos en la misma Wi-Fi.
Tiempo estimado: 30 a 45 minutos la primera vez.

## Parte A: preparar el PC (Windows)

1. **Instala Python 3.** Descárgalo de https://www.python.org/downloads/ y en el instalador marca la casilla
   "Add python.exe to PATH" antes de pulsar Install.
2. **Descarga el repositorio.** En GitHub, en tu repositorio, cambia a la rama
   `claude/metal-revolution-multiplayer-server-kode3a`, botón verde "Code", "Download ZIP". Descomprímelo,
   por ejemplo en `C:\mr`. Dentro verás la carpeta `metal-revolution`.
3. **Averigua la IP de tu PC en la Wi-Fi.** Tecla Windows, escribe `cmd`, Enter, y luego:
   ```
   ipconfig
   ```
   Busca el adaptador de Wi-Fi (o Ethernet si vas por cable) y apunta "Dirección IPv4", por ejemplo `192.168.1.35`.
   Esa IP es la que usaremos en todo lo demás. Si el router te la cambia otro día, habrá que regenerar el APK,
   así que si tu router lo permite, resérvala ("DHCP reservation") o pon IP fija en Windows.
4. **Arranca el servidor.** En la misma ventana de cmd:
   ```
   cd C:\mr\metal-revolution\server
   python mr_server.py --host 192.168.1.35 --port 8080
   ```
   (pon tu IP en lugar de 192.168.1.35). Debe salir algo como
   `escuchando en 0.0.0.0:8080 (los clientes usaran 192.168.1.35:8080)`. Deja esa ventana abierta.
5. **Firewall.** La primera vez Windows pregunta si permitir Python en la red: marca "Redes privadas" y Permitir.
   Si no preguntó y luego el teléfono no conecta, abre "Firewall de Windows Defender", "Configuración avanzada",
   "Reglas de entrada", "Nueva regla", Puerto, TCP, 8080, Permitir.
6. **Comprueba que escucha.** Desde el navegador del teléfono (en la misma Wi-Fi) entra a `http://192.168.1.35:8080`.
   La página saldrá vacía o con error, es normal, pero en la ventana del servidor debe aparecer una línea
   `conexion de (...)`. Si aparece, la red está bien. Si no aparece nada, es firewall o el teléfono está en otra red.

## Parte B: generar el APK que apunta a tu PC

Tienes dos caminos. El primero es el más fácil.

**Camino 1: lo genero yo.** Me dices tu IP (la del paso A3) y yo creo el APK ya parcheado y firmado y lo subo al
repositorio. Tú solo lo descargas e instalas.

**Camino 2: lo generas tú.** Necesitas las herramientas de firma de Android:
1. Instala Android Studio (https://developer.android.com/studio). Al abrirlo, "More Actions", "SDK Manager",
   pestaña "SDK Tools", marca "Android SDK Build-Tools" y acepta.
2. Localiza la carpeta de build-tools, normalmente
   `C:\Users\TU_USUARIO\AppData\Local\Android\Sdk\build-tools\34.0.0` y añádela al PATH de Windows
   (Configuración, "Editar las variables de entorno del sistema", Variables de entorno, Path, Nuevo).
3. Instala la librería de Python: en cmd, `pip install UnityPy`.
4. Reconstruye el APK del mod si no lo tienes suelto: une las cinco partes con 7-Zip (clic derecho en `.001`,
   Extraer aquí). El archivo resultante `metal offline.zip` es el APK: renómbralo a `metal_offline.apk`.
5. Genera el APK:
   ```
   cd C:\mr\metal-revolution\tools
   python parchear_cliente.py "C:\ruta\metal_offline.apk" 192.168.1.35 metal_online.apk
   ```
   Crea `mr.keystore` (guárdalo, sirve para firmar las versiones siguientes) y `metal_online.apk`.

## Parte C: instalar en los teléfonos

1. **Desinstala** el Metal Offline que tengan instalado. La firma es distinta y Android no deja actualizar encima.
   Antes de desinstalar, copia a un lugar seguro la carpeta del OBB:
   `Android/obb/com.gtarcade.next.mrglo/`. Al desinstalar, Android la borra.
2. Pasa `metal_online.apk` al teléfono (cable, Telegram, Drive, lo que sea) e instálalo. Acepta "instalar apps de
   origen desconocido" si lo pide.
3. Vuelve a poner el OBB en `Android/obb/com.gtarcade.next.mrglo/` igual que lo tenías con el mod.
4. Conecta el teléfono a la misma Wi-Fi que el PC. Los datos móviles apagados, para no confundirse.

## Parte D: la prueba

1. Con el servidor corriendo en el PC, abre el juego en un teléfono.
2. Mira la ventana del servidor. Lo esperado es ver, en este orden: una conexión `TGCP` con `-> ACK63`,
   `-> AUTHRSP54 + BINGO55`, y las tres consultas `QueryAddrSvr`, `DirService`, `VersionUpdate`; y después otra
   conexión con líneas `<- cmd=1 LoginRequest`, `cmd=92 QueryServerTimeReq`, etc.
3. Juega un poco: entra al menú, a una sala del hall, al entrenamiento. Cada pantalla genera comandos.
4. Prueba con un segundo teléfono a la vez.

## Lo que necesito que me mandes

1. El archivo `mr_server.log` que el servidor crea en la carpeta `server` (contiene todo lo que pasó).
2. Qué viste en el teléfono: hasta dónde llegó el juego, en qué pantalla se quedó cargando o qué error mostró.
   Una captura de pantalla ayuda.
3. Si usaste el camino 1, tu IP del paso A3 antes de empezar, para generarte el APK.

Con el log sé exactamente qué pidió el juego y qué le faltó, y con eso preparo la siguiente versión del servidor.
