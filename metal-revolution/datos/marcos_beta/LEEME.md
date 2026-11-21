# Marcos de la primera prueba beta

Cinco marcos exclusivos (diseño del proyecto) adaptados al formato de los marcos del juego:
Founder, Bug Hunter, Beta Vanguard, Elite Patcher y Revolution Hero.

- `juego/<marco>_256.png` y `_128.png`: imagen lista para el atlas de marcos (`headframe.bundle`). Lienzo cuadrado,
  ventana del avatar transparente y centrada; la ventana ocupa ~60% del ancho, como los marcos originales (58-74%).
- `juego/meta.json`: ventana del avatar (x, y, ancho, alto) y su contorno, en coordenadas de 256x256.
- `motor.js`: animación de cada marco en un canvas (chispas, glitch y araña, rayos, pulsos de datos, fuego).
  Sirve para la página, Discord y anuncios. En el teléfono el movimiento lo hace un efecto de partículas de Unity
  (los que trae el juego en `effects/prefab/ui/headframe`), no esta animación.

Cómo se hicieron: se recortaron de la imagen original separando el fondo por conexión desde el borde (así las partes
oscuras, como las púas de Revolution Hero, no quedan transparentes), y la ventana se detectó desde el centro (en
Bug Hunter y Elite Patcher se marcó a mano para conservar las arañas y el borde morado interior).

Pendiente: pintarlos en el atlas del OBB (en huecos de marcos que nadie gana, p. ej. 63 WeChat y 68 QQ, o los que se
agreguen), elegir el efecto de cada uno y probarlo en un teléfono. Después se entregan con
`python server/colaboradores.py marco <jugador> <id>`.
