// Live check of the 3D view's "Loading elevation…" message (Phase 20), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/elevation_loading_check.js <port> <out folder>
// With the lidar surface off (this browser only: no lidar is built) and AWS's elevation tiles slowed by 1.5 s, in the
// area editor ("Live check elevation area") and a new waypoint route ("Live check elevation waypoints"): switching to
// 3D shows the message on the status bar while the tiles load, hides it once the map is drawn, shows it again when a
// zoom loads more, and leaving 3D during a load hides it. Screenshots while loading and after. Deletes its routes.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const LNG = -79.528168, LAT = 41.4898;
const SLOW_MS = 1500;
const errors = [], problems = [];
const log = (...a) => console.log(...a);
const expect = (ok, what) => { log((ok ? '  ok   ' : '  FAIL ') + what); if (!ok) problems.push(what); };

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body, SLUG]);
}

const bar = page => page.evaluate(() => {
  const b = document.querySelector('.mp-lidar-status');
  return b && !b.hidden ? b.textContent : null;
});

async function layers(page, view3d) {
  await page.click('.mp-layers-button');
  await page.click('.mp-layers-view:has-text("' + (view3d ? '3D' : '2D') + '")');
  await page.click('.mp-layers-button');
}

// What the bar says every 100 ms, until it has been hidden for 3 s after saying something (or 30 s pass)
async function watch(page) {
  const seen = [];
  const start = Date.now();
  let shownAt = null, hiddenSince = null;
  while (Date.now() - start < 30000) {
    const text = await bar(page);
    if (text && shownAt === null) shownAt = Date.now() - start;
    if (text && seen[seen.length - 1] !== text) seen.push(text);
    if (!text && shownAt !== null) { if (hiddenSince === null) hiddenSince = Date.now(); if (Date.now() - hiddenSince > 3000) break; }
    if (text) hiddenSince = null;
    await page.waitForTimeout(100);
  }
  return {seen, shownAt, hidden: !(await bar(page))};
}

async function checkEditor(page, where) {
  log(where);
  await layers(page, true);
  await page.waitForTimeout(700);
  expect(await bar(page) === 'Loading elevation…', where + ': switching to 3D says "Loading elevation…"');
  await page.screenshot({path: path.join(out, 'elevation-' + port + '-' + where + '-loading.png')});
  let w = await watch(page);
  log('  bar said', w.seen);
  // the message was there at 700 ms (above); the loading may have ended before this watch began
  expect(['', 'Loading elevation…'].indexOf(w.seen.join('|')) >= 0 && w.hidden, where + ': then hides once the map is drawn');
  await page.screenshot({path: path.join(out, 'elevation-' + port + '-' + where + '-drawn.png')});

  await page.evaluate(() => { const m = document.querySelector('.maplibregl-ctrl-zoom-out'); if (m) m.click(); });
  w = await watch(page);
  log('  after zooming out', w.seen);
  expect(w.seen.indexOf('Loading elevation…') >= 0 && w.hidden, where + ': a zoom that loads more says it again, then hides');

  await page.evaluate(() => { const m = document.querySelector('.maplibregl-ctrl-zoom-out'); if (m) m.click(); });
  await page.waitForTimeout(700);
  const during = await bar(page);
  await layers(page, false);
  await page.waitForTimeout(300);
  log('  during a load:', during, '- after leaving 3D:', await bar(page));
  expect(await bar(page) === null, where + ': leaving 3D hides it');
  await page.waitForTimeout(SLOW_MS + 1000);
  expect(await bar(page) === null, where + ': and it does not come back in 2D');
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await (await browser.newContext({viewport: {width: 1400, height: 900}})).newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text() + ' ' + ((m.location() || {}).url || '')); });
  page.on('dialog', d => d.accept());
  await page.route('**/elevation-tiles-prod/**', route => setTimeout(() => route.continue().catch(() => {}), SLOW_MS));
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  log('routes before', (await api(page, 'GET', 'routes')).data.map(r => r.id));
  await page.evaluate(() => localStorage.setItem('mission-planner:lidar', 'off'));
  const made = [];
  try {
    const d = 0.0015, polygon = [[LNG - d, LAT - d], [LNG + d, LAT - d], [LNG + d, LAT + d], [LNG - d, LAT + d]];
    const area = await api(page, 'POST', 'routes', {name: 'Live check elevation area', route_type: 'area', model: 'm4t', settings: {polygon}});
    made.push(area.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + area.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    expect(await bar(page) === null, 'area: nothing said in 2D');
    await checkEditor(page, 'area');

    await page.evaluate(([lng, lat]) => localStorage.setItem('mission-planner:view', JSON.stringify({center: [lng, lat], zoom: 16})), [LNG + 0.05, LAT]);
    const wp = await api(page, 'POST', 'routes', {name: 'Live check elevation waypoints', route_type: 'waypoint', model: 'm4t'});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    await checkEditor(page, 'waypoint');
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.unrouteAll({behavior: 'ignoreErrors'});
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
