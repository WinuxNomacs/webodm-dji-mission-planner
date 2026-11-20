// Live check of the takeoff point's heights (ellipsoidal in the KMZ, above sea level in the editor), headless:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/takeoff_check.js <port> <out folder>
// Imports Pilot 2's TestAreaRoute.kmz (above the ground, no DSM) as "Live check takeoff", reads the editor's "Ground
// height at the takeoff point (m above sea level)", downloads the KMZ and compares its takeOffRefPoint with Pilot 2's
// own (they must match: ellipsoidal in, ellipsoidal out). Deletes the route; the geoid grid it downloaded stays in
// mission_planner_data/grids (remove it by hand to leave the stack as found).
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const {execFileSync} = require('child_process');
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const KMZ = path.join(repo, 'mission_planner/tests/fixtures/dji-kmz/TestAreaRoute.kmz');
const refPoint = file => (execFileSync('unzip', ['-p', file, 'wpmz/template.kml']).toString().match(/<wpml:takeOffRefPoint>([^<]*)/) || [])[1];

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({acceptDownloads: true, viewport: {width: 1400, height: 900}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  const api = (method, p) => page.evaluate(async ([method, p, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'X-CSRFToken': csrf}});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, SLUG]);
  console.log('routes before', (await api('GET', 'routes')).data.map(r => r.id));
  let id;
  try {
    const up = await page.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check takeoff.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    id = up.data.id || up.data.route.id;
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    await page.waitForSelector('#mp-download:not([disabled])', {timeout: 60000});
    console.log('editor field (m above sea level):', await page.inputValue('#mp-takeoff-altitude'));
    const [dl] = await Promise.all([page.waitForEvent('download', {timeout: 90000}), page.click('#mp-download')]);
    const file = path.join(out, 'takeoff-' + port + '.kmz');
    await dl.saveAs(file);
    console.log('Pilot 2 takeOffRefPoint:   ', refPoint(KMZ));
    console.log('exported takeOffRefPoint:  ', refPoint(file));
    fs.unlinkSync(file);
  } finally {
    if (id) console.log('delete', id, (await api('DELETE', 'routes/' + id)).status);
    console.log('routes after', (await api('GET', 'routes')).data.map(r => r.id));
    console.log('page errors', errors);
    await browser.close();
  }
})();
