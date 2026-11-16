# Servidor privado de Metal Revolution (fase 2)

Reproduce las respuestas grabadas del servidor original, igual que el servidor local del mod "Metal Offline V2",
pero en una máquina con IP pública para que varios teléfonos conecten al mismo sitio. Es el primer escalón:
con esto el juego arranca, hace login y llega al menú contra **nuestro** servidor. Las cuentas, estadísticas,
salas reales y el relay de combate vienen en las fases siguientes sobre esta misma base.

## Qué necesitas

- Un VPS Linux con IP pública (cualquier plan básico sirve) con el puerto TCP 8080 abierto.
- Python 3.10 o superior en el VPS. No hace falta ninguna librería extra.
- En tu PC: Python 3, `pip install UnityPy`, y las herramientas `zipalign` y `apksigner`
  (en Debian/Ubuntu: `sudo apt install zipalign apksigner`; en Windows vienen con Android Studio, en build-tools).

## 1. Arrancar el servidor en el VPS

```
git clone <este repositorio>
cd Escaner-de-puertos/metal-revolution/server
python3 mr_server.py --host IP_PUBLICA_DEL_VPS --port 8080
```

`--host` es la dirección que el servidor le dirá a los clientes para la fase de juego (puede ser un dominio).
El log muestra cada conexión y cada comando recibido con su nombre.

## 2. Crear el APK que apunta al VPS

Con el APK del mod (el archivo `metal offline.zip` reconstruido, que en realidad es un APK):

```
python3 ../tools/parchear_cliente.py "metal offline.apk" IP_PUBLICA_DEL_VPS metal_online.apk
```

El script cambia las tres cadenas `127.0.0.1` del objeto `GCloudConfig` por tu dirección, reconstruye el APK,
lo alinea y lo firma con un keystore nuevo (`mr.keystore`, clave `metalrevolution`). Guarda ese keystore:
todas las versiones futuras deben firmarse con el mismo para poder actualizar sin desinstalar.

## 3. Instalar y probar

- Desinstala el "Metal Offline" anterior (la firma es distinta, Android no deja actualizar encima).
- Instala `metal_online.apk`. Los OBB son los mismos que ya usas.
- Abre el juego con el VPS corriendo y mira el log: deberían aparecer la conexión TGCP (ACK, AUTHRSP, BINGO,
  las tres consultas del directorio) y luego la conexión del juego con `LoginRequest`, `QueryServerTimeReq`, etc.

Si el juego se queda cargando, el log dice en qué comando se quedó: es la información que necesitamos
para la siguiente iteración.

## Cómo funciona por dentro

- `blobs/`: 75 mensajes grabados del servidor original, extraídos de `libgame.so` del mod.
- Conexión TGCP (primer byte `0xAA`): paquete = `aa` + largo + TLV; el campo 9 de la cabecera dice cuántos
  bytes de datos Pebble/Thrift siguen. Se responde SYN→ACK63, AUTH→AUTHRSP54+BINGO55, y las peticiones del
  directorio por el nombre del método que contienen.
- Conexión del juego (primer byte `0x00`): `u16 tipo | u32 largo | tag2 seq | tag6 cmd | tag5 flag | tag4 payload`.
  El payload es FlatBuffers (`GameSvrReq` / `GameSvrRsp`, ver `protocolo.json`). Se responde con el blob grabado
  del mismo cmd copiando el seq; sin blob, un `EmptyRsp` (tipo de unión 2).

## Fase 2 (actual): cuentas, mesas, búsqueda de rival y clasificatoria

`mr_server.py` decodifica cada petición con el esquema FlatBuffers (`esquema_fb.json`, extraído del cliente) y la
despacha a `juego.py`. No hace falta instalar nada: la librería `flatbuffers` va incluida en `server/flatbuffers/`.

- **Cuentas** en `cuentas.db` (SQLite), una por teléfono (OpenId del login de invitado). La primera vez el servidor
  devuelve el nombre vacío y el juego abre su propia pantalla de crear jugador (`CreateRoleReq`). Nombres únicos.
  Con `--nombre-automatico` se asigna `JugadorNNNNN` sin preguntar. En el chat del hall o de la mesa,
  `/nombre NuevoNombre` cambia el nombre en cualquier momento.
- **Hall** "Sala Principal" con 8 mesas: entrar, sentarse en el lado izquierdo o derecho, observar, salir, clave y
  título de mesa (`SetRoomPasswordReq`), chat del hall (con historial) y de la mesa, mensajes privados.
- **Búsqueda de rival** (`StartSearchMatchReq`, cancelar con `ExitMatchReq`), una cola por modo:
  clasificatoria 1v1, normal 1v1, clasificatoria 2v2, clasificatoria 3v3 y normal 3v3.
- **Equipos 2v2**: invitar (`InvitePlayerToRoomReq`), aceptar, salir del equipo; el líder busca por los dos.
  Si faltan compañeros, la cola completa el equipo con jugadores sueltos.
- **Partida**: selección de personaje (uno o tres por jugador), escenario, carga, listos, fases con
  `NotifyMatchState`, abandono (cuenta como derrota si ya empezó la pelea, cancela si aún se elegía personaje).
- **Estadísticas y ranking**: victorias, derrotas, empates, experiencia y nivel por cuenta; puntos de
  clasificatoria por modo (empiezan en 1000, +25 al ganar, −20 al perder); tabla de posiciones
  (`QueryTopRankReq`, `QueryPlayerRankReq`); historial de partidas en la tabla `partidas`.
- Anuncio de bienvenida (`QueryServerAnnounceReq`), editable en `ANUNCIO` dentro de `juego.py`.
- Lo que no tiene handler se contesta con la grabación del mod si existe, y si no con `EmptyRsp`. Ningún error de
  un handler corta la conexión.

**Pendiente (fase 3): el relay del combate.** Al confirmar escenario, el servidor anuncia un `RelayServerInfo` que
apunta a sí mismo y registra en el log los paquetes UDP que lleguen, pero todavía no los reenvía. Hasta entonces
la pelea online entre dos teléfonos se quedará en la pantalla de carga.

Prueba sin teléfonos: `tools/cliente_prueba.py` implementa el protocolo del cliente (ver ejemplos en el historial).
Versión anterior (solo grabaciones): `mr_server_v1_replay.py`.
