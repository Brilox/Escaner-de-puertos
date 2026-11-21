const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 2048, height: 724 } });
  await p.goto('file://' + __dirname + '/logo.html'); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
  await (await p.$('#logo')).screenshot({ path: __dirname + '/../../datos/arte/logo_4x.png', omitBackground: true });
  await b.close();
})();
