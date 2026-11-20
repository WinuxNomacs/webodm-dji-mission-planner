// Live check of the height under the pointer (Phase 7), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/pointer_check.js <port> <out folder>
// Imports the oblique AGL sample as "Live check pointer", hovers the map in 2D (terrain: no lidar built yet), in
// imperial units, in 3D once the lidar surface is built, and in 2D again (now lidar); then a new waypoint route's
// map. Deletes its routes and clears the lidar surface (the settings page) at the end; remove the lidar index by
// hand afterwards (see SKILL.md).
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

// Moves the pointer over the map (fractions of its size) and reads the tooltip
async function hover(page, fx, fy, label) {
  const box = await page.locator('#mp-map').boundingBox();
  await page.mouse.move(box.x + box.width * fx - 20, box.y + box.height * fy - 20);
  await page.mouse.move(box.x + box.width * fx, box.y + box.height * fy, {steps: 3});
  await page.waitForTimeout(2500);
  const tip = await page.evaluate(() => { const t = document.querySelector('.mp-pointer-height'); return t && !t.hidden ? t.innerText.replace(/\n/g, ' | ') : '(hidden)'; });
  log('  ' + label + ':', tip);
  return tip;
}

async function layers(page, view3d) {
  await page.click('.mp-layers-button');
  await page.click('.mp-layers-view:has-text("' + (view3d ? '3D' : '2D') + '")');
  await page.click('.mp-layers-button');
}

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await (await browser.newContext({viewport: {width: 1400, height: 900}})).newPage();
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
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check pointer.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    const id = up.data.id || up.data.route.id;
    made.push(id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    await hover(page, 0.5, 0.5, '2D before any 3D view');
    log('  cursor over the map:', await page.evaluate(() => getComputedStyle(document.querySelector('.maplibregl-canvas')).cursor));
    await page.screenshot({path: path.join(out, 'pointer-' + port + '-2d.png')});
    await page.click('[data-units="imperial"]');
    await hover(page, 0.5, 0.5, '2D, imperial');
    await page.click('[data-units="metric"]');

    await layers(page, true);
    const started = Date.now();
    while (Date.now() - started < 300000) {                     // until the status bar has gone (built)
      await page.waitForTimeout(2000);
      const busy = await page.evaluate(() => { const b = document.querySelector('.mp-lidar-status'); return b && !b.hidden && b.textContent.indexOf('Building') >= 0; });
      if (!busy && Date.now() - started > 4000) break;
    }
    log('  built after', Math.round((Date.now() - started) / 1000), 's');
    await page.waitForTimeout(4000);
    await hover(page, 0.5, 0.55, '3D, lidar built');
    await page.screenshot({path: path.join(out, 'pointer-' + port + '-3d.png')});
    await layers(page, false);
    await page.waitForTimeout(2000);
    await hover(page, 0.5, 0.5, '2D after the 3D view');
    await hover(page, 0.3, 0.4, '2D elsewhere');
    await page.mouse.move(5, 5);
    await page.waitForTimeout(500);
    log('  pointer off the map:', await page.evaluate(() => document.querySelector('.mp-pointer-height').hidden ? '(hidden)' : 'SHOWN'));

    const wp = await api(page, 'POST', 'routes', {name: 'Live check pointer waypoint', route_type: 'waypoint', model: 'm4t'});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    await hover(page, 0.5, 0.5, 'waypoint editor, 2D');

    await page.goto(base + '/plugins/' + SLUG + '/settings');
    await Promise.all([page.waitForNavigation(), page.click('#mp-lidar-clear')]);
    log('lidar:', (await page.textContent('#mp-lidar-usage')).trim());
  } finally {
    for (const id of made) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors.filter(e => e.indexOf('ERR_CONNECTION_REFUSED') < 0));
    await browser.close();
  }
})();
