// Live check of the lidar terrain of AGL routes (Phase 14), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/lidar_terrain_check.js <port> <out folder>
// Imports the oblique AGL sample (oblique AGL, Pilot 2's DSM) as "Live check lidar terrain", fetches its terrain with
// the Terrain choice on Lidar surface (waiting while the units build), downloads its KMZ (<out>/lidar-<port>.kmz),
// then COP30 (<out>/cop30-<port>.kmz); a waypoint AGL route's ground heights from the lidar (saved, then read back);
// a route in Paris and one over 4 km2 falling back to COP30 with their reasons. About 6 OpenTopography calls
// (3 COP30 fetches, each with a Point Elevation call). Deletes its routes. Afterwards: compare the KMZs' DSMs
// (dsm_compare.py), remove the lidar units the check built and the GEOID18 grid (see SKILL.md).
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const KMZ = path.join(repo, 'mission_planner/tests/fixtures/dji-kmz/m4t-testkmz-oblique-AGL.kmz');
const LNG = -79.528168, LAT = 41.4898;
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

const text = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent : null; }, sel);

// Waits until the selector's text matches done (or fails), logging the progress lines seen
async function waitText(page, sel, done, seconds) {
  const seen = new Set(), started = Date.now();
  while (Date.now() - started < seconds * 1000) {
    const t = await text(page, sel);
    if (t && !seen.has(t)) { seen.add(t); log('    ' + Math.round((Date.now() - started) / 1000) + ' s: ' + t); }
    if (t && done.test(t)) return {text: t, seen: [...seen]};
    const dialog = await page.evaluate(() => { const d = document.querySelector('#mp-elevation-dialog'); return d && !d.hidden ? d.textContent.replace(/\s+/g, ' ').trim() : null; });
    if (dialog) return {text: 'DIALOG: ' + dialog, seen: [...seen]};
    await page.waitForTimeout(1000);
  }
  return {text: await text(page, sel), seen: [...seen], timedOut: true};
}

async function download(page, file) {
  const [dl] = await Promise.all([page.waitForEvent('download', {timeout: 120000}), page.click('#mp-download')]);
  await dl.saveAs(file);
  return fs.statSync(file).size;
}

async function areaRoute(page, name, polygon) {
  const r = await api(page, 'POST', 'routes', {name, route_type: 'area', model: 'm4t',
    settings: {polygon, altitude_mode: 'agl', surface_follow: 'dsm', height: '60'}});
  return r.data.id;
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const context = await browser.newContext({viewport: {width: 1400, height: 900}, acceptDownloads: true});
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
  let cop30Fetches = 0;
  try {
    // -- the oblique AGL sample: lidar, then COP30 --------------------------------------------------------------------
    const up = await page.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check lidar terrain.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    const id = up.data.id || up.data.route.id;
    made.push(id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    log('oblique AGL sample (route ' + id + ')');
    log('  area', await text(page, '#mp-sum-area'), '| terrain', await text(page, '#mp-terrain-status'));
    expect(await page.evaluate(() => document.querySelector('[data-seg="terrain_source"][data-value="lidar"]').classList.contains('active')),
           'the Terrain choice is on Lidar surface for a route saved before it existed');
    await page.click('#mp-fetch-terrain');
    let w = await waitText(page, '#mp-terrain-status', /terrain fetched|DIALOG/, 420);
    expect(/^Lidar terrain \(10 m/.test(w.text), 'lidar terrain fetched: ' + w.text);
    log('  waited through', w.seen.filter(t => /Building/.test(t)).length, 'progress lines');
    if (/COP30/.test(w.text)) cop30Fetches++;
    await page.screenshot({path: path.join(out, 'lidar-terrain-' + port + '-2d.png')});
    const lidarSize = await download(page, path.join(out, 'lidar-' + port + '.kmz'));
    log('  lidar KMZ', lidarSize, 'bytes');

    await page.click('.mp-layers-button');
    await page.click('.mp-layers-view:has-text("3D")');
    await page.click('.mp-layers-button');
    await page.waitForTimeout(8000);
    await page.screenshot({path: path.join(out, 'lidar-terrain-' + port + '-3d.png')});
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-view:has-text("2D")');
    await page.click('.mp-layers-button');

    await page.click('[data-seg="terrain_source"][data-value="cop30"]');
    log('  after choosing COP30:', await text(page, '#mp-terrain-status'));
    expect(/it is fetched again on export/.test(await text(page, '#mp-terrain-status')), 'the status says the lidar terrain is fetched again for COP30');
    const cop30Size = await download(page, path.join(out, 'cop30-' + port + '.kmz'));   // the export fetches COP30 first
    cop30Fetches++;
    w = await waitText(page, '#mp-terrain-status', /terrain fetched|DIALOG/, 120);
    expect(/^COP30 terrain fetched /.test(w.text) && !/: [a-z]/.test(w.text), 'COP30 chosen, no reason given: ' + w.text);
    log('  COP30 KMZ', cop30Size, 'bytes');

    // -- a waypoint AGL route ----------------------------------------------------------------------------------------
    const points = [[LAT, LNG], [LAT + 0.0008, LNG + 0.0012], [LAT - 0.0006, LNG + 0.002]].map(([lat, lon]) => ({lat, lon}));
    const wp = await api(page, 'POST', 'routes', {name: 'Live check lidar terrain waypoints', route_type: 'waypoint', model: 'm4t',
      settings: {height_mode: 'agl', height: '50', points}});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    log('waypoint AGL route (' + wp.data.id + ')');
    await page.click('#mp-fetch-grounds');
    w = await waitText(page, '#mp-ground-status', /All points have their ground height|without/, 420);
    expect(/All points have their ground height/.test(w.text), 'the points have their ground heights: ' + w.text);
    await page.click('#mp-save-button');
    await page.waitForTimeout(2000);
    const saved = (await api(page, 'GET', 'routes/' + wp.data.id)).data;
    const grounds = saved.settings.points.map(p => p.ground);
    log('  grounds', grounds, '| terrain', saved.terrain_info && saved.terrain_info.dataset);
    expect(saved.terrain_info && /^Lidar/.test(saved.terrain_info.dataset), 'the waypoint route\'s terrain is the lidar\'s');
    fs.writeFileSync(path.join(out, 'waypoint-grounds-' + port + '.json'), JSON.stringify(saved.settings.points));

    // -- fallbacks ---------------------------------------------------------------------------------------------------
    const d = 0.0006;
    for (const [name, lng, lat, dx, dy, why] of [
      ['Live check lidar terrain Paris', 2.3522, 48.8566, d, d, /outside the conterminous US/],
      ['Live check lidar terrain large', LNG, LAT, 0.012, 0.008, /lidar is used up to 4 km2/]]) {
      const rid = await areaRoute(page, name, [[lng - dx, lat - dy], [lng + dx, lat - dy], [lng + dx, lat + dy], [lng - dx, lat + dy]]);
      made.push(rid);
      await page.goto(base + '/plugins/' + SLUG + '/route/' + rid);
      await page.waitForSelector('.mp-layers-button');
      await page.waitForTimeout(3000);
      await page.click('#mp-fetch-terrain');
      cop30Fetches++;
      w = await waitText(page, '#mp-terrain-status', /terrain fetched|DIALOG/, 120);
      expect(why.test(w.text), name + ': ' + w.text);
    }
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('COP30 fetches (each about 2 OpenTopography calls):', cop30Fetches);
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
