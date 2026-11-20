// Live check of the route in the air in 3D and the waypoint height labels (Phase 8), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/route3d_check.js <port> <out folder> [lidar]
// Imports the oblique AGL sample (m4t-testkmz-oblique-AGL.kmz: AGL over Pilot 2's DSM, kept as the route's terrain) and
// reads its plan's "air"; opens it in 3D (the lidar surface off unless "lidar": then it waits for it to be built) and
// screenshots it; then makes an ALT waypoint route there with a takeoff height, one point below the ground (the takeoff height set 16 m low, the point 10 m up: red), and screenshots
// its labels in 2D and in 3D. Deletes the routes it made and, with "lidar", clears the lidar surface.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3], withLidar = process.argv[4] === 'lidar';
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

// Turns the lidar surface on or off and the view to 2D or 3D through the layers panel
async function view(page, threeD) {
  await page.click('.mp-layers-button');
  const box = await page.$('.mp-layers-lidar input');
  if ((await box.isChecked()) !== withLidar) await box.click();
  await page.click('.mp-layers-view:has-text("' + (threeD ? '3D' : '2D') + '")');
  await page.click('.mp-layers-button');
}

async function waitLidar(page) {
  if (!withLidar) return;
  const started = Date.now();
  while (Date.now() - started < 6 * 60 * 1000) {
    const s = await page.evaluate(() => { const b = document.querySelector('.mp-lidar-status'); const sp = b && b.querySelector('.fa-spin'); return b ? {hidden: b.hidden, busy: sp ? !sp.hidden : false, text: b.textContent.trim()} : null; });
    if (s && !s.hidden && s.busy) { await page.waitForTimeout(2000); continue; }
    if (Date.now() - started > 8000) { log('  lidar:', JSON.stringify(s), Math.round((Date.now() - started) / 1000), 's'); return; }
    await page.waitForTimeout(1000);
  }
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
  const made = [];
  try {
    const up = await page.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check 3D.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    const id = up.data && (up.data.id || (up.data.route && up.data.route.id));
    made.push(id);
    log('import', up.status, 'id', id);

    // The plan's air, as the editor asks for it
    const planned = page.waitForResponse(r => r.url().endsWith('/plan') && r.request().method() === 'POST');
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    const plan = await (await planned).json();
    await page.waitForSelector('.mp-layers-button');
    const air = plan.air;
    log('area air:', air && air.reference, 'paths', air && air.paths.length, 'points', air && air.paths[0].length,
        'first', air && JSON.stringify(air.paths[0][0]), 'drops', air && air.drops.length);
    await page.waitForTimeout(2000);
    await view(page, true);
    await waitLidar(page);
    await page.waitForTimeout(6000);
    await page.screenshot({path: path.join(out, 'route3d-' + port + '-area.png')});

    // A waypoint route: ALT with a takeoff height, the third point 10 m up
    const lat0 = air.paths[0][0][1], lon0 = air.paths[0][0][0];
    const points = [[0, 0, 40], [0.0006, 0, 40], [0.0006, 0.0008, 10], [0, 0.0008, 40]].map(([dlat, dlon, h]) => ({lat: +(lat0 + dlat).toFixed(9), lon: +(lon0 + dlon).toFixed(9), height: h}));
    const wp = await api(page, 'POST', 'routes', {name: 'Live check 3D waypoints', route_type: 'waypoint', model: 'm4t',
      settings: {height: '40', height_mode: 'alt', takeoff_altitude: '200', takeoff: [lat0, lon0], points}});
    made.push(wp.data && wp.data.id);
    log('waypoint route', wp.status, wp.data && wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(4000);
    const labels2d = await page.$$eval('.mp-wp-height', els => els.map(e => (e.hidden ? '(hidden)' : e.textContent) + (e.classList.contains('below') ? ' red' : '')));
    log('labels 2D:', JSON.stringify(labels2d));
    await page.screenshot({path: path.join(out, 'route3d-' + port + '-wp-2d.png')});
    await view(page, true);
    await waitLidar(page);
    await page.waitForTimeout(6000);
    const labels3d = await page.$$eval('.mp-wp-height', els => els.map(e => (e.hidden ? '(hidden)' : e.textContent) + (e.classList.contains('below') ? ' red' : '')));
    log('labels 3D:', JSON.stringify(labels3d));
    const offsets = await page.$$eval('.mp-wp-marker', els => els.map(e => e.style.transform));
    log('marker transforms 3D:', JSON.stringify(offsets));
    await page.screenshot({path: path.join(out, 'route3d-' + port + '-wp-3d.png')});

    if (withLidar) {
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
