// Arte para difundir: logo v2 en alta resolucion, imagen del post de Facebook (1080x1350) e icono del Discord (512x512).
//   node render_promo.js   -> datos/arte/logo_v2_4x.png, post_facebook_1080x1350.png, icono_discord_512.png
const { chromium } = require('playwright');
const path = require('path');
const out = path.join(__dirname, '..', '..', 'datos', 'arte');
(async () => {
  const b = await chromium.launch();
  let p = await b.newPage({ viewport: { width: 2048, height: 724 } });
  await p.goto('file://' + __dirname + '/logo2.html?f=BlackOps&s=80&ls=3&f2=Oxanium&s2=26&ls2=13');
  await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
  await (await p.$('#logo')).screenshot({ path: path.join(out, 'logo_v2_4x.png'), omitBackground: true });
  for (const [html, w, h, nombre] of [['promo.html', 1080, 1350, 'post_facebook_1080x1350.png'], ['icono.html', 512, 512, 'icono_discord_512.png']]) {
    p = await b.newPage({ viewport: { width: w, height: h } });
    await p.goto('file://' + __dirname + '/' + html); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(400);
    await p.screenshot({ path: path.join(out, nombre) });
  }
  await b.close();
})();
