# Arte de Metal Online (pantalla de inicio de sesion)

Diseno propio, generado por codigo (no usa arte del juego):
- `logo.html` -> logo "METAL ONLINE" 512x181 con fondo transparente (se dibuja a 4x y se reduce).
- `fondo.html` -> fondo 1920x1080: ciudad cyberpunk con lluvia, luz azul a la izquierda y roja a la derecha.
- Fuentes: Russo One y Rajdhani (Google Fonts, licencia OFL) en `fuentes/`.

Volver a generar (con Playwright):  `node render_logo.js` y `node render_fondo.js` (salen en datos/arte/; el logo sale a
4x y hay que reducirlo a 512x181). Meterlos en el juego: `reemplazar_imagen.py` (ver su ayuda) y armar una actualizacion.

## Fondo animado (v6)
- `fondo_anim.html?t=0..1` dibuja un cuadro del bucle (lluvia, neon que parpadea, haces y resplandores que laten,
  chispas y un destello que recorre el ring); `node render_anim.js 16 <carpeta>` exporta 16 cuadros que empalman.
- `animar_fondo.py` mete los cuadros en mainbg_dontmove.bundle y cambia el componente UFOImageLoopUtil de
  loginscreen.bundle (lista de cuadros, intervalo 1/fps, sin inicio al azar).
- Logo v2: `logo2.html?f=BlackOps&s=80&ls=3&f2=Oxanium&s2=26&ls2=13` (opciones: render_opciones.js).
