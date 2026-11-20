// node .claude/skills/live-check/settings_check.js <port> <mode: nokey | env>
// nokey: the stack started with MP_NO_KEY=1, and a throwaway non-admin user "mpcheck" (password
// "mpcheck-throwaway-1") made first and deleted after. env: the stack started with the key. Logs in as
// MP_ADMIN_USER / MP_ADMIN_PASSWORD (the dev account, from the environment).
// Checks the DJI Mission Planner settings page live. The real key is read from the repo's .env and never printed:
// only whether a page or message contains it.
const fs = require('fs');
const REPO = require('path').join(__dirname, '../../..');
const { chromium } = require(REPO + '/node_modules/playwright');
const OUT = process.env.MP_OUT || '/tmp';  // screenshots s-<port>-*.png (the scratchpad)
const port = process.argv[2], mode = process.argv[3];
const BASE = 'http://localhost:' + port;
const line = fs.readFileSync(REPO + '/.env', 'utf8').split('\n').find(l => l.startsWith('WO_OPENTOPOGRAPHY_API_KEY='));
const KEY = line.slice('WO_OPENTOPOGRAPHY_API_KEY='.length).replace(/["'\r\s]/g, '');
const WRONG = '0'.repeat(32);
const log = (...a) => console.log(port, ...a);

async function login(page, user, pass) {
  await page.goto(BASE + '/login/');
  await page.fill('input[name=username]', user);
  await page.fill('input[name=password]', pass);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
}

async function api(page, method, path, body) {
  return page.evaluate(async ([method, path, body]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/mission_planner/' + path, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, path, body]);
}

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await (await browser.newContext()).newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await login(page, process.env.MP_ADMIN_USER, process.env.MP_ADMIN_PASSWORD);
  log('routes before', (await api(page, 'GET', 'routes')).data.length);

  await page.goto(BASE + '/plugins/mission_planner/');
  log('admin sees Settings button', await page.isVisible('#mp-settings-link'));
  await page.screenshot({path: `${OUT}/s-${port}-list.png`});
  await page.click('#mp-settings-link');
  await page.waitForSelector('#mp-key-source');
  log('source:', (await page.textContent('#mp-key-source')).replace(/\s+/g, ' ').trim());
  await page.screenshot({path: `${OUT}/s-${port}-${mode}-page.png`, fullPage: true});

  if (mode === 'env') {
    log('field disabled', await page.isDisabled('#mp-api-key'), 'save disabled', await page.isDisabled('#mp-key-save'));
    log('page has key', (await page.content()).includes(KEY));
  } else {
    await page.fill('#mp-api-key', WRONG);
    await Promise.all([page.waitForNavigation(), page.click('#mp-key-save')]);
    log('wrong key:', (await page.textContent('#mp-settings-error')).trim(), '| repeats it:', (await page.content()).includes(WRONG));
    await page.screenshot({path: `${OUT}/s-${port}-wrong.png`, fullPage: true});

    await page.fill('#mp-api-key', KEY);
    await Promise.all([page.waitForNavigation(), page.click('#mp-key-save')]);
    log('real key:', (await page.textContent('#mp-settings-done')).trim(), '| source:', (await page.textContent('#mp-key-source')).replace(/\s+/g, ' ').trim(), '| page has key:', (await page.content()).includes(KEY));
    await page.screenshot({path: `${OUT}/s-${port}-saved.png`, fullPage: true});

    const route = (await api(page, 'POST', 'routes', {name: 'MP settings check', route_type: 'area', model: 'm4t'})).data;
    const el = await api(page, 'POST', `routes/${route.id}/elevation`, {lat: 42.1030, lon: -85.020728});
    log('takeoff height', el.status, el.data && el.data.orthometric, el.data && el.data.ellipsoidal);
    const DLON = 1 / (111320 * Math.cos(42.103 * Math.PI / 180)), DLAT = 1 / 110574;
    const lon = -85.020728, lat = 42.1030;
    const polygon = [[lon, lat], [lon + 60 * DLON, lat], [lon + 60 * DLON, lat + 40 * DLAT], [lon, lat + 40 * DLAT]];
    const tr = await api(page, 'POST', `routes/${route.id}/terrain`, {polygon, direction: 0, height: 30, cameras: ['visable', 'ir'],
      overlap_h: 80, overlap_w: 70, margin: 0, height_mode: 'realTimeFollowSurface', collection_mode: 'oblique', gimbal_pitch: -45, route_id: route.id});
    log('terrain', tr.status, tr.data && tr.data.dataset, tr.data && tr.data.undulation, tr.data && tr.data.error);
    log('route deleted', (await api(page, 'DELETE', `routes/${route.id}`)).status);

    await page.goto(BASE + '/plugins/mission_planner/settings');
    await Promise.all([page.waitForNavigation(), page.click('#mp-key-remove')]);
    log('remove:', (await page.textContent('#mp-settings-done')).trim(), '| source:', (await page.textContent('#mp-key-source')).replace(/\s+/g, ' ').trim());

    const r2 = (await api(page, 'POST', 'routes', {name: 'MP settings check', route_type: 'area', model: 'm4t'})).data;
    const el2 = await api(page, 'POST', `routes/${r2.id}/elevation`, {lat: 42.1030, lon: -85.020728});
    log('no key:', el2.status, el2.data && el2.data.error);
    log('route deleted', (await api(page, 'DELETE', `routes/${r2.id}`)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.length);

    await page.goto(BASE + '/logout/');
    await login(page, 'mpcheck', 'mpcheck-throwaway-1');
    await page.goto(BASE + '/plugins/mission_planner/');
    log('non-admin sees Settings button', await page.isVisible('#mp-settings-link'));
    const res = await page.goto(BASE + '/plugins/mission_planner/settings');
    log('non-admin settings page', res.status());
    await page.screenshot({path: `${OUT}/s-${port}-nonadmin.png`});
  }
  log('page errors', JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.log(port, 'FAILED', String(e).split(KEY).join('[REDACTED]')); process.exit(1); });
