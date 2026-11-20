// The release check on a stack started without the mounted plugin (SKILL.md, steps 4 to 6):
//   node release_check.js <port> install <zip>   load the zip in Administration > Plugins; the menu entry, node_modules
//   node release_check.js <port> check           each route type from the Pilot 2 samples (the first through the
//                                                routes list's Import; editor, KMZ download), an AGL route whose
//                                                editor fetches COP30 terrain (1 OpenTopography call), the settings page, an import of a
//                                                hand-made LuxODM export; keeps the routes (named "Release check ...")
//   node release_check.js <port> check settings-only   only the settings page and the LuxODM import
//   node release_check.js <port> delete          delete the plugin in Administration > Plugins
//   node release_check.js <port> cleanup         delete every route named "Release check ..." (after a failed run)
//   node release_check.js <port> after           the routes still there, each editor downloads without asking for
//                                                terrain; then deletes every route named "Release check ..."
// Logs in as MP_ADMIN_USER / MP_ADMIN_PASSWORD (the dev account, from the environment). Screenshots and downloads go to
// MP_OUT (the scratchpad). The webapp container is mp-webapp (8009). WebODM's dev pages fail to
// load livereload (port 35729) when no other WebODM serves it: those console errors are expected.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const REPO = path.resolve(__dirname, '../../..');
const { chromium } = require(REPO + '/node_modules/playwright');
const [port, mode, arg] = process.argv.slice(2);
const BASE = 'http://localhost:' + port;
const CONTAINER = 'mp-webapp';
const OUT = process.env.MP_OUT || '/tmp';
const FIXTURES = path.join(REPO, 'mission_planner/tests/fixtures/dji-kmz');
const SAMPLES = ['m4t-testkmz-oblique-AGL.kmz', 'm4t-test-linear-single.kmz', 'm4e-test-waypoint.kmz',
  'm4t-test-poi-waypoint.kmz', 'm4t-test-slope.kmz', 'm4t-test-geo.kmz'];
const PREFIX = 'Release check ';
const TERRAIN = '/webodm/app/media/plugins/mission_planner_data/terrain';
const log = (...a) => console.log(port, ...a);
const errors = [];
const inContainer = (...a) => { try { return execFileSync('docker', ['exec', CONTAINER, ...a]).toString().trim(); } catch (e) { return 'ERR ' + String(e.stderr || e).trim(); } };
const terrainFiles = () => inContainer('find', TERRAIN, '-type', 'f').split('\n').filter(Boolean);

async function open() {
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({acceptDownloads: true, viewport: {width: 1400, height: 900}});
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', d => d.accept());
  await page.goto(BASE + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  if (page.url().includes('/login')) throw new Error('login failed');
  return {browser, page};
}

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/mission_planner/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body]);
}

async function menuEntry(page) {
  await page.goto(BASE + '/dashboard/');
  return page.locator('a[href*="/plugins/mission_planner/"]').count();
}

// The editor's download, watching whether it asks for terrain (a POST to .../terrain)
async function download(page, id, file) {
  const asked = [];
  const watch = r => { if (r.method() === 'POST' && /\/terrain$/.test(r.url())) asked.push(r.url()); };
  page.on('request', watch);
  await page.goto(BASE + '/plugins/mission_planner/route/' + id);
  await page.waitForSelector('#mp-download:not([disabled])', {timeout: 60000});
  const [dl] = await Promise.all([page.waitForEvent('download', {timeout: 90000}), page.click('#mp-download')]);
  await dl.saveAs(file);
  await page.screenshot({path: file.replace(/\.kmz$/, '.png')});
  page.off('request', watch);
  const entries = execFileSync('python3', ['-c', 'import sys, zipfile; print(" ".join(sorted(zipfile.ZipFile(sys.argv[1]).namelist())))', file]).toString().trim();
  return {entries, askedTerrain: asked.length};
}

// A LuxODM export (luxodm_import.py's format) of one route whose terrain is a sample KMZ's DSM, with that sample's settings
function exportWithTerrain(kmz, settings) {
  const b64 = execFileSync('python3', ['-c', 'import sys, zipfile, base64; z = zipfile.ZipFile(sys.argv[1]); n = [n for n in z.namelist() if n.startswith("wpmz/res/dsm/")][0]; print(base64.b64encode(z.read(n)).decode())', kmz], {maxBuffer: 1 << 28}).toString().trim();
  const now = new Date().toISOString();
  return JSON.stringify({format: 'luxodm-routes', version: 1, routes: [{id: 101, owner: process.env.MP_ADMIN_USER,
    name: PREFIX + 'LuxODM import', route_type: 'area', model: 'm4t',
    settings,
    terrain_info: {dataset: 'KMZ', name: 'terrain.tif'}, terrain: b64, created_at: now, updated_at: now}]});
}

async function routeTypes(page) {
  for (const [i, k] of SAMPLES.entries()) {
    await page.goto(BASE + '/plugins/mission_planner/');
    let id;
    if (i === 0) {
      await page.setInputFiles('#mp-import-file', path.join(FIXTURES, k));   // the import's summary dialog, then Open
      await page.waitForSelector('#mp-import-open', {state: 'visible', timeout: 60000});
      await page.screenshot({path: `${OUT}/rc-${port}-import-dialog.png`});
      await Promise.all([page.waitForURL(/route\/\d+/, {timeout: 60000}), page.click('#mp-import-open')]);
      id = +page.url().match(/route\/(\d+)/)[1];
    } else {
      id = await page.evaluate(async ([name, b64]) => {   // the call the Import button makes
        const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
        const form = new FormData();
        form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), name);
        const res = await fetch('/api/plugins/mission_planner/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
        const d = await res.json();
        return (d.route && d.route.id) || d.id;
      }, [k, fs.readFileSync(path.join(FIXTURES, k)).toString('base64')]);
    }
    const r = (await api(page, 'GET', 'routes/' + id)).data;
    await api(page, 'PATCH', 'routes/' + id, {name: PREFIX + k});
    const d = await download(page, id, path.join(OUT, `rc-${port}-${id}.kmz`));
    log(`#${id} ${k}: ${r.route_type} ${r.model} terrain ${(r.terrain_info && r.terrain_info.name) || '-'} | asked terrain ${d.askedTerrain} | ${d.entries}`);
  }
  // COP30 terrain: the AGL sample's settings on a route with no terrain, so its editor's download fetches COP30
  // (one OpenTopography call) before it exports
  const route = (await api(page, 'POST', 'routes', {name: PREFIX + 'COP30', route_type: 'area', model: 'm4t'})).data;
  await api(page, 'PATCH', 'routes/' + route.id, {settings: await aglSettings(page)});
  const d = await download(page, route.id, path.join(OUT, `rc-${port}-${route.id}.kmz`));
  const info = (await api(page, 'GET', 'routes/' + route.id)).data.terrain_info || {};
  log(`#${route.id} COP30: terrain ${info.dataset} ${info.name} | asked terrain ${d.askedTerrain} | ${d.entries}`);
}

// The settings of the AGL sample route (the first sample, imported by routeTypes)
async function aglSettings(page) {
  const r = (await api(page, 'GET', 'routes')).data.find(r => r.name === PREFIX + SAMPLES[0]);
  if (!r) throw new Error('no route ' + PREFIX + SAMPLES[0] + ': run check without settings-only first');
  return (await api(page, 'GET', 'routes/' + r.id)).data.settings;
}

async function settingsAndImport(page) {
  await page.goto(BASE + '/plugins/mission_planner/settings');
  log('key source:', (await page.textContent('#mp-key-source')).replace(/\s+/g, ' ').trim());
  const file = path.join(OUT, `rc-${port}-luxodm-export.json`);
  fs.writeFileSync(file, exportWithTerrain(path.join(FIXTURES, SAMPLES[0]), await aglSettings(page)));
  await page.setInputFiles('#mp-import-routes-file', file);
  await Promise.all([page.waitForNavigation(), page.click('#mp-import-routes')]);
  log('import:', (await page.textContent('#mp-import-done')).trim(), '|', (await page.textContent('#mp-import-report tbody')).replace(/\s+/g, ' ').trim());
  await page.screenshot({path: `${OUT}/rc-${port}-settings.png`, fullPage: true});
  fs.unlinkSync(file);
}

(async () => {
  const {browser, page} = await open();
  if (mode === 'install') {
    log('menu entry before', await menuEntry(page));
    await page.goto(BASE + '/admin/app/plugin/');
    await Promise.all([page.waitForNavigation(), page.setInputFiles('#plugin-upload-file', arg)]);
    log('upload:', JSON.stringify(await page.$$eval('.messagelist li, .alert', els => els.map(e => e.innerText.trim()))));
    log('plugins row:', JSON.stringify(await page.$$eval('tr', trs => trs.map(t => t.innerText.replace(/\s+/g, ' ').trim()).filter(t => /mission_planner/i.test(t)))));
    await page.screenshot({path: `${OUT}/rc-${port}-installed.png`, fullPage: true});
    log('menu entry after', await menuEntry(page));
    log('installed:', inContainer('ls', '/webodm/app/media/plugins/mission_planner').split('\n').join(' '));
    log('node_modules:', inContainer('ls', '/webodm/app/media/plugins/mission_planner/public/node_modules').split('\n').join(' '));
  } else if (mode === 'check') {
    await page.goto(BASE + '/plugins/mission_planner/');
    log('routes before', (await api(page, 'GET', 'routes')).data.length);
    if (arg !== 'settings-only') await routeTypes(page);
    await settingsAndImport(page);
    await page.goto(BASE + '/plugins/mission_planner/');
    log('routes now', (await api(page, 'GET', 'routes')).data.map(r => `#${r.id} ${r.name}`).join(', '));
    log('terrain files:', terrainFiles().map(f => f.slice(TERRAIN.length + 1)).join(' '));
  } else if (mode === 'delete') {
    await page.goto(BASE + '/admin/app/plugin/');
    const href = await page.$$eval('a[href*="/delete/"]', as => (as.find(a => a.href.includes('mission_planner')) || {}).href);
    log('delete link', href ? href.replace(/^https?:\/\/[^/]+/, '') : 'none');
    await page.goto(href);
    log('delete:', JSON.stringify(await page.$$eval('.messagelist li, .alert', els => els.map(e => e.innerText.trim()))));
    log('plugin media:', inContainer('ls', '/webodm/app/media/plugins').split('\n').join(' '));
    log('terrain files kept:', terrainFiles().length);
    log('menu entry', await menuEntry(page));
  } else if (mode === 'cleanup') {
    await page.goto(BASE + '/plugins/mission_planner/');
    for (const r of (await api(page, 'GET', 'routes')).data.filter(r => r.name.startsWith(PREFIX))) log('deleted', r.id, (await api(page, 'DELETE', 'routes/' + r.id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.length, '| terrain left:', inContainer('find', TERRAIN, '-mindepth', '1') || 'none');
  } else if (mode === 'after') {
    await page.goto(BASE + '/plugins/mission_planner/');
    const routes = (await api(page, 'GET', 'routes')).data.filter(r => r.name.startsWith(PREFIX));
    log('routes kept', routes.length);
    for (const r of routes) {
      const full = (await api(page, 'GET', 'routes/' + r.id)).data;
      const d = await download(page, r.id, path.join(OUT, `rc-${port}-after-${r.id}.kmz`));
      log(`#${r.id} ${r.name}: terrain ${(full.terrain_info && full.terrain_info.name) || '-'} | asked terrain ${d.askedTerrain} | dsm in kmz ${/wpmz\/res\/dsm\//.test(d.entries)}`);
    }
    await page.goto(BASE + '/plugins/mission_planner/');
    for (const r of routes) log('deleted', r.id, (await api(page, 'DELETE', 'routes/' + r.id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.length);
    log('terrain left:', inContainer('find', TERRAIN, '-mindepth', '1') || 'none');
  }
  log('page errors', JSON.stringify(errors.filter(e => !/ERR_CONNECTION_REFUSED/.test(e))),
    '| livereload refusals', errors.filter(e => /ERR_CONNECTION_REFUSED/.test(e)).length);
  await browser.close();
})().catch(e => { console.log(port, 'FAILED', String(e)); process.exit(1); });
