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

Pendiente de verificar: si el Connector de GCloud usa cifrado (`GCloud.EncryptMethod`: None/Tea/Aes;
`KeyMaking`: None/Auth/Server/RawDH/EncDH). El mod sirve respuestas grabadas sin librería criptográfica,
lo que sugiere canal en claro o cifrado anulado por su hook.

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

Qué no sabemos todavía y hay que mirar con el APK **original** sin modificar: cifrado del Connector, qué exactamente
parchea el hook en `libil2cpp.so`, y si el login exige token MSDK válido (campos `OpenId`, `Token`, `MsdkPf`...).

## Herramientas en este directorio

- `tools/extraer_tipos_il2cpp.py`: clases/campos/métodos desde `global-metadata.dat` (sin .NET).
- `tools/extraer_blobs_mod.py`: extrae los mensajes grabados de `libgame.so`.
- `datos/comandos_grabados.txt`: tabla cmd ↔ mensaje.
- `datos/fbtypes_mensajes.txt`: los 1 388 tipos FlatBuffers del protocolo.
