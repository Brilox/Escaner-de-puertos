const { chromium } = require('playwright');
const ops = JSON.parse(process.argv[2]);
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 2048, height: 724 } });
  for (const [nombre, qs] of ops) {
    await p.goto('file://' + __dirname + '/logo2.html?' + qs); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(250);
    await (await p.$('#logo')).screenshot({ path: __dirname + '/../../datos/arte/op_' + nombre + '.png', omitBackground: true });
  }
  await b.close();
})();
