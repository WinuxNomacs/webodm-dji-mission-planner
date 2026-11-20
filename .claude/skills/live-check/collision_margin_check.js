// Live check of the collision margin and the tighter lidar surface (Phase 22), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/collision_margin_check.js <port> <out folder> <route id>
// Copies the area route <route id> (its settings and outline; the place is not printed) as "Live check margin", opens it
// with the lidar on and waits while its units build (units built by an older surface are built again once). Then: the
// "Collision margin" field (2 m by default), the side panel's line with the margin, 0 m (the surface itself) and 40 m,
// feet in imperial, a margin saved with the route and read back after a reload, and a waypoint route ("Live check margin
// waypoints") 60 m above the ground beside the area: clear at 0.5 m, red at 100 m. Screenshots of the area route in 3D.
// Deletes its routes.
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

const said = page => page.evaluate(() => { const e = document.getElementById('mp-collisions'); return e && !e.hidden ? e.textContent : null; });
const status = page => page.evaluate(() => { const b = document.querySelector('.mp-lidar-status'); return b && !b.hidden ? b.textContent : ''; });

async function untilBuilt(page) {
  const start = Date.now();
  let text = await status(page);
  while (Date.now() - start < 10 * 60 * 1000) {
    await page.waitForTimeout(2000);
    text = await status(page);
    if (!/Building/.test(text)) break;
  }
  log('  lidar ready after ' + Math.round((Date.now() - start) / 1000) + ' s' + (text ? ' (' + text + ')' : ''));
}

// Types a margin into the field (in the shown units) and waits for the line to say something new
async function setMargin(page, value) {
  const before = await said(page);
  await page.evaluate(v => { const i = document.getElementById('mp-collision-margin'); i.value = v; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true})); }, String(value));
  for (let i = 0; i < 40 && (await said(page)) === before; i++) await page.waitForTimeout(250);
  return said(page);
}

async function open(page, id) {
  await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
  await page.waitForSelector('.mp-layers-button');
  await untilBuilt(page);
  for (let i = 0; i < 40 && !(await said(page)); i++) await page.waitForTimeout(250);
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
  await page.evaluate(() => { localStorage.setItem('mission-planner:lidar', 'on'); localStorage.setItem('mission-planner:units', 'metric'); });
  const made = [];
  try {
    const src = (await api(page, 'GET', 'routes/' + source)).data;
    const settings = Object.assign({}, src.settings);
    delete settings.collision_margin;                            // as a route saved before the field
    const copy = await api(page, 'POST', 'routes', {name: 'Live check margin', route_type: src.route_type, model: src.model, settings});
    made.push(copy.data.id);
    log('area route');
    await open(page, copy.data.id);
    expect(await page.inputValue('#mp-collision-margin') === '2', 'a route saved without a margin gets 2 m');
    const at2 = await said(page);
    log('  2 m:', at2);
    expect(/within 2 m|at least 2 m/.test(at2 || ''), 'the line says the 2 m margin');
    const at0 = await setMargin(page, 0);
    log('  0 m:', at0);
    expect(/goes into the surface|stays above the surface/.test(at0 || ''), 'at 0 m it checks against the surface itself');
    const at40 = await setMargin(page, 40);
    log('  40 m:', at40);
    expect(/comes within 40 m of the surface/.test(at40 || ''), 'at 40 m the route comes within it');
    await page.click('[data-units="imperial"]');
    await page.waitForTimeout(300);
    log('  imperial:', await said(page), '- field', await page.inputValue('#mp-collision-margin'), await page.textContent('#mp-collision-margin-label'));
    expect(/131 ft/.test((await said(page)) || '') && Math.abs(parseFloat(await page.inputValue('#mp-collision-margin')) - 131.23) < 0.05,
           'imperial: the line and the field in feet');
    await page.click('[data-units="metric"]');
    await setMargin(page, 2);

    // in 3D, the building at the middle of the route
    const center = src.settings.polygon.reduce((a, p) => [a[0] + p[0] / src.settings.polygon.length, a[1] + p[1] / src.settings.polygon.length], [0, 0]);
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-view:has-text("3D")');
    await page.click('.mp-layers-button');
    for (const [name, bearing] of [['south', 0], ['southeast', -40]]) {
      await page.evaluate(([c, bearing]) => new Promise(r => { window.__mpMap.jumpTo({center: c, zoom: 18.6, pitch: 62, bearing}); window.__mpMap.once('idle', r); }), [center, bearing]);
      await page.waitForTimeout(2500);
      await page.screenshot({path: path.join(out, 'margin-' + port + '-3d-' + name + '.png')});
    }

    // saved with the route
    await setMargin(page, 5);
    await page.click('#mp-save-button');
    await page.waitForTimeout(1500);
    await open(page, copy.data.id);
    expect(await page.inputValue('#mp-collision-margin') === '5', 'the margin is saved with the route');

    log('waypoint route');
    // a short line 60 m above the takeoff point's ground (ALT), west of the area's middle: above every tree and roof there
    const lawn = [center[1] + 0.00006, center[0] - 0.00065];
    const points = [[0, 0], [0.00018, 0]].map(([dlat, dlon]) => ({lat: +(lawn[0] + dlat).toFixed(9), lon: +(lawn[1] + dlon).toFixed(9), height: 60}));
    const wp = await api(page, 'POST', 'routes', {name: 'Live check margin waypoints', route_type: 'waypoint', model: 'm4t',
      settings: {height: '60', height_mode: 'alt', takeoff: lawn, points}});
    made.push(wp.data.id);
    await open(page, wp.data.id);
    expect(await page.inputValue('#mp-collision-margin') === '2', 'the waypoint editor has the field, 2 m by default');
    log('  2 m:', await said(page));
    const wp05 = await setMargin(page, 0.5);
    log('  0.5 m:', wp05);
    expect(/stays at least 0.5 m above/.test(wp05 || ''), 'a line 60 m up stays above a 0.5 m margin');
    const wp100 = await setMargin(page, 100);
    log('  100 m:', wp100);
    expect(/comes within 100 m of the surface/.test(wp100 || ''), 'and comes within a 100 m one');
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
