// Live check of drawing and editing in 3D (Phase 9), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/edit3d_check.js <port> <out folder>
// Over the oblique AGL sample's area (the lidar surface off: AWS's terrain), in the 3D view:
// - an area route: draws a polygon with the Polygon tool, drags it with Edit, saves, and reads the saved corners;
// - an ALT and an AGL waypoint route: adds a point with a click, drags a numbered marker (in the air) and checks that
//   it stays under the pointer during the drag and after the plan comes back, saves, and reads the saved points.
// Screenshots each step. Deletes the routes it made.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const LAT0 = 42.1030, LON0 = -85.020728;
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

// The 3D view, the lidar surface off, through the layers panel
async function to3d(page) {
  await page.click('.mp-layers-button');
  const box = await page.$('.mp-layers-lidar input');
  if (await box.isChecked()) await box.click();
  await page.click('.mp-layers-view:has-text("3D")');
  await page.click('.mp-layers-button');
  await page.waitForTimeout(6000);
}

async function canvasBox(page) { return page.$eval('#mp-map canvas.maplibregl-canvas', c => { const r = c.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }); }
async function markerCentres(page) {
  return page.$$eval('.mp-wp-marker', els => els.map(e => { const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }));
}
async function save(page) {
  await page.click('#mp-save-button');
  await page.waitForFunction(() => /Saved|Could not/.test(document.getElementById('mp-save-status').textContent), null, {timeout: 15000});
  log(' save:', await page.textContent('#mp-save-status'));
}
const dist = (a, b) => Math.round(Math.hypot(a.x - b.x, a.y - b.y) * 10) / 10;

async function waypointRoute(page, made, mode) {
  const points = [[0, 0], [0.0004, 0.0003], [0.0008, 0]].map(([dlat, dlon]) => ({lat: LAT0 + dlat, lon: LON0 + dlon, height: 100}));
  const settings = {height: '100', height_mode: mode, takeoff: [LAT0 - 0.0003, LON0], points};
  if (mode === 'alt') settings.takeoff_altitude = '210';
  const wp = await api(page, 'POST', 'routes', {name: 'Live check edit 3D ' + mode, route_type: 'waypoint', model: 'm4t', settings});
  made.push(wp.data.id);
  log(mode, 'waypoint route', wp.status, wp.data.id);
  await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
  await page.waitForSelector('.mp-layers-button');
  await page.waitForTimeout(3000);
  await to3d(page);
  await page.click('.maplibregl-ctrl-zoom-out');                  // the points 100 m up in view, below the camera
  await page.waitForTimeout(4000);
  const before = await markerCentres(page);
  log(' markers in 3D', JSON.stringify(before.map(p => [Math.round(p.x), Math.round(p.y)])));

  // A click on the map adds a point
  const box = await canvasBox(page);
  await page.mouse.click(box.x + box.w * 0.7, box.y + box.h * 0.55);
  await page.waitForTimeout(3000);
  log(' after a click:', (await markerCentres(page)).length, 'markers (was', before.length + ')');

  // Drag point 2 by its marker, grabbed 3 px off its centre
  const start = (await markerCentres(page))[1];
  const grab = {x: start.x + 3, y: start.y + 2};
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  const misses = [];
  for (let k = 1; k <= 10; k++) {
    const at = {x: grab.x + 12 * k, y: grab.y + 6 * k};
    await page.mouse.move(at.x, at.y);
    await page.waitForTimeout(80);
    const c = (await markerCentres(page))[1];
    misses.push(dist({x: c.x + 3, y: c.y + 2}, at));
  }
  const drop = {x: grab.x + 120, y: grab.y + 60};
  await page.screenshot({path: path.join(out, 'edit3d-' + port + '-' + mode + '-dragging.png')});
  await page.mouse.up();
  log(' during the drag, the marker off the pointer by (px):', JSON.stringify(misses));
  await page.waitForTimeout(5000);
  const after = (await markerCentres(page))[1];
  log(' after the plan, marker 2 off the drop by', dist({x: after.x + 3, y: after.y + 2}, drop), 'px');
  const labels = await page.$$eval('.mp-wp-height', els => els.map(e => (e.hidden ? '(hidden)' : e.textContent)));
  log(' labels', JSON.stringify(labels));
  await page.screenshot({path: path.join(out, 'edit3d-' + port + '-' + mode + '-dropped.png')});
  await save(page);
  const saved = (await api(page, 'GET', 'routes/' + wp.data.id)).data.settings.points;
  log(' saved', saved.length, 'points; point 2 moved', JSON.stringify([+(saved[1].lat - points[1].lat).toFixed(6), +(saved[1].lon - points[1].lon).toFixed(6)]),
      'height', saved[1].height);
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
  await page.evaluate(([lon, lat]) => localStorage.setItem('mission-planner:view', JSON.stringify({center: [lon, lat], zoom: 16})), [LON0, LAT0]);
  log('routes before', (await api(page, 'GET', 'routes')).data.map(r => r.id));
  const made = [];
  try {
    // The area editor
    const area = await api(page, 'POST', 'routes', {name: 'Live check edit 3D area', route_type: 'area', model: 'm4t', settings: {height: '40'}});
    made.push(area.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + area.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    await to3d(page);
    const tools = await page.$$eval('[data-tool]', els => els.map(b => b.getAttribute('data-tool') + (b.disabled ? ' disabled' : '')));
    log('area tools in 3D', JSON.stringify(tools));
    await page.click('[data-tool=polygon]');
    const box = await canvasBox(page);
    const corners = [[0.4, 0.45], [0.6, 0.45], [0.62, 0.65], [0.38, 0.65]].map(([fx, fy]) => ({x: box.x + box.w * fx, y: box.y + box.h * fy}));
    for (const c of corners) { await page.mouse.click(c.x, c.y); await page.waitForTimeout(300); }
    await page.mouse.click(corners[0].x, corners[0].y);           // closes the polygon
    await page.waitForTimeout(3000);
    log('area message', JSON.stringify(await page.textContent('#mp-area-message')));
    await page.screenshot({path: path.join(out, 'edit3d-' + port + '-area-drawn.png')});
    await save(page);
    const got = (await api(page, 'GET', 'routes/' + area.data.id)).data;
    const drawn = got.settings.polygon;
    log('saved corners', JSON.stringify(drawn));
    // Edit: drag the area by its middle
    const mid = {x: box.x + box.w * 0.5, y: box.y + box.h * 0.55};
    await page.mouse.click(mid.x, mid.y);                         // selects it
    await page.waitForTimeout(500);
    await page.mouse.move(mid.x, mid.y);
    await page.mouse.down();
    for (let k = 1; k <= 8; k++) { await page.mouse.move(mid.x + 10 * k, mid.y); await page.waitForTimeout(60); }
    await page.mouse.up();
    await page.waitForTimeout(3000);
    await page.screenshot({path: path.join(out, 'edit3d-' + port + '-area-moved.png')});
    await save(page);
    const moved = (await api(page, 'GET', 'routes/' + area.data.id)).data.settings.polygon;
    log('moved by (lon, lat)', moved && drawn ? JSON.stringify([+(moved[0][0] - drawn[0][0]).toFixed(6), +(moved[0][1] - drawn[0][1]).toFixed(6)]) : '-');

    await waypointRoute(page, made, 'alt');
    await waypointRoute(page, made, 'agl');
  } finally {
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    await browser.close();
  }
})();
