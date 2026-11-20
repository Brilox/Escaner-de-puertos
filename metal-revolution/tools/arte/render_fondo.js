const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto('file://' + __dirname + '/fondo.html'); await p.waitForTimeout(500);
  await (await p.$('#c')).screenshot({ path: __dirname + '/../../datos/arte/fondo_1920x1080.png' });
  await b.close();
})();
