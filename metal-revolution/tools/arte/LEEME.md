# Arte de Metal Online (pantalla de inicio de sesion)

Diseno propio, generado por codigo (no usa arte del juego):
- `logo.html` -> logo "METAL ONLINE" 512x181 con fondo transparente (se dibuja a 4x y se reduce).
- `fondo.html` -> fondo 1920x1080: ciudad cyberpunk con lluvia, luz azul a la izquierda y roja a la derecha.
- Fuentes: Russo One y Rajdhani (Google Fonts, licencia OFL) en `fuentes/`.

Volver a generar (con Playwright):  `node render_logo.js` y `node render_fondo.js` (salen en datos/arte/; el logo sale a
4x y hay que reducirlo a 512x181). Meterlos en el juego: `reemplazar_imagen.py` (ver su ayuda) y armar una actualizacion.
