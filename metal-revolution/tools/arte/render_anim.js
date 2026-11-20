const { chromium } = require('playwright');
const N = +process.argv[2], out = process.argv[3];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  for (let i = 0; i < N; i++) {
    await p.goto('file://' + __dirname + '/fondo_anim.html?t=' + (i / N)); await p.waitForTimeout(150);
    await (await p.$('#c')).screenshot({ path: out + '/' + String(i).padStart(3, '0') + '.png' });
  }
  await b.close();
})();
