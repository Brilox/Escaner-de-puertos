/* Exporta la animacion de cada marco como cuadros PNG en bucle, con el MISMO motor que se uso para el video y la pagina
   (datos/marcos_beta/motor.js, modo bucle). Despues construir.py arma la hoja de cuadros y el efecto del juego.

     node tools/marcos/exportar_animaciones.js            (desde metal-revolution/, con Playwright instalado)

   Por cada marco: renderiza dos vueltas, guarda la segunda en datos/marcos_beta/cuadros/<marco>/ y comprueba que el
   primer cuadro de la vuelta siguiente sea identico al primero guardado (empalme perfecto). */
const { chromium } = require('playwright');
const path = require('path'); const fs = require('fs');

const BASE = path.resolve(__dirname, '..', '..', 'datos', 'marcos_beta');
const MARCOS = [            // [marco, segundos del bucle, cuadros por segundo, tamano del cuadro en px]
  ['founder', 8, 24, 192],
  ['bughunter', 12, 20, 192],   // mas largo: la arana da una vuelta completa al marco en cada bucle
  ['vanguard', 8, 24, 192],
  ['patcher', 8, 24, 192],
  ['hero', 8, 24, 192],
];

const PAGINA = `<meta charset="utf-8"><script src="motor.js"></script><script>
window.exportar = async (k, L, fps, px) => {
  const img = await Motor.cargar('juego/' + k + '_256.png');
  const c = document.createElement('canvas'); c.width = c.height = px;
  const x = c.getContext('2d', { willReadFrequently: true });
  const b = Motor.crearBucle(c, k, { img, bucle: L, fps });
  const N = b.N, out = []; let primero = null;
  for (let i = 0; i < N; i++) b.cuadro(i);
  for (let i = N; i < 2 * N; i++) { b.cuadro(i); out.push(c.toDataURL('image/png')); if (i === N) primero = x.getImageData(0, 0, px, px).data.slice(); }
  b.cuadro(2 * N); const d = x.getImageData(0, 0, px, px).data; let dif = 0;
  for (let i = 0; i < d.length; i++) if (d[i] !== primero[i]) dif++;
  return { N, cuadros: out, diferencias: dif };
};</script>`;

(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  await p.route('http://local.test/**', r => {
    const u = decodeURIComponent(new URL(r.request().url()).pathname);
    if (u === '/exportar.html') return r.fulfill({ body: PAGINA, contentType: 'text/html' });
    r.fulfill({ path: path.join(BASE, u) });
  });
  await p.goto('http://local.test/exportar.html');
  let mal = 0;
  for (const [k, L, fps, px] of MARCOS) {
    const r = await p.evaluate(a => window.exportar(...a), [k, L, fps, px]);
    const d = path.join(BASE, 'cuadros', k); fs.rmSync(d, { recursive: true, force: true }); fs.mkdirSync(d, { recursive: true });
    r.cuadros.forEach((u, i) => fs.writeFileSync(path.join(d, String(i).padStart(3, '0') + '.png'), Buffer.from(u.split(',')[1], 'base64')));
    console.log(`${k}: ${r.N} cuadros, bucle de ${L} s a ${fps} fps, empalme ${r.diferencias === 0 ? 'perfecto' : 'CON DIFERENCIAS: ' + r.diferencias}`);
    if (r.diferencias) mal++;
  }
  await b.close(); process.exit(mal ? 1 : 0);
})();
