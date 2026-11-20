// Live check of the ASL hints and the automatic fetch of the takeoff point's ground height (Phase 12), headless:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/asl_hint_check.js <port> <out folder>
// Area editor: ASL picked without a takeoff point shows the hints and fetches nothing; picking the takeoff point
// fetches its height once (one real OpenTopography call), the hints go and the plan is made. A takeoff point moved
// while its fetch is on its way: the old answer is dropped (faked, delayed answers). Waypoint editor: a route opened
// in ASL without a height shows the hints and fetches nothing; a failed automatic fetch (faked) shows its reason in
// the hint and opens no dialog; then Fetch from elevation data fetches it (faked). Deletes the routes it made.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const LAT = 42.1034, LON = -85.020528;
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

const hints = page => page.evaluate(() => ['mp-asl-hint-takeoff', 'mp-asl-hint-mode'].map(id => { const e = document.getElementById(id); return e.hidden ? '(hidden)' : e.textContent; }));
const field = page => page.$eval('#mp-takeoff-altitude', e => e.value);
const dialog = page => page.$eval('#mp-elevation-dialog', e => e.hidden ? 'closed' : 'open');

async function pickTakeoff(page, dx, dy) {
  await page.click('#mp-takeoff-button');
  const box = await (await page.$('#mp-map canvas, .maplibregl-canvas')).boundingBox();
  await page.mouse.click(box.x + box.width / 2 + (dx || 0), box.y + box.height / 2 + (dy || 0));
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await (await browser.newContext({viewport: {width: 1400, height: 900}})).newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());
  const posts = [];
  page.on('response', r => { if (r.status() === 400) log('  400 from', r.request().method(), r.url().replace(base, '')); });
  page.on('request', r => { if (r.method() === 'POST' && /\/elevation$/.test(r.url())) posts.push(JSON.parse(r.postData())); });
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  log('routes before', (await api(page, 'GET', 'routes')).data.map(r => r.id));
  const made = [];
  try {
    // -- area editor
    const d = 0.0004, polygon = [[LON - d, LAT - d], [LON + d, LAT - d], [LON + d, LAT + d], [LON - d, LAT + d]];
    const area = await api(page, 'POST', 'routes', {name: 'Live check ASL area', route_type: 'area', model: 'm4t', settings: {polygon}});
    made.push(area.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + area.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    log('area opened (AGL): hints', await hints(page));
    await page.click('[data-seg="altitude_mode"][data-value="asl"]');
    await page.waitForTimeout(800);
    log('area ASL, no takeoff: hints', await hints(page), 'fetches', posts.length);
    const planned = page.waitForResponse(r => r.url().endsWith('/plan') && r.request().method() === 'POST' && r.status() === 200, {timeout: 30000});
    await pickTakeoff(page);
    await page.waitForTimeout(300);
    log('area takeoff picked: hints while fetching', await hints(page));
    const air = (await (await planned).json()).air;
    log('area after fetch: fetches', posts.length, 'field', await field(page), 'hints', await hints(page), 'dialog', await dialog(page),
        'air', air && air.reference, air && air.paths[0][0][2]);
    await page.screenshot({path: path.join(out, 'asl-hint-' + port + '-area.png')});

    // A takeoff point moved while its height is fetched: faked answers, the first one slow
    let n = 0;
    await page.route('**/elevation', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      const b = JSON.parse(route.request().postData()), k = ++n;
      await new Promise(r => setTimeout(r, k === 1 ? 2500 : 200));
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({lat: b.lat, lon: b.lon, orthometric: k === 1 ? 111 : 222, ellipsoidal: 77, fetched_at: 0})});
    });
    await page.click('#mp-takeoff-button');                       // clears the point
    await page.$eval('#mp-takeoff-altitude', e => { e.value = ''; });     // hidden without a takeoff point
    await page.$eval('#mp-takeoff-ellipsoidal-height', e => { e.value = ''; });
    await pickTakeoff(page, -40, 0);
    await page.waitForTimeout(500);
    await page.click('#mp-takeoff-button');                       // cleared during the slow fetch
    await pickTakeoff(page, 40, 0);
    await page.waitForTimeout(4000);
    log('area moved during fetch: faked fetches', n, 'field', await field(page), '(222 expected, not 111) hints', await hints(page));
    await page.unroute('**/elevation');

    // -- waypoint editor: a route opened in ASL without a height
    const before = posts.length;
    const points = [[0, 0], [0.0004, 0], [0.0004, 0.0004]].map(([a, b]) => ({lat: LAT + a, lon: LON + b, height: 300}));
    const wp = await api(page, 'POST', 'routes', {name: 'Live check ASL waypoints', route_type: 'waypoint', model: 'm4t',
      settings: {height: '300', height_mode: 'asl', takeoff: [LAT, LON], points}});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2500);
    log('waypoint opened in ASL, no height: hints', await hints(page), 'fetches on opening', posts.length - before);
    // A failed automatic fetch (faked): ALT, then ASL again
    await page.route('**/elevation', route => route.request().method() !== 'POST' ? route.continue()
      : route.fulfill({status: 502, contentType: 'application/json', body: JSON.stringify({error: 'The OpenTopography API key was refused'})}));
    await page.click('[data-seg="height_mode"][data-value="alt"]');
    await page.click('[data-seg="height_mode"][data-value="asl"]');
    await page.waitForTimeout(1000);
    log('waypoint failed auto fetch: hints', await hints(page), 'dialog', await dialog(page));
    await page.$eval('#mp-asl-hint-mode', e => e.scrollIntoView({block: 'center'}));
    await page.screenshot({path: path.join(out, 'asl-hint-' + port + '-failed.png')});
    await page.unroute('**/elevation');
    await page.route('**/elevation', route => { if (route.request().method() !== 'POST') return route.continue(); const b = JSON.parse(route.request().postData());
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({lat: b.lat, lon: b.lon, orthometric: 242.4, ellipsoidal: 208.2, fetched_at: 0})}); });
    await page.click('#mp-fetch-elevation');
    await page.waitForTimeout(1500);
    log('waypoint after Fetch: field', await field(page), 'hints', await hints(page), 'errors line', JSON.stringify(await page.textContent('#mp-errors')));
    await page.screenshot({path: path.join(out, 'asl-hint-' + port + '-waypoint.png')});
    await page.unroute('**/elevation');
  } finally {
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('elevation POSTs seen', posts.length, '(the real ones: the area editor\'s first; the rest faked)');
    log('console errors', errors);
    await browser.close();
  }
})();
