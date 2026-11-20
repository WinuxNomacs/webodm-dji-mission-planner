// The LuxODM import, live: LuxODM's routes -> its export_routes file -> the plugin's import on the settings page,
// compared through the editors' downloads (then kmz_compare.py). LuxODM's mission planner must be enabled.
//   KMZS=a.kmz,b.kmz node luxodm_import_check.js lux-import   import LuxODM's fixture KMZs into LuxODM (:8000)
//   node luxodm_import_check.js lux-copy <id> <m4t|m4e>        copy a LuxODM route for the other aircraft
//   node luxodm_import_check.js lux-download <id,id,...>       each route's fields and editor download, from LuxODM
//   node luxodm_import_check.js mp <port> <export.json>        import it on the settings page; each route's fields
//                                                              compared, its editor download; then ALL the dev
//                                                              account's routes on that stack are deleted
//   node luxodm_import_check.js lux-delete <id,id,...>         delete those LuxODM routes
// Logs in as MP_ADMIN_USER / MP_ADMIN_PASSWORD on both. LUXODM: LuxODM's checkout (default ../luxodm beside this
// repo). Output (fields, KMZs, screenshots) in MP_OUT (default the system temp folder)/luxodm-import.
const fs = require('fs');
const path = require('path');
const os = require('os');
const REPO = path.resolve(__dirname, '../../..');
const { chromium } = require(path.join(REPO, 'node_modules/playwright'));
const OUT = path.join(process.env.MP_OUT || os.tmpdir(), 'luxodm-import');
fs.mkdirSync(OUT, {recursive: true});
const FIXTURES = path.join(process.env.LUXODM || path.resolve(REPO, '../luxodm'), 'app/fixtures/dji-kmz');
const KMZS = (process.env.KMZS || '').split(',');
const [mode, a1, a2] = process.argv.slice(2);
const USER = process.env.MP_ADMIN_USER, PASS = process.env.MP_ADMIN_PASSWORD;
const errors = [];
const SLUG = mode && mode.startsWith('lux') ? 'mission-planner' : 'mission_planner';

async function open(base) {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({acceptDownloads: true, viewport: {width: 1400, height: 900}});
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', USER);
  await page.fill('input[name=password]', PASS);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  if (page.url().includes('/login')) throw new Error('login failed on ' + base);
  return {browser, page};
}

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body, SLUG]);
}

async function upload(page, name, b64) {
  return page.evaluate(async ([name, b64, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const form = new FormData();
    form.append('file', new Blob([bytes]), name);
    const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
    return {status: res.status, data: await res.json()};
  }, [name, b64, SLUG]);
}

async function download(page, base, id, file) {
  await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
  await page.waitForSelector('#mp-download:not([disabled])', {timeout: 60000});
  const [dl] = await Promise.all([page.waitForEvent('download', {timeout: 90000}), page.click('#mp-download')]);
  await dl.saveAs(file);
  await page.screenshot({path: file.replace(/\.kmz$/, '.png')});
}

const pick = r => ({name: r.name, route_type: r.route_type, model: r.model, settings: r.settings, terrain_info: r.terrain_info});

(async () => {
  if (mode === 'lux-import' || mode === 'lux-download' || mode === 'lux-delete' || mode === 'lux-copy') {
    const base = 'http://localhost:8000';
    const {browser, page} = await open(base);
    await page.goto(base + '/plugins/' + SLUG + '/');
    if (mode === 'lux-import') {
      console.log('routes before', (await api(page, 'GET', 'routes')).data.length);
      const ids = [];
      for (const k of KMZS) {
        const r = await upload(page, k, fs.readFileSync(path.join(FIXTURES, k)).toString('base64'));
        const id = r.data && r.data.route && r.data.route.id || r.data && r.data.id;
        console.log(k, r.status, id || JSON.stringify(r.data).slice(0, 200));
        if (id) ids.push(id);
      }
      console.log('ids', ids.join(','));
    } else if (mode === 'lux-copy') {
      const r = await api(page, 'POST', `routes/${a1}/copy`, {model: a2});
      console.log('copy', r.status, r.data && r.data.id, r.data && r.data.name, r.data && r.data.model);
    } else if (mode === 'lux-download') {
      for (const id of a1.split(',')) {
        const d = await api(page, 'GET', 'routes/' + id);
        fs.writeFileSync(path.join(OUT, `lux-${id}.json`), JSON.stringify(pick(d.data)));
        await download(page, base, id, path.join(OUT, `lux-${id}.kmz`));
        console.log('lux', id, d.data.name, d.data.route_type, 'terrain', d.data.terrain_info && d.data.terrain_info.name || '-');
      }
    } else {
      for (const id of a1.split(',')) console.log('deleted', id, (await api(page, 'DELETE', 'routes/' + id)).status);
      console.log('routes after', (await api(page, 'GET', 'routes')).data.length);
    }
    console.log('page errors', JSON.stringify(errors));
    await browser.close();
    return;
  }
  // mp <port> <export.json>
  const base = 'http://localhost:' + a1;
  const {browser, page} = await open(base);
  console.log(a1, 'routes before', (await api(page, 'GET', 'routes')).data.length);
  await page.goto(base + '/plugins/mission_planner/');
  await page.click('#mp-settings-link');
  await page.waitForSelector('#mp-import-routes-file');
  await page.setInputFiles('#mp-import-routes-file', a2);
  await Promise.all([page.waitForNavigation(), page.click('#mp-import-routes')]);
  console.log(a1, 'url', page.url().replace(base, ''));
  console.log(a1, 'done:', (await page.textContent('#mp-import-done')).trim());
  const rows = await page.$$eval('#mp-import-report tbody tr', trs => trs.map(tr => {
    const a = tr.querySelector('a');
    return {text: tr.innerText.replace(/\s+/g, ' ').trim(), href: a && a.getAttribute('href')};
  }));
  await page.screenshot({path: path.join(OUT, `mp${a1}-report.png`), fullPage: true});
  await page.reload();
  console.log(a1, 'after reload: report shown', await page.isVisible('#mp-import-report'), '| routes', (await api(page, 'GET', 'routes')).data.length);
  for (const row of rows) {
    console.log(a1, 'report:', row.text);
    if (!row.href) continue;
    const luxId = row.text.match(/^#(\d+)/)[1];
    const id = row.href.match(/route\/(\d+)$/)[1];
    const d = await api(page, 'GET', 'routes/' + id);
    const lux = JSON.parse(fs.readFileSync(path.join(OUT, `lux-${luxId}.json`)));
    console.log(a1, `#${luxId} -> #${id} same fields:`, JSON.stringify(pick(d.data)) === JSON.stringify(lux));
    await download(page, base, id, path.join(OUT, `mp${a1}-${luxId}.kmz`));
  }
  for (const r of (await api(page, 'GET', 'routes')).data) console.log(a1, 'deleted', r.id, (await api(page, 'DELETE', 'routes/' + r.id)).status);
  console.log(a1, 'routes after', (await api(page, 'GET', 'routes')).data.length);
  console.log(a1, 'page errors', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.log('FAILED', String(e)); process.exit(1); });
