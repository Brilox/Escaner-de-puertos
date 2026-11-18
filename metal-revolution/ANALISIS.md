# Metal Revolution: análisis del APK "Metal Offline V2" y viabilidad de un servidor propio

Fecha del análisis: 2025-11-15. Fuente: `metal offline_2.7z.001-005` (APK `com.gtarcade.next.mrglo` 1.0.23, build 1300),
firmado por el modder como "Metal Revolution Offline V2" (C=BR, O=Local Project, OU=Preservation), 30-oct-2026.

## Veredicto

**Sí es viable** un servidor privado para ~10 personas. La simulación del combate corre en el cliente
(rollback y frame-sync), de modo que el servidor de batalla es solo un *relay* de inputs. El trabajo real está en
reimplementar el servidor de "hall/salas" (protocolo FlatBuffers sobre un canal TCP de Tencent GCloud) y un relay UDP/KCP.
El modder ya hizo la mitad del camino: su librería trae grabaciones del protocolo real y emula localmente el login y el hall.

## Qué hay dentro del APK

| Pieza | Hallazgo |
|---|---|
| Motor | Unity 2018.4.32f1, IL2CPP. `global-metadata.dat` **sin cifrar** (21.8 MB, versión 24 / layout 24.1). |
| Lógica del juego | `Assembly-CSharp` con 11 594 tipos. Namespaces clave: `MetalFury.Logic`, `MetalFury.Rollback`, `MetalFury.FBTypes` (1 388 tipos FlatBuffers = el esquema completo de mensajes), `GCloud`, `GCloud.LockStep`. |
| Red (SDK) | Tencent GCloud: Connector (TConnd/GCP, TDR), Tdir (directorio de zonas), LockStep (relay de frames), Dolphin/Puffer (parches). Login vía MSDK/INTL (`us.itopsdk.com`). |
| Servidores originales | `pre-dir.2.1291864285.gcloudcs.com` (Tdir), `test.mr.qq.com:10002`, `img.mr.qq.com`, `sg.intlgame.com`, zona de pago `unipay.qq.com`. Todos caídos. |
| Mod | `lib/*/libgame.so` **no es del juego**: es la librería del modder (`org.metalrevival.offlinecore`), con símbolos sin stripear. |

## Cómo funciona el mod (y por qué nos sirve)

1. `libgame.so` localiza `libil2cpp.so` con `dl_iterate_phdr`, busca una secuencia de 64 bytes de código
   (`mrboundary::kAnchor`, coincide en `libil2cpp.so` @ `0x220b20c`) e instala un hook con `mprotect`.
2. Levanta un **servidor TCP local en 127.0.0.1:8080** (importa `socket/bind/listen/accept4`).
3. Responde al Tdir con una zona falsa "Local Revival" cuyo dato custom es
   `{"hosts":[{"host":"127.0.0.1:8080","zone":"local"}]}`; `QueryAddrSvr` devuelve `127.0.0.1:8080`;
   `VersionUpdate` devuelve `http://127.0.0.1/` (sin actualización).
4. Para el canal de juego sirve **61 mensajes grabados del servidor real** (ver `datos/comandos_grabados.txt`):
   login (cmd 1), hora del servidor (92), pong (47), lista de zonas (16), config de cliente (167/168),
   y en el namespace `mroffline_lan`: lista de halls (134), entrar al hall (136), lista de salas (146),
   entrar a sala (137), lista de jugadores (145), con una "Sala LAN Experimental". El modder ya está probando LAN.
5. La nota del modder (en portugués, incrustada) dice que el online "está siendo estudiado".

## Protocolo del canal de juego (reconstruido de los blobs)

Trama big-endian: `u16 tipo (1 req / 2 rsp) | u32 largo | TLV` con `tag 2 = seq`, `tag 6 = cmd`, `tag 5 = flag`,
`tag 4 = largo payload` seguido del payload **FlatBuffers**. El id de cada mensaje sale del enum
`MetalFury.FBTypes.GameSvrReqUnion` (248 valores: `LoginRequest`, `QueryZoneListReq`, `EnterHallReq`, ...),
y los campos de cada mensaje salen de los accessors `get_*` de cada clase `MetalFury.FBTypes.*`
(ej. `RelayServerInfo`: Id, Port, KcpConv, RelayId, Host, NetCode, InnerHost, InnerPort, TcpInnerPort, TcpOuterPort, UseRudp).
Con eso se puede regenerar el `.fbs` y escribir el servidor en Python/Go/Node.

**Cifrado confirmado (leído del código máquina).** `GCloudNetBase::InitConnector` escribe
`EncMethod = 3 (QQ)` y `KeyMakingMethod = 2 (Server)` en el `ConnectorInitInfo`
(instrucciones `mov x8,#0x200000002 ; movk x8,#3 ; stur x8,[x20,#0x1c]` en `0x42e6d8c` del build 1.0.23).
Es decir, el canal TConnd va cifrado con la variante TEA "QQ" de Tencent y la clave la fija el servidor en el handshake.
Dos salidas: (a) implementar el handshake GCP + TEA en nuestro servidor (todo el código está en `libgcloud.so`,
con nombres de archivo fuente intactos: `tdrcrypt.cpp`, `gcpapi.g.cpp`), o (b) parchear esas dos instrucciones
del cliente a `EncMethod = 0, KeyMaking = 0` y hablar en claro. La opción (b) es la rápida, ya que de todos modos
distribuimos un APK modificado. Dato útil: la tabla de offsets de campos de IL2CPP está ofuscada con XOR `0xB6B6B6B6`.

## Batalla online: cómo está hecho el netcode

- `MetalFury.NetCode = {Rollback, FrameSync}`; `RelayConnectorType = {Kcp, RawUdp, LocalSimulate, GCloud}`.
- Mensajes al relay (`RelaySendToMsgType`): EnterRoom, ExitRoom, HeartBeat, ClientInput, SyncPing, CheckSync, UseEmoji,
  UseItem, en variantes Rollback y FrameSync. El relay **no simula nada**: reenvía inputs entre los dos clientes.
- Clases: `MetalFury.Rollback.RollbackManager` (snapshots, `CheckAndPerformRollback`), `BaseMatchNetworkHandler`
  (`InitRelayServerClient`, `OnRelayRoomEntered`, `ConnectRelayServerTimeout`), `RelayServerInfoWrapper`.
- El servidor de hall le dice al cliente a qué relay ir mediante `RelayServerInfo` (host, puerto UDP/TCP, KcpConv).

Conclusión: un relay KCP/UDP de salas de 2 jugadores es un programa pequeño.

## Plan propuesto

1. **Esquema**: regenerar el `.fbs` desde `MetalFury.FBTypes` (nombres y orden de campos salen de los accessors).
2. **Servidor de hall** (TCP, trama TLV + FlatBuffers): login, zonas, hora, ping/pong, config, halls, salas, jugadores,
   emparejamiento en sala, `NotifyGameHallMatchCreated` con `RelayServerInfo`. Empezar reproduciendo los 61 blobs
   grabados y luego reemplazarlos por lógica real.
3. **Directorio**: emular Tdir (protocolo GCP/TDR, hay 3 respuestas grabadas) o reutilizar el hook del mod cambiando
   `127.0.0.1:8080` por la IP del VPS.
4. **Relay** UDP/KCP: salas de 2, reenvío de inputs, heartbeat, `RollbackSyncPing`.
5. **Cliente**: parchear el host en `libgame.so` (o un APK con el hook apuntando al VPS) y firmar.
6. Probar con 2 jugadores, luego 10.

## Comparación con el APK original (`metal-revolution-1-0-20.xapk`, release del repo)

- Original: `com.gtarcade.next.mrglo` 1.0.20 (build 997), firmado por NEXT Studios (Shenzhen). El mod parte de **1.0.23**
  (build 1300), una versión posterior; por eso `libil2cpp.so` y `global-metadata.dat` difieren, pero el conjunto de clases
  es el mismo (solo cambian clases generadas por el compilador). Las clases Java son idénticas byte a byte en nombres y métodos.
- El mod **reemplazó** `libgame.so`: el original (1,3 MB) es el verificador de firma del SDK Youzu
  (`checkSignatureByJava`), cargado por `com.youzu.gamexy.Game.<clinit>` con `System.loadLibrary("game")`.
  El modder puso su librería con el mismo nombre, así se carga sola y de paso anula la verificación de firma.
- El mod **eliminó** `libLocalAIService.so` (IA local con TensorFlow Lite, `AvatarAIEngine`) y cambió `MSDK_URL`
  a `us.itopsdk.com`. Nada más cambió, salvo configs del SDK de pagos.
- El hook del mod se instala sobre `MetalFury.Logic.GameApp::InitAssetsAndSettings` (los 64 bytes de `kAnchor`
  son el prólogo de esa función, en `0x220b20c` del build 1.0.23).
- OBB (865 MB): `assets/first_source.png` es en realidad un paquete NIFS de GCloud IIPS (844 MB) con los recursos
  del juego. No contiene lógica de red.
- Login: `LoginRequest` lleva `OpenId`, `Token`, `MsdkPf`, `GameVersion`, etc. Nuestro servidor puede aceptar cualquier
  valor; el mod ya responde al login con un `LoginGameSvrRsp` grabado (cmd 1).

## Corrección importante: el canal del juego NO usa GCloud ni cifrado

Al leer el servidor local del mod (`serve()` en `libgame.so`) quedó claro que por el puerto 8080 llegan dos clases
de conexión y el mod las distingue por el primer byte:

- `0xAA`: TGCP (handshake SYN/ACK, AUTH/AUTHRSP+BINGO, respuestas constantes de 63/54/55 bytes) y dentro, en
  paquetes de comando `0x4013`, peticiones **Pebble RPC** (Thrift binario) del directorio: `DirService:get_server_dirtree_by_id`,
  `QueryAddrSvr:QueryAddrInfo`, `VersionUpdate:ReqUpdateVersion`. Es la parte que usa `libgcloud.so`.
- `0x00 0x01`: el protocolo del juego, **TCP plano** con el framing propio (`den.TcpConnector` en C#), sin TGCP
  y sin cifrado. El `EncMethod = QQ` de `GCloudNetBase::InitConnector` no afecta a este canal.

Por tanto no hace falta parchear `libil2cpp.so`. El único cambio en el cliente es la dirección del directorio,
que está en `assets/bin/Data/sharedassets0.assets`, objeto `GCloudConfig` (clase `MetalFury.VersionUpdate.GCloudGameOptions`),
entrada del mercado 643839105: el mod puso `127.0.0.1` en `updateUrlRelease`, `tDirUrlPreview` y `tDirUrlRelease`
(el original tenía `pre-dir.3.643839105.dmp-jsdj.gtarcade.com`). `tools/parchear_cliente.py` lo cambia por nuestro host.

## Fase 1 implementada: `server/`

`server/mr_server.py` reproduce el comportamiento del servidor local del mod en una IP pública (ver `server/README.md`).
Probado con un cliente sintético: handshake TGCP, las tres respuestas del directorio con la dirección parcheada
y longitudes recalculadas, canal del juego con `seq` copiado, hora del servidor actualizada y `EmptyRsp` genérico.
Pendiente de probar con el juego real.

## Selección del relay (confirmado)

`BaseMatchNetworkHandler::InitRelayServerClient` construye `RollbackRelayServerClient` o `FrameSyncRelayServerClient`
y elige el conector según `RelayServerInfo`: `GCloudRelayServerConnector`, `KcpRelayServerConnector`,
`RawUdpRelayServerConnector` o `LocalRelayServerConnector`. Los conectores Kcp/RawUdp usan sockets propios
(namespace `den`: `TcpConnector`, `UdpConnector`), sin pasar por GCloud. Para nuestro servidor conviene
devolver un `RelayServerInfo` que fuerce **RawUdp o Kcp**: así el relay es un programa UDP simple y evitamos
el protocolo LockStep de Tencent.

## Protocolo del relay (fase 3, leído del código del cliente)

- El cliente usa `RollbackRelayServerClient` si `RelayServerInfo.NetCode != 1` y el conector `KcpRelayServerConnector`
  (`KCPSharp.KcpSocket`): UDP directo a `Host:Port`, `conv = KcpConv` (6666 por defecto), nodelay 1, intervalo 10 ms,
  reenvío rápido 2, sin control de congestión, ventanas de 128.
- Antes de conectar mide el ping (`PingRetriever`): un datagrama con el mismo formato TLV del canal TCP (tipo 1,
  payload = marca de tiempo) **al puerto `Port - 1`** (`InitRelayServerPingRetriever` resta 1 a `GetUdpPort`). Hay que
  devolverlo igual con tipo 2. Si falla, `OnPingErrorBeforeConnect` muestra "RelayServerConnectTimeout" y reconecta.
- Fase de ordenar (3v3/2v2, fase 2 `ORDERING_CHAR`): `ChangeCharOrderReq{SrcPos, TargetPos}` con `TargetPos` igual al
  `OrderingIndex` actual; `ChangeCharOrderRsp.OrderingIndex` = siguiente puesto (el cliente completa solo el último).
  El rival aplica el cambio con `NotifyOtherRequestChangeCharOrder` (SourceUid = TargetUid = quien ordena) y el aviso
  vacío `NotifyFinishReorderChar` (unión 121) llama a `FinishReorderChar` → `GotoSelectStagePhase`.
- Un datagrama cuyos primeros 4 bytes son cero no pasa por KCP: es el canal sin garantía de entrega.
- Mensajes cliente → servidor (primer byte = tipo, little-endian, pueden venir varios seguidos):
  `0 EnterRoom` (matchId i32 = `RelayId`, subMatchId u16, side, pos, reEnter, teamSize), `1 ExitRoom`, `2 HeartBeat`,
  `14 Input` (frame i32, botones u16), `15 SyncPing`, `16 CheckSync`, `17 Emoji`, `18 Item`.
- Servidor → cliente: `0` (un byte) cuando ya entraron todos (`AllPlayerEnterRoom`, dispara `OnRelayRoomEntered`
  y arranca la pelea); y los tipos 14 a 18 reenviados a los demás con `side` y `pos` del emisor insertados tras el frame.
  El emisor no recibe eco de sus propios mensajes (`RollbackNetCodeDriver::OnRecvRelayMsg` los entrega al
  `RollbackRemoteInputReader` del lado indicado).
- Fin de pelea: `UploadBattleResult` por TCP y aviso `BattleResult` (`ServerBattleResult`) cuyo `MatchId` debe
  coincidir con `RelayId`.

## Obfuscaciones encontradas en `libil2cpp.so` (build 1.0.23 arm64)

- Tabla de offsets de campos: XOR `0xB6B6B6B6`. Tipos con enum ≥ 0x80: XOR `0xB6`.
- La sección `.text` (los thunks de métodos de structs, como los getters de FlatBuffers) va con XOR `0xB6` por byte.
  `tools/mrrev.py` lo deshace y `tools/extraer_defaults_fb.py` saca de esos getters el número de slot real y el valor
  por defecto de cada campo. Importa: un campo que vale su valor por defecto no viaja, así que `Confirm` (por
  defecto verdadero) llegaba "vacío" y el servidor lo leía como falso.

## Herramientas en este directorio

- `tools/mrrev.py`: desensamblado anotado (nombres de métodos, literales, campos) para leer la lógica del cliente.
- `tools/extraer_esquema_fb.py` y `tools/extraer_defaults_fb.py`: esquema FlatBuffers completo con slots y valores por defecto.
- `tools/prueba_pelea.py`: prueba de punta a punta con dos teléfonos simulados.

- `tools/extraer_tipos_il2cpp.py`: clases/campos/métodos desde `global-metadata.dat` (sin .NET).
- `tools/extraer_blobs_mod.py`: extrae los mensajes grabados de `libgame.so`.
- `tools/resolver_direcciones_il2cpp.py`: direcciones de métodos C# en `libil2cpp.so` para desensamblar con capstone.
- `datos/comandos_grabados.txt`: tabla cmd ↔ mensaje.
- `datos/fbtypes_mensajes.txt`: los 1 388 tipos FlatBuffers del protocolo.

## El archivo grande del OBB (`assets/first_source.png`): abierto

No es una imagen: es un paquete **IFS de Tencent GCloud** (cabecera `nifs`, lo maneja `libgcloud.so`), un MPQ v4
modificado. Herramientas: `tools/ifs/` (`python extraer.py main.obb salida [--todo]`).

- Cabecera (172 bytes): `nifs`, tamaño, versión, sector (512 << 5 = 16 KB), posiciones y tamaños de las tablas
  BET, HET, MD5 (por trozo de 16 KB) y bitmap.
- Tablas `HET\x1a` y `BET\x1a` cifradas con el cifrado MPQ estándar (claves de "(hash table)" y "(block table)").
  Cada entrada BET (304 bits): posición 30, tamaño 25, comprimido 25, flags 32, MD5 128, hash de la carpeta 64.
  Después, un hash de 56 bits por archivo con su nombre.
- Hash del nombre: Jenkins lookup3 `hashlittle2(nombre en minúsculas con '\\', 2, 1)`, `(b << 32) | c`, 56 bits.
- Nombres: el `(listfile)`, único archivo cifrado (MPQ estándar con la clave de "(listfile)").
- Cada archivo: tabla de sectores (u32) y sectores con 1 byte de tipo delante (2 = zlib).
- Contenido: 8.691 archivos: AssetBundles de Unity (personajes 1.160, efectos 5.230, interfaz 898, escenarios,
  configuración), sonido Wwise, modelos de IA (`LocalModels/*.tflite`) y **`lua/lua.bytes`**.

### Los scripts Lua del juego (`lua/lua.bytes`)
`LuaManager.DoLoadEncryptedLuaBytes` lo descifra con `XLUAInspector.Utils.ByteArrayUtil.Decrypt`: **AES-256-CBC**
con clave e IV de `PasswordDeriveBytes("klsdfsafsdf", sal 43 87 23 72)` (SHA1, 100 iteraciones), en la versión de
.NET con su error histórico en la segunda llamada (el IV sale de `bloque0[8:16] + bloque2[0:8]`). Descifrado, es un
texto con 1.242 scripts separados por `\nlua/<ruta>\n`. **Volver a cifrarlo da el archivo original byte a byte**,
así que se pueden modificar.

Hallazgos en los scripts (no se publican: son código del juego):
- `MetalFury/UI/MainMenuScreen.lua`: el botón de clasificatoria abre un submenú con **1v1** (`GotoRankMatch`),
  **2v2** y **3v3** (`GotoSoloRank3v3`). Cada opción se habilita según `OpenSystemConfig` ("RankMatch",
  "RankSolo3v3"...: fechas, horarios y trofeos) y `RankMatchConfig` (nivel y número de personajes mínimos).
- `MetalFury/Config/ConfigManager.lua`: la configuración del juego son archivos `Shared/*.csv` y `*.json`
  (`OpenSystemConfig.json`, tienda, objetos, tareas, pase de batalla...) que se recargan cuando el servidor avisa.
- Pantallas de fin de pelea: `UI/DerivedUI/InBattle/{Base,Common,Rank}BattleEndScreen.lua`, `UI/SoloNvN/*`.

## El servidor puede cambiar la configuración del juego (implementado: `server/config_juego.py`)
Leído de `ConfigHashNetworkHandler` / `ConfigManager` / `TextConfig` en `libil2cpp.so` (1.0.23):
1. `NotifySvrConfigReload{Reload, HashAll}`: si `Reload` y `HashAll` distinto del guardado (y el servidor no mandó
   el flag `disableConfigHash`), el teléfono pide `QueryAllConfigHashReq`.
2. `QueryAllConfigHashRsp{HashPairs[{FileName, Hash}]}`: `FileName` es el nombre corto (`OpenSystemConfig.json`).
   Para cada uno, `NeedUpgrade` compara `Hash` con el MD5 de su copia de fábrica (`hashInApp`) y con el de la
   descargada (`hashInDoc`); si no coincide con ninguno, lo pide.
3. `DownloadConfigReq{Key}` → `DownloadConfigRsp{Content}`. El teléfono aplica `StringUtils.JsonFromServer`
   (reemplaza `\"`, `\\`, `\n`, `\r`, `\b`, `\f`, `\t`, en ese orden), lo guarda cifrado con XOR en su carpeta de
   datos (`SaveDocString`) y anota en `Hash.json` que use esa copia (`useDoc`).
4. `TextConfig.GetConfig` (lo que usa Lua para leer `Shared/<archivo>`) devuelve la copia descargada si `useDoc`.
   Las respuestas solo se aceptan con código 200/188 (cualquier respuesta normal; un `Error` las rechaza).

## El OBB del teléfono (`main.1300`, release `obb` del repo): es el oficial 1.0.23 y coincide con el APK
- `main.1300.com.gtarcade.next.mrglo.obb` (944.393.108 bytes, fecha 24/10/2022): OBB **oficial** de la 1.0.23, sin
  tocar por el mod (el mod solo cambió el APK). Es la versión que corresponde al APK Metal Offline V2.
- Su Lua usa `TextConfig:GetConfigTextLuaCall`, la función que sí existe en el C# del mod (el Lua de la 1.0.20 usaba
  `ConfigManager.LoadConfigTextLuaCall`, que no existe ahí). Desde ahora se analiza **este** código, no el de la 1.0.20.
- 1.147 scripts (la 1.0.20 tenía 1.242) y 79 configuraciones: se quitó el sistema de trofeos / cultivo de héroes
  (`trophy*`, `HeroCultivationConfig`, `HeroLevelConfig`, `Talent*`, `GameTaskConfig`).
- `OpenSystemConfig.json` es igual al de la 1.0.20 (solo falta `icon` en BpCore): la versión que manda el servidor para
  abrir los modos no cambia nada más.
- La pantalla de resultados (`CommonBattleEndScreen.lua`) en la sala llama a `ArenaBattleEndMono:OnOpen()` (C#). El
  perdedor de la sala nunca llega a abrirla (no pide `QueryPlayerRankReq`): el paso de la pelea a esa pantalla está en
  C# (`BaseMatchNetworkHandler::OnGameOver` -> `SendMatchResult` / `OnMatchResult` / `DirectlyGotoBattleEndOnRivalFlee`).
  Pendiente de seguir ahí.
- `tools/ifs/ifs.py`: corregido un sector guardado sin comprimir (como en MPQ, si comprimir no ahorra va tal cual y sin
  byte de tipo); con eso `lua.bytes` de la 1300 sale completo y se descifra con la misma clave.

### Cómo pasa el teléfono de la pelea a la pantalla de resultados (C# del APK 1.0.23)
1. `BaseMatchNetworkHandler::OnGameOver`: guarda el snapshot (su hash va en `SnapshotHash`), vuelve al relay, manda la
   repetición y, salvo que el rival haya huido (`LastBattleResult.ExitMatchInfo.ExitPlayerId`), llama a `SendMatchResult`.
2. `SendMatchResult` arma `UploadBattleResult` (ganador, rondas, estadísticas, `RoundResults`, hash, `ReplayId`, `NetStatus`).
3. Al llegar la **respuesta** a esa petición (`<SendMatchResult>b__68_0`): código 188 o 408-411 = reconectar; error =
   abre `WaitingBattleResultUI`; correcto = cierra esa espera y llama a `CheckAllMatchResultMsgProcessed`.
4. `CheckAllMatchResultMsgProcessed`: si la pelea terminó (`FightGame.gameOver`), fase 7 y `GotoBattleEndSafely`
   (disparador del autómata `GotoBattleEnd`). Es decir: **la pantalla de resultados se abre con la respuesta al
   UploadBattleResult**, y `BattleResult` (`OnMatchResult`) solo rellena `lastMatchResult` (ganador, puntos, NetStatus).
5. La pantalla (`CommonBattleEndScreen.lua`) en `BaseOnOpen` refresca los dos jugadores (C# `BattleEndPlayerInfoGroup::Refresh`)
   y luego `RankEndRewardGroup`, que es lo que manda `QueryPlayerRankReq`. Como el perdedor de la sala no manda ese
   `QueryPlayerRankReq`, su pantalla se corta en el refresco de jugadores o antes. Para saber la línea exacta hace falta el
   registro del teléfono (`adb logcat`), donde Unity escribe los errores de Lua.

### Relay en el 3v3 en solitario (C# `BaseMatchNetworkHandler::PrepareFightContext` y `RollbackNetCodeDriver::OnRecvRelayMsg`)
- Por cada personaje del combate (lado, índice) el teléfono crea un lector de inputs: **local solo para el índice igual a
  `localPlayerIndex` (0)**; todos los demás, incluidos los otros dos personajes del propio jugador, son lectores remotos.
- Los mensajes del relay se entregan al lector de `[lado][pos]` (si no es remoto se descartan).
- Por eso en el 3v3 el relay debe repartir cada input del jugador marcado con **sus 3 puestos** y devolvérselo también a
  él para los puestos 1 y 2. Marcando siempre el puesto 0, al entrar el segundo personaje nadie lo controlaba.
- Sala: subir de nivel justo al terminar la pelea dejó a los dos teléfonos sin abrir la pantalla de resultados; el nivel
  mostrado queda fijo durante la sesión.

