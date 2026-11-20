// Live check of the lidar surface of the 3D view (Phase 6), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/lidar_check.js <port> <out folder> [keep]
// Imports the oblique AGL sample (m4t-testkmz-oblique-AGL.kmz) as "Live check lidar", opens its 3D view (the lidar
// surface on by default), follows the status bar until the surface is built, screenshots it with the lidar on and
// off, opens a new waypoint route far from the US (Paris) to see "No lidar here", reads the settings page's size and
// clears it, then deletes the routes it made (unless "keep": then the routes and the surface stay).
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3], keep = process.argv[4] === 'keep';
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

// Follows the status bar until it has said it is building and then hides or stops being busy; returns what it said
async function follow(page, limitMs) {
  const seen = [];
  const started = Date.now();
  while (Date.now() - started < limitMs) {
    const s = await page.evaluate(() => {
      const bar = document.querySelector('.mp-lidar-status');
      if (!bar) return null;
      const spin = bar.querySelector('.fa-spin');
      return {hidden: bar.hidden, busy: spin ? !spin.hidden : false, text: bar.textContent.trim()};
    });
    if (s && !s.hidden && seen[seen.length - 1] !== s.text) { seen.push(s.text); log('  status:', s.text, '(' + Math.round((Date.now() - started) / 1000) + ' s)'); }
    if (s && seen.length && (s.hidden || !s.busy)) return {seen, last: s};
    await page.waitForTimeout(1000);
  }
  return {seen, last: null, timedOut: true};
}

async function open3d(page, lidarWanted) {
  await page.click('.mp-layers-button');
  const box = await page.$('.mp-layers-lidar input');
  if ((await box.isChecked()) !== lidarWanted) await box.click();
  await page.click('.mp-layers-view:has-text("3D")');
  await page.click('.mp-layers-button');
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
  const before = (await api(page, 'GET', 'routes')).data.map(r => r.id);
  log('routes before', before);
  const made = [];
  try {
    const up = await page.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check lidar.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    const id = up.data && (up.data.id || (up.data.route && up.data.route.id));
    made.push(id);
    log('import', up.status, 'id', id);

    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    await page.click('.mp-layers-button');
    log('lidar checkbox on by default:', await page.isChecked('.mp-layers-lidar input'));
    await page.click('.mp-layers-button');
    const t0 = Date.now();
    await open3d(page, true);
    const built = await follow(page, 6 * 60 * 1000);
    log('built in', Math.round((Date.now() - t0) / 1000), 's:', JSON.stringify(built.last), built.timedOut ? 'TIMED OUT' : '');
    await page.waitForTimeout(6000);
    await page.screenshot({path: path.join(out, 'lidar-' + port + '-on.png')});
    log('attribution:', (await page.textContent('.maplibregl-ctrl-attrib-inner')).trim());

    await open3d(page, false);
    await page.waitForTimeout(5000);
    await page.screenshot({path: path.join(out, 'lidar-' + port + '-off.png')});
    const t1 = Date.now();
    await open3d(page, true);
    const again = await follow(page, 30000);
    log('on again (already built):', JSON.stringify(again.seen), Math.round((Date.now() - t1) / 1000), 's');

    // Far from the US: a new waypoint route, with the map's last view set to Paris
    const wp = await api(page, 'POST', 'routes', {name: 'Live check lidar Paris', route_type: 'waypoint', model: 'm4t'});
    made.push(wp.data && wp.data.id);
    await page.evaluate(() => localStorage.setItem('mission-planner:view', JSON.stringify({center: [2.3522, 48.8566], zoom: 16})));
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(2000);
    await open3d(page, true);
    const paris = await follow(page, 3 * 60 * 1000);
    log('Paris:', JSON.stringify(paris.seen), JSON.stringify(paris.last));
    await page.screenshot({path: path.join(out, 'lidar-' + port + '-paris.png')});

    await page.goto(base + '/plugins/' + SLUG + '/settings');
    log('settings:', (await page.textContent('#mp-lidar-usage')).trim());
    if (!keep) {
      await Promise.all([page.waitForNavigation(), page.click('#mp-lidar-clear')]);
      log('cleared:', (await page.textContent('#mp-lidar-done')).trim(), '|', (await page.textContent('#mp-lidar-usage')).trim());
    }
  } finally {
    if (!keep) for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    await browser.close();
  }
})();
