// Live check of the collisions and the route's height in 2D (Phase 11), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/collide2d_check.js <port> <out folder>
// Lidar surface on (a fresh browser profile). Imports the oblique AGL sample (the area editor) and reads the side
// panel's collision line in 2D, waiting for the lidar surface the 2D editor builds; then two ALT waypoint routes there
// with a takeoff height: one with a point 10 m up (expected: a collision, red and yellow on the 2D map), one with every
// point 150 m up ("stays above"). For each: the red and yellow pixels on the 2D map counted, the pointer tooltip read
// over the route's line, then the count in 3D at the editor's zoom and three levels out (expected: the same). The
// lidar surface is cleared at the end only if it was empty before. Deletes the routes it made.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const KMZ = path.join(repo, 'mission_planner/tests/fixtures/dji-kmz/m4t-testkmz-oblique-AGL.kmz');
const errors = [];
const log = (...a) => console.log(...a);

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body, SLUG]);
}

async function view(page, threeD) {
  await page.click('.mp-layers-button');
  await page.click('.mp-layers-view:has-text("' + (threeD ? '3D' : '2D') + '")');
  await page.click('.mp-layers-button');
}

// Waits while the status bar's spinner turns (the lidar surface building), and says what it said last
async function waitLidar(page) {
  const started = Date.now();
  let last = null;
  while (Date.now() - started < 6 * 60 * 1000) {
    const s = await page.evaluate(() => { const b = document.querySelector('.mp-lidar-status'); const sp = b && b.querySelector('.fa-spin'); return b ? {hidden: b.hidden, busy: sp ? !sp.hidden : false, text: b.textContent.trim()} : null; });
    if (s && !s.hidden) last = s.text;
    if (s && !s.hidden && s.busy) { await page.waitForTimeout(2000); continue; }
    if (Date.now() - started > 8000) { log('  lidar status seen:', JSON.stringify(last), Math.round((Date.now() - started) / 1000), 's'); return; }
    await page.waitForTimeout(1000);
  }
}

async function collisionLine(page) {
  return page.$eval('#mp-collisions', e => (e.hidden ? '(hidden)' : e.textContent) + (e.classList.contains('mp-hit') ? ' [red]' : ''));
}

// The 2D map's red and yellow pixels (the stretches' colours), from a screenshot of the map
async function stretchPixels(page, name) {
  const file = path.join(out, 'collide2d-' + port + '-' + name + '.png');
  await page.locator('#mp-map').screenshot({path: file});
  const b64 = fs.readFileSync(file).toString('base64');
  return page.evaluate(async b64 => {
    const img = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob());
    const c = new OffscreenCanvas(img.width, img.height), ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, img.width, img.height).data;
    let red = 0, yellow = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (Math.abs(d[i] - 229) < 12 && Math.abs(d[i + 1] - 57) < 14 && Math.abs(d[i + 2] - 53) < 14) red++;
      if (d[i] > 240 && Math.abs(d[i + 1] - 213) < 14 && d[i + 2] < 30) yellow++;
    }
    return {red, yellow};
  }, b64);
}

async function tooltipAt(page, x, y) {
  await page.mouse.move(x - 15, y - 10);
  await page.mouse.move(x, y, {steps: 3});
  await page.waitForTimeout(1500);
  return page.evaluate(() => { const t = document.querySelector('.mp-pointer-height'); return t && !t.hidden ? t.textContent + (t.classList.contains('mp-route-below') ? ' [red]' : '') : '(hidden)'; });
}

async function zoomOut(page, levels) {
  for (let i = 0; i < levels; i++) { await page.click('.maplibregl-ctrl-zoom-out'); await page.waitForTimeout(700); }
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const context = await browser.newContext({viewport: {width: 1400, height: 900}});
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  log('routes before', (await api(page, 'GET', 'routes')).data.map(r => r.id));
  await page.goto(base + '/plugins/' + SLUG + '/settings');
  const lidarBefore = (await page.textContent('#mp-lidar-usage')).trim();
  log('lidar before:', lidarBefore);
  const made = [];
  try {
    const up = await page.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check collisions 2D.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    const id = up.data && (up.data.id || (up.data.route && up.data.route.id));
    made.push(id);
    log('import', up.status, 'id', id);
    const planned = page.waitForResponse(r => r.url().endsWith('/plan') && r.request().method() === 'POST');
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    const air = (await (await planned).json()).air;
    await page.waitForSelector('.mp-layers-button');
    await waitLidar(page);
    await page.waitForTimeout(4000);
    log(' area 2D:', await collisionLine(page), JSON.stringify(await stretchPixels(page, 'area')));

    const lat0 = air.paths[0][0][1], lon0 = air.paths[0][0][0];
    for (const [name, low] of [['wp-low', 10], ['wp-high', 150]]) {
      const points = [[0, 0, 150], [0.0006, 0, 150], [0.0006, 0.0008, low], [0, 0.0008, 150]].map(([dlat, dlon, h]) => ({lat: +(lat0 + dlat).toFixed(9), lon: +(lon0 + dlon).toFixed(9), height: h}));
      const wp = await api(page, 'POST', 'routes', {name: 'Live check collisions 2D ' + name, route_type: 'waypoint', model: 'm4t',
        settings: {height: '150', height_mode: 'alt', takeoff_altitude: '200', takeoff: [lat0, lon0], points}});
      made.push(wp.data && wp.data.id);
      log(name, 'route', wp.status, wp.data && wp.data.id);
      await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
      await page.waitForSelector('.mp-wp-marker');
      await waitLidar(page);
      await page.waitForTimeout(4000);
      log(' ' + name + ' 2D:', await collisionLine(page), JSON.stringify(await stretchPixels(page, name)));
      const m = await page.$$eval('.mp-wp-marker', els => els.map(e => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }));
      const along = (a, b, f) => [m[a][0] + (m[b][0] - m[a][0]) * f, m[a][1] + (m[b][1] - m[a][1]) * f];
      log('  tooltip on the line 1-2:', await tooltipAt(page, ...along(0, 1, 0.5)));
      log('  tooltip on the line 2-3, near 3:', await tooltipAt(page, ...along(1, 2, 0.85)));
      log('  tooltip off the line:', await tooltipAt(page, ...along(0, 2, 0.5)));
      await view(page, true);
      await page.waitForTimeout(6000);
      log(' ' + name + ' 3D:', await collisionLine(page));
      await page.screenshot({path: path.join(out, 'collide2d-' + port + '-' + name + '-3d.png')});
      await zoomOut(page, 3);
      await page.waitForTimeout(5000);
      log(' ' + name + ' 3D zoomed out 3:', await collisionLine(page));
      await view(page, false);
      await page.waitForTimeout(1500);
    }

    if (/^0 |none|empty/i.test(lidarBefore || '')) {
      await page.goto(base + '/plugins/' + SLUG + '/settings');
      await Promise.all([page.waitForNavigation(), page.click('#mp-lidar-clear')]);
      log('lidar cleared:', (await page.textContent('#mp-lidar-usage')).trim());
    }
  } finally {
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    await browser.close();
  }
})();
