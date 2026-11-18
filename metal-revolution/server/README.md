# Servidor privado de Metal Revolution (fase 3)

Reproduce las respuestas grabadas del servidor original, igual que el servidor local del mod "Metal Offline V2",
pero en una máquina con IP pública para que varios teléfonos conecten al mismo sitio. Es el primer escalón:
con esto el juego arranca, hace login y llega al menú contra **nuestro** servidor. Las cuentas, estadísticas,
salas reales y el relay de combate vienen en las fases siguientes sobre esta misma base.

## Qué necesitas

- Un VPS Linux con IP pública (cualquier plan básico sirve) con el puerto TCP 8080 abierto y los puertos
  **UDP 8079 y 8080** (8080 para la pelea; 8079 para el ping previo, que el juego manda al puerto de la pelea menos uno).
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
- **Partida**: selección de personaje (uno o tres por jugador), escenario, carga, resultado, revancha, volver a
  elegir personaje y abandono (derrota si ya empezó la pelea; si aún se elegía personaje, se cancela sin puntos).
  El servidor solo reenvía cada acción al rival (`NotifyOtherSelectChar`, `NotifyOtherConfirmSelectChar`,
  `NotifyOtherConfirmSelectStage`, `NotifyOtherSyncLoadingProgress`...): el cambio de pantalla lo decide cada
  teléfono. `NotifyMatchState` no se usa en el flujo normal porque en el cliente es el camino de reconexión.
- **Mesas con sala de espera**: el primero que se sienta queda esperando; cuando se sienta el segundo, los dos
  reciben `NotifyGameHallMatchCreated` y pasan a la vez a elegir personaje. Detalle en `Mesa.detalle()`.
- **Estadísticas y ranking**: victorias, derrotas, empates, experiencia y nivel por cuenta; puntos de
  clasificatoria por modo (empiezan en 1000, +25 al ganar, −20 al perder); tabla de posiciones
  (`QueryTopRankReq`, `QueryPlayerRankReq`); historial de partidas en la tabla `partidas`.
- Anuncio de bienvenida (`QueryServerAnnounceReq`), editable en `ANUNCIO` dentro de `juego.py`.
- Lo que no tiene handler se contesta con la grabación del mod si existe, y si no con `EmptyRsp`. Ningún error de
  un handler corta la conexión.

## Fase 3 (actual): la pelea en tiempo real (`relay.py`)

Cada pelea lleva un `RelayServerInfo` que apunta a este mismo servidor (mismo número de puerto, pero UDP). Al
terminar de cargar, cada teléfono manda un ping UDP, abre un canal KCP y pide entrar a la sala de su pelea; cuando
están todos, el relay da la salida y a partir de ahí reenvía los botones de cada jugador a los demás (netcode
rollback del propio juego). El formato exacto de cada mensaje está en la cabecera de `relay.py` y en `ANALISIS.md`.
Al acabar, los teléfonos suben el resultado (`UploadBattleResult`) y el servidor contesta a todos con `BattleResult`.

- El relay corre en un hilo aparte con sockets UDP normales y un KCP propio escrito en Python puro.
- El ping previo va a `RelayServerInfo.Port - 1` (leído en `InitRelayServerPingRetriever`); por eso el relay escucha
  también en ese puerto. `--puerto-relay N` cambia el puerto de la pelea (el ping pasa a ser N-1).
- 3v3 y 2v2 tienen una fase de **ordenar personajes** entre la selección y el escenario: cada `ChangeCharOrderReq`
  llena el puesto `OrderingIndex` y se contesta con el siguiente; el rival recibe `NotifyOtherRequestChangeCharOrder`
  y, cuando los dos lados terminaron (o pasan 33 s), todos reciben `NotifyFinishReorderChar`.
- En el log, las líneas `relay:` cuentan quién entra, cuándo empieza la pelea y cuántos inputs se reenviaron.
- **Resultado:** cada teléfono sube su `UploadBattleResult` y el servidor le contesta con `BattleResult` solo después
  de recibir el suyo. Si se lo manda antes, el teléfono lo descarta y se queda en "esperando resultado". A quien no lo
  sube en 10 s se le manda igual.
- El `BattleLog` del resultado debe traer `LeftRoundResults`/`RightRoundResults` con `TotalRounds` elementos: la
  pantalla de resultados los recorre ronda a ronda y, si faltan, falla y el juego se queda en la imagen del ganador.
- **Partida rápida (tipo 2):** el juego no muestra selección de personaje; usa el favorito elegido antes de buscar
  (`ChangeFavCharReq`). El servidor manda ya el personaje de cada uno y un escenario, y la pelea pasa directo a la carga.
- **Clasificatoria:** el botón del menú abre el modo "3v3 en solitario" (`MatchMakingType` 3): 3 personajes por
  jugador, fase de ordenarlos y pelea por relevos. Al reordenar, el rival recibe `NotifyOtherRequestChangeCharOrder`
  con `TargetUid = 0`; con otro valor su teléfono lo ignora y la pelea se desincroniza.
- **Sala:** al terminar la pelea no se manda `NotifyRoomDetailInfoUpdate` a los de la mesa. Si llega justo antes del
  resultado, el teléfono se queda en la imagen del ganador sin revancha ni salir.
- **Modos de batalla abiertos:** el juego decide qué botones habilita con su `OpenSystemConfig.json` (la 2v2 venía
  con fechas de 2021 y la clasificatoria 1v1 solo de 9:00 a 20:30) y con `RankMatchConfig` (nivel 8 y 5 personajes).
  El servidor le manda al teléfono una `OpenSystemConfig.json` sin fechas ni horario (ver `config_juego/README.md`).
  La primera vez hay que cerrar y abrir el juego. El nivel es el real de la cuenta (sube 1 cada 100 de experiencia):
  forzarlo a 10 rompía la pantalla de resultados del que pierde.
- **Teléfono pegado al terminar:** si a un jugador le llega el resultado pero su pantalla de resultados no se abre
  (no pide nada más), en la sala la revancha o "volver a elegir" del rival lo mandan también a elegir personaje
  (`NotifyGameHallMatchCreated`). Si un teléfono vuelve a cargar una pelea ya terminada, se le cancela.
- **Tutoriales:** se guardan los que termina cada cuenta (`QueryTrainingDataReq`); la guía que salía tras la primera
  derrota viene marcada como hecha.
- No implementado todavía: el netcode FrameSync (el servidor anuncia rollback), espectadores de una pelea en curso
  y reconexión a mitad de combate.

## Probar sin teléfonos

```
python mr_server.py --host 127.0.0.1 --port 18080 --nombre-automatico
python ../tools/prueba_pelea.py 127.0.0.1 18080
```

`tools/prueba_pelea.py` simula dos teléfonos de punta a punta: sala de espera, selección, carga, ping, KCP con
paquetes perdidos, resultado, revancha, abandono, clasificatoria 3v3, 2v2 y el envío de configuraciones. `tools/cliente_prueba.py` es el cliente base.
Versión anterior (solo grabaciones): `mr_server_v1_replay.py`.

## Perfil del jugador
- **Estadísticas:** cada pelea se guarda por jugador y personaje (tabla `registros` de `cuentas.db`) con las estadísticas
  que sube su teléfono (daño, combos, golpes, bloqueos…). De ahí salen `CommonBattleStats` (por tipo de pelea),
  `HeroBattleDatas` (por personaje) y la temporada (`QuerySeasonInfoReq`): porcentaje de victorias y los seis puntajes
  de 0 a 20 del radar (daño por segundo, movimiento, combo, ataque, técnica, defensa), con el total sobre 100.
- **Avatar:** los 18 avatares de personaje (`PlayerHeadReq`/`PlayerHeadChangeReq`). Una foto propia no se puede: el
  juego la subía a una nube de Tencent que ya no existe.
- **Marcos:** se desbloquean con las reglas del propio juego (`datos/marcos.json`, de `HeadFrameConfig`): puntos de
  clasificatoria, victorias con un personaje y nivel. Los de objeto/especiales quedan bloqueados para campeones y
  colaboradores.
- **Me gusta** (`PraiseOtherReq`) se acumula en el perfil.

