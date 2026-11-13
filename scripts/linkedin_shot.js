// Renders linkedin/*.html (scripts/linkedin_images.py) to PNG. Needs the web/ folder served on :8765? No: files are self-contained.
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2 });
  for (const n of ['1_network', '2_areas']) {
    await p.goto('file://' + path.resolve('linkedin/' + n + '.html'));
    await p.waitForTimeout(1500);
    await (await p.$('#card')).screenshot({ path: 'linkedin/' + n + '.png' });
  }
  await b.close();
})();
