# Estudio: crear marcos NUEVOS (imagen, efecto y texto) y agregarlos al juego

Pregunta: ¿se pueden crear marcos nuevos, con más espacios, con sus propios efectos (por ejemplo la araña del marco
verde) y en un formato que el juego lea tal cual se lo indicamos?

**Respuesta: sí. Todas las piezas están verificadas en el código del juego, y ya hay un paquete construido con los 5
marcos beta (ids 100 a 104).** Falta un solo paso, que solo se puede hacer en un teléfono: confirmar que el juego
usa los archivos nuevos (ver "Prueba en el teléfono").

## 1. Cómo arma el juego un marco (verificado en el código)

Un marco tiene 4 partes y cada una sale de un lugar distinto:

| Parte | De dónde la lee el juego | Prueba en el código (APK 1.0.23) |
|---|---|---|
| **Lista de marcos** (id, imagen, efecto, textos) | `Shared/HeadFrameConfig.json` | `HeadFrameConfig.Load` → `TextConfig.GetConfig` → `JsonUtility.FromJsonOverwrite`. Es el mismo camino por el que el servidor ya reemplaza `OpenSystemConfig.json` |
| **Imagen** | bundle `gui/textures/items/<idioma>/common/headframe` | `ItemIconSet.ApplyItemIcon`: ruta = base + idioma + `/` + `icon`, en minúsculas. Dentro del bundle: `assets/ufo/gui/textures/items/chinese/common/headframe/<nombre>.png` |
| **Efecto** (brillo y movimiento) | bundle `effects/prefab/ui/headframe/prefab` | campo `effect`; dentro del bundle: `assets/ufo/effects/prefab/ui/headframe/prefab/<nombre>.prefab` |
| **Nombre y descripción** | bundle `config/i2languages` (I2 Localization) | claves `item/name/…`, `item/desc/…`, `item/lockdesc/…`, en 12 idiomas |

En el servidor, los ids de marco son `ushort` (`CurHeadFrame`, `UnlockedHeadFrames`): hay lugar hasta el 65.535.
**No hay un número fijo de espacios**: el juego muestra todos los que vengan en `HeadFrameConfig.json`.

### Dónde están esos archivos en el teléfono
`UFOGCloudConfig` (dentro del APK) tiene `enableUpdate = 1` y `firstExtractObb = 1`. Con eso:
- `GameApp.GetUpdateAssetRootPath` devuelve `Application.persistentDataPath` (y no el OBB);
- `GCloudDolphinUpdater.GetUpdateSourceSavePath` también es `persistentDataPath`: en el primer arranque el
  actualizador de Tencent (Dolphin) **extrae el OBB ahí**;
- `LuaManager.LoadEncryptedLuaBytes` lee `lua/lua.bytes` desde esa misma carpeta.

Es decir, el juego **lee los recursos como archivos sueltos** en
`/storage/emulated/0/Android/data/com.gtarcade.next.mrglo/files/`
(`AssetBundles/Android/...`, `lua/lua.bytes`...). Reemplazar o agregar archivos ahí cambia lo que carga el juego
**sin reempaquetar el OBB**.

### Los bundles se pueden editar sin el proyecto original
- Unity **2018.4.32f1**, con la estructura de tipos incluida (typetree): UnityPy los lee y los vuelve a escribir.
- Los efectos **no usan scripts del juego**, solo componentes de Unity: `Animator` (anima colores y desplazamiento
  de textura de los materiales), mallas con forma de borde (`flow`, `glow`) y partículas (`ParticleSystem` con todos
  los módulos, incluida la animación cuadro por cuadro, *Texture Sheet Animation*). Los shaders están en un bundle
  `shader` compartido y se reutilizan.

## 2. Lo que se construyó y se verificó

Herramientas en `tools/marcos/`:

| Herramienta | Qué hace |
|---|---|
| `agregar_marcos.py` | agrega imágenes nuevas al bundle de marcos (textura ETC2 RGBA8 + sprite + índice) sin tocar las 99 originales |
| `clonar_efecto.py` | crea un efecto nuevo copiando uno del juego (todos sus objetos con ids nuevos), le cambia el color y, opcional, le pone una animación cuadro por cuadro propia en una partícula |
| `agregar_textos.py` | agrega nombres y descripciones al bundle de idiomas (12 idiomas; los que falten van en inglés) |
| `construir.py` | **el formato que pediste**: lee un solo JSON con los marcos nuevos y genera todo |

El formato es `datos/marcos_beta/marcos_nuevos.json`: por marco, `id`, `nombre`, `imagen`, `titulo`,
`descripcion`, `bloqueado` y `efecto` (efecto base del juego + color + hoja de animación opcional).

Resultado (`python tools/marcos/construir.py datos/marcos_beta/marcos_nuevos.json <juego extraído> <salida>`):
- `headframe.bundle`: 104 imágenes (99 originales idénticas + 5 nuevas);
- `prefab.bundle`: 51 efectos (46 originales idénticos + 5 nuevos, sin referencias rotas);
  `beta_bughunter_fx` lleva la araña caminando (8 cuadros, 4×2);
- `i2languages.bundle`: 7.140 textos (+15);
- `HeadFrameConfig.json`: 91 marcos (86 + ids 100 a 104), guardada en `server/config_juego/en_espera/`.

Cada archivo se volvió a abrir desde cero y se comprobó: originales intactos, nuevos presentes, imágenes iguales a
la entrada (error de compresión ETC2 de unos 3/255).

## 3. Todas las vías posibles

| Vía | Qué permite | Qué hay que hacer en cada teléfono | Estado |
|---|---|---|---|
| **A. Solo servidor** (`HeadFrameConfig.json`) | ids nuevos que **combinan imágenes y efectos que ya existen** (p. ej. marco del pase con efecto de fuego) | nada | listo para usar; el servidor ya sabe enviar configuraciones |
| **B. Archivos en la carpeta del juego** | imágenes, efectos y textos **nuevos** (lo construido) | copiar 3 archivos una vez | construido; falta probar en el teléfono |
| **C. Descarga automática con Lua** | lo mismo que B, pero el juego baja los marcos nuevos de **nuestro servidor** al entrar | copiar `lua/lua.bytes` una vez; después, nada más | factible: Lua tiene `UnityWebRequest`, `AssetBundle.LoadFromMemory` y `System.IO.File`, y el repo ya descifra y vuelve a cifrar `lua.bytes` byte a byte |
| **D. OBB/APK nuevos** | lo mismo, para instalaciones nuevas | instalar | sin hacer: falta un escritor de IFS (hoy solo se lee). C lo vuelve innecesario |
| **E. Unity 2018.4.32f1** (gratis, en PC) | efectos **totalmente libres**: araña que recorre el borde con su propia trayectoria, mallas nuevas, varios cuadros | lo de B o C | factible: se diseña en Unity y se integra al bundle con una herramienta como `clonar_efecto.py` |

Recomendación: probar B ahora con el paquete de los 5 marcos. Si funciona, armar C para no tocar más los teléfonos.

## 4. La araña y los demás efectos

- **Hecho:** una partícula con animación cuadro por cuadro (patas que se mueven) dentro de un efecto nuevo,
  copiada del efecto de Navidad, que ya usaba una animación así.
- **Pendiente:** que la araña **recorra el borde**. La partícula sale donde la ponía el efecto original. Opciones:
  (1) poner la araña en la textura de un brillo que recorre el borde (las mallas `flow` ya se mueven así), pero
  la araña se desliza sin mover las patas; (2) encadenar partículas, una por lado; (3) hacerlo en Unity 2018.4 (vía E),
  que es lo más fiel.
- Rayos, glitch y pulsos se resuelven igual: hojas de animación (las puede generar `datos/marcos_beta/motor.js`)
  en partículas, o texturas propias en las mallas `flow`.
- El color: `--tinte` cambia los materiales que vienen dentro del bundle de efectos. Algunos efectos usan
  materiales de otro bundle (`effects/material`), que conservan su color: se resuelve copiándolos igual.

## 5. Prueba en el teléfono (lo único que falta)

1. Con el juego ya abierto una vez, revisar que exista
   `Android/data/com.gtarcade.next.mrglo/files/AssetBundles/Android/` (en Android 11 o superior: con el cable a una PC,
   con `adb`, o con un explorador que pueda entrar a `Android/data`). **Si no existe, avisar: cambia el plan.**
2. Respaldar los 3 archivos originales que se van a reemplazar.
3. Copiar los 3 bundles del paquete a sus mismas rutas.
4. En el servidor: mover `config_juego/en_espera/HeadFrameConfig.json` a `config_juego/activos/`, reemplazar
   `datos/marcos.json` por `servidor/marcos.json` del paquete, reiniciar y dar un marco a la cuenta de prueba:
   `python colaboradores.py marco <jugador> 101`.
5. Entrar al juego: perfil → marcos. Revisar la imagen, el nombre, el efecto, ponérselo y verlo en la sala.

Para volver atrás: restaurar los 3 respaldos y sacar `HeadFrameConfig.json` de `activos/`.

**Importante:** no activar `HeadFrameConfig.json` ni los ids nuevos en el servidor para jugadores que no tengan los
archivos nuevos: su teléfono buscaría una imagen que no existe.

### Riesgos a vigilar en la prueba
- **Revisión de archivos del actualizador:** Dolphin tiene una revisión de archivos (`StartFileCheck`,
  `filelist.json`). Si al abrir el juego vuelve a poner los originales, hay que actualizar también `filelist.json`.
- **Revisión de integridad de bundles:** si el juego compara el CRC con el manifiesto
  (`AssetBundles/Android/Android`), un bundle modificado no cargaría. Se arregla actualizando ese manifiesto.
- **Idioma:** la imagen se busca primero en el bundle del idioma del teléfono (`english/...`) y luego en el chino.
  Con los nuevos solo en el chino debería funcionar igual que con los originales (el bundle inglés solo tiene 1 marco).

## 6. Efectos EXACTOS: la misma animación del video, dentro del juego

Los efectos copiados y recoloreados (`clonar_efecto.py`) se parecen, pero no son iguales a lo promocionado. Para que
el juego muestre **exactamente** lo del video se usa la animación misma:

1. `node tools/marcos/exportar_animaciones.js`: el **mismo motor** del video y la página (`datos/marcos_beta/motor.js`,
   modo bucle) dibuja cada marco cuadro por cuadro. Cada cuadro usa una semilla fija y las velocidades se ajustan a
   un múltiplo exacto del bucle (cambios de pocos %), así la última imagen empalma con la primera.
   Se comprueba solo: 0 píxeles distintos en el empalme de los 5 marcos.
2. `tools/marcos/efecto_cuadros.py` (lo llama `construir.py`): arma la hoja de cuadros y crea un efecto nuevo con
   piezas que el juego ya usa:
   - una partícula eterna y quieta con *Texture Sheet Animation* en modo FPS (`timeMode` 2: cuadros por segundo fijos, en bucle);
   - el shader del juego **`UFOEffect/Alpha Blended`**, que calcula `2 × color × _TintColor × textura`. Con
     `_TintColor` 0,5 sale la textura tal cual, con mezcla alfa normal, igual que en el navegador;
   - la textura en ETC2 RGBA8, el formato de las texturas del juego.
3. Diferencias con el navegador, ya corregidas:
   - **Espacio de color:** el juego mezcla en espacio lineal (`m_ActiveColorSpace = 1`). El alfa de los píxeles
     semitransparentes se compensa en la hoja para que sobre fondo oscuro dé lo mismo que el video.
   - **Doble resplandor:** en los marcos animados, la imagen fija guarda solo el cuerpo sólido, sin el resplandor.
     El resplandor lo dibuja la animación.

Resultado medido con los datos del bundle, simulando el dibujo del juego: error medio de 2,5 a 3,6 sobre 255 frente
al video (sobre todo por la compresión ETC2). Comparación de lado a lado en `comparacion_video_vs_juego.mp4`.

| Marco | Cuadros | Bucle | Hoja | Memoria de la textura |
|---|---|---|---|---|
| Founder, Vanguard, Patcher, Hero | 192 de 192 px | 8 s a 24 fps | 3072×2304 | 6,75 MB c/u |
| Bug Hunter | 240 de 192 px | 12 s a 20 fps (la araña da una vuelta completa) | 3072×2880 | 8,4 MB |

El bundle de efectos pasa de 0,7 a 5,6 MB. Si todos se ven a la vez (pantalla de marcos), son ~36 MB de memoria
de video.

### Tamaño y posición: marco de calibración (id 105)
El tamaño del efecto respecto de la imagen del marco se midió en los efectos del juego (1,38 unidades, ±4 %).
El marco 105 lo confirma en el teléfono: su imagen tiene un **borde azul** y su efecto dibuja cuadrados del 90 al 110 %.
- Si el rojo (100) tapa al azul, está perfecto.
- Si coincide otro número, en `marcos_nuevos.json` se pone `"calibracion": {"tamano": 1.38 × número / 100}`.
- Si la cruz roja no cae sobre la azul, se ajustan `x` e `y`.
Después se vuelve a construir.
