// Live check of the 3D view's Relief (Phase 22), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/relief_check.js <port> <out folder> <route id>
// Copies the area route <route id> as "Live check relief" (its lidar units built or buildable), and in its editor: Relief
// off by default; turned on in 3D (the color-relief layer under the hillshade, the photo at 45%, the shading "igor"),
// screenshot; another basemap while it is on (still faint); the lidar off and on while it is on; 2D (all of it gone,
// the photo back); a reload (remembered, back on entering 3D); a new waypoint route ("Live check relief waypoints")
// in 3D with it on. Screenshots. Deletes its routes and leaves Relief off in this browser.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3], source = process.argv[4];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const errors = [], problems = [];
const log = (...a) => console.log(...a);
const expect = (ok, what) => { log((ok ? '  ok   ' : '  FAIL ') + what); if (!ok) problems.push(what); };

const INIT = () => { let ml; Object.defineProperty(window, 'maplibregl', {configurable: true, get: () => ml, set: v => {
  const o = Object.assign({}, v); o.Map = class extends v.Map { constructor(a) { super(a); window.__mpMap = this; } }; ml = o; }}); };

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body, SLUG]);
}

// What the map has: the relief layer (and what it lies under), the photo's opacity, the shading's method
const mapState = page => page.evaluate(() => {
  const m = window.__mpMap, ids = m.getStyle().layers.map(l => l.id), at = ids.indexOf('mp-relief');
  return {relief: at >= 0, under: at >= 0 ? ids[at + 1] : null, photo: m.getLayer('mp-basemap') ? m.getPaintProperty('mp-basemap', 'raster-opacity') : null,
          shade: m.getLayer('mp-hillshade') ? m.getPaintProperty('mp-hillshade', 'hillshade-method') : null};
});

async function inPanel(page, act) {
  await page.click('.mp-layers-button');
  await act();
  await page.click('.mp-layers-button');
}
const view = (page, label) => inPanel(page, () => page.click('.mp-layers-view:has-text("' + label + '")'));
const box = (page, cls) => inPanel(page, () => page.click('.' + cls + ' input'));
// Until the map is idle (or 10 s), then a moment for the last tiles to fade in
const settle = async page => {
  await page.evaluate(() => new Promise(r => { const m = window.__mpMap; if (m.loaded() && !m.isMoving()) return setTimeout(r, 300); m.once('idle', r); setTimeout(r, 10000); }));
  await page.waitForTimeout(1500);
};

async function untilBuilt(page) {
  const start = Date.now();
  while (Date.now() - start < 10 * 60 * 1000) {
    await page.waitForTimeout(2000);
    const text = await page.evaluate(() => { const b = document.querySelector('.mp-lidar-status'); return b && !b.hidden ? b.textContent : ''; });
    if (!/Building/.test(text)) break;
  }
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--disable-accelerated-2d-canvas']});
  const context = await browser.newContext({viewport: {width: 1400, height: 900}});
  await context.addInitScript(INIT);
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text() + ' ' + ((m.location() || {}).url || '')); });
  page.on('dialog', d => d.accept());
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  log('routes before', (await api(page, 'GET', 'routes')).data.map(r => r.id));
  await page.evaluate(() => { localStorage.setItem('mission-planner:lidar', 'on'); localStorage.removeItem('mission-planner:relief'); });
  const made = [];
  try {
    const src = (await api(page, 'GET', 'routes/' + source)).data;
    const copy = await api(page, 'POST', 'routes', {name: 'Live check relief', route_type: src.route_type, model: src.model, settings: src.settings});
    made.push(copy.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + copy.data.id);
    await page.waitForSelector('.mp-layers-button');
    await untilBuilt(page);
    expect(!(await page.isChecked('.mp-layers-relief input')), 'Relief is off by default');
    await view(page, '3D');
    await settle(page);
    let s = await mapState(page);
    expect(!s.relief && s.photo !== 0.45, '3D without Relief: no relief layer, the photo as it was');
    await page.screenshot({path: path.join(out, 'relief-' + port + '-off.png')});
    await box(page, 'mp-layers-relief');
    await settle(page);
    s = await mapState(page);
    log('  on:', JSON.stringify(s));
    expect(s.relief && s.under === 'mp-hillshade' && s.photo === 0.45 && s.shade === 'igor', 'Relief on: its layer under the hillshade, the photo faint, the stronger shading');
    await page.screenshot({path: path.join(out, 'relief-' + port + '-on.png')});

    const other = await page.evaluate(() => [...document.querySelectorAll('.mp-layers-panel input[type=radio]')].map(r => r.value).find(v => !document.querySelector('.mp-layers-panel input[type=radio][value="' + v + '"]').checked));
    if (other) {
      await inPanel(page, () => page.click('.mp-layers-panel input[type=radio][value="' + other + '"]'));
      await settle(page);
      s = await mapState(page);
      expect(s.relief && s.photo === 0.45, 'another basemap while it is on: still faint, the relief kept (' + other + ')');
    }
    await box(page, 'mp-layers-lidar');
    await settle(page);
    s = await mapState(page);
    expect(s.relief && s.under === 'mp-hillshade', 'the lidar turned off while it is on: the relief on the new ground');
    await box(page, 'mp-layers-lidar');
    await untilBuilt(page);
    await settle(page);
    expect((await mapState(page)).relief, 'and on again');

    await view(page, '2D');
    await page.waitForTimeout(1500);
    s = await mapState(page);
    expect(!s.relief && s.photo === 1, '2D: the relief gone, the photo back');

    await page.reload();
    await page.waitForSelector('.mp-layers-button');
    expect(await page.isChecked('.mp-layers-relief input'), 'remembered after a reload');
    await view(page, '3D');
    await settle(page);
    expect((await mapState(page)).relief, 'and back on entering 3D');

    const wp = await api(page, 'POST', 'routes', {name: 'Live check relief waypoints', route_type: 'waypoint', model: 'm4t'});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    await view(page, '3D');
    await settle(page);
    s = await mapState(page);
    expect(s.relief && s.under === 'mp-hillshade' && s.photo === 0.45, 'the waypoint editor: Relief in 3D too');
    await page.screenshot({path: path.join(out, 'relief-' + port + '-waypoint.png')});
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.evaluate(() => localStorage.removeItem('mission-planner:relief')).catch(() => {});
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
