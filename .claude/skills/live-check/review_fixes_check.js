// Live check of the code review's visible fixes (findings 2, 4, 5, 6, 7), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/review_fixes_check.js <port> <out folder>
// Routes list: imports m4e-test-waypoint.kmz (the import dialog describes a waypoint route), the copy dialog for it
// (keeps its heights), a delete the server refuses (answered 403 by the browser, nothing deleted). Area editor: an edit
// made while a Save is in flight (the PATCH held back 2 s) stays unsaved. An AGL route over the lidar terrain near the
// oblique AGL sample: Fetch terrain then Download at once, the KMZ arrives after the fetch. That route needs the lidar
// units there built (no OpenTopography call when they cover it, else one COP30 fill). Deletes its routes.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const WAYPOINT_KMZ = path.join(repo, 'mission_planner/tests/fixtures/dji-kmz/m4e-test-waypoint.kmz');
const LNG = -79.530568, LAT = 41.4878, D = 0.0003;
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
const text = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent.replace(/\s+/g, ' ').trim() : null; }, sel);

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
  const before = (await api(page, 'GET', 'routes')).data.map(r => r.id);
  log('routes before', before);
  const made = [];
  try {
    // -- routes list ---------------------------------------------------------------------------------------------
    await page.goto(base + '/plugins/' + SLUG + '/');
    await page.waitForSelector('#mp-import-file', {state: 'attached'});
    await page.setInputFiles('#mp-import-file', WAYPOINT_KMZ);
    await page.waitForSelector('#mp-import-dialog:not([hidden])', {timeout: 30000});
    const summary = await text(page, '#mp-import-summary');
    log('  import summary:', summary);
    expect(/TypeWaypoint, \d+ points/.test(summary) && !/Overlap/.test(summary) && !/Ortho/.test(summary),
           'the import dialog describes a waypoint route, without overlaps');
    await page.screenshot({path: path.join(out, 'import-' + port + '.png')});
    await page.click('#mp-import-close');
    await page.waitForTimeout(1500);
    const imported = (await api(page, 'GET', 'routes')).data.find(r => !before.includes(r.id));
    made.push(imported.id);

    await page.click('.mp-route-copy[data-id="' + imported.id + '"]');
    await page.selectOption('#mp-copy-model', 'm4t');
    const note = await text(page, '#mp-copy-note');
    log('  copy note:', note);
    expect(/keeps their heights/.test(note) && !/→/.test(note), 'the copy dialog says the waypoint route keeps its heights');
    await page.click('#mp-copy-cancel');

    await page.route('**/api/plugins/' + SLUG + '/routes/' + imported.id, r =>
      r.request().method() === 'DELETE' ? r.fulfill({status: 403, contentType: 'application/json', body: '{"detail":"CSRF"}'}) : r.continue());
    await page.click('.mp-route-delete[data-id="' + imported.id + '"]');
    await page.waitForTimeout(1000);
    const msg = await text(page, '#mp-routes-message');
    expect(/Could not delete the route/.test(msg), 'a refused delete says so: ' + msg);
    await page.unroute('**/api/plugins/' + SLUG + '/routes/' + imported.id);
    expect((await api(page, 'GET', 'routes')).data.some(r => r.id === imported.id), 'the route is still there');

    // -- an edit during a save -----------------------------------------------------------------------------------
    const polygon = [[LNG - D, LAT - D], [LNG + D, LAT - D], [LNG + D, LAT + D], [LNG - D, LAT + D]];
    const area = await api(page, 'POST', 'routes', {name: 'Live check review fixes', route_type: 'area', model: 'm4t',
      settings: {polygon, altitude_mode: 'agl', surface_follow: 'dsm', terrain_source: 'lidar', height: '40'}});
    made.push(area.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + area.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    await page.fill('#mp-height', '45');
    await page.dispatchEvent('#mp-height', 'change');
    let release;
    const held = new Promise(r => { release = r; });
    await page.route('**/api/plugins/' + SLUG + '/routes/' + area.data.id, async r => {
      if (r.request().method() === 'PATCH') { await held; }
      await r.continue();
    });
    await page.click('#mp-save-button');
    await page.waitForTimeout(300);
    await page.fill('#mp-height', '50');
    await page.dispatchEvent('#mp-height', 'change');
    release();
    await page.waitForTimeout(1500);
    const saveState = {status: await text(page, '#mp-save-status'), disabled: await page.$eval('#mp-save-button', b => b.disabled)};
    log('  after the save:', saveState);
    expect(saveState.status === 'Unsaved changes' && !saveState.disabled, 'the edit made during the save stays unsaved');
    await page.unroute('**/api/plugins/' + SLUG + '/routes/' + area.data.id);
    await page.click('#mp-save-button');
    await page.waitForTimeout(1500);
    expect((await api(page, 'GET', 'routes/' + area.data.id)).data.settings.height === '50', 'saving again keeps the last edit');

    // -- Download right after Fetch terrain ----------------------------------------------------------------------
    await page.click('#mp-fetch-terrain');
    await page.waitForTimeout(200);
    const [dl] = await Promise.all([page.waitForEvent('download', {timeout: 240000}), page.click('#mp-download')]);
    const file = path.join(out, 'after-fetch-' + port + '.kmz');
    await dl.saveAs(file);
    const listing = require('child_process').execFileSync('unzip', ['-l', file]).toString();
    log('  terrain status:', await text(page, '#mp-terrain-status'));
    expect(/wpmz\/res\/dsm\/wgs84_LIDAR10M_/.test(listing), 'the download waited for the fetch and carries the lidar terrain');
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.unrouteAll({behavior: 'ignoreErrors'}).catch(() => {});
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
