// Live check of the Pointer tool (Phase 13), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/measure_check.js <port> <out folder>
// With the lidar surface off (this browser only: no lidar is built), over the oblique AGL sample's place: an area route
// "Live check measure area" opens in Pointer; three dots in 2D, each label compared with the pointer tooltip there and
// the lines' differences with the labels; imperial; clearing by a dot and by choosing Polygon; three dots in 3D.
// A new waypoint route "Live check measure waypoints" opens in Pointer: a click adds a dot, not a point; Add points
// clears the dots and adds points. Nothing is saved; deletes its routes.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', out = process.argv[3];
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
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

const state = page => page.evaluate(() => ({
  dots: [...document.querySelectorAll('.mp-measure-dot .mp-measure-label')].map(e => e.textContent),
  diffs: [...document.querySelectorAll('.mp-measure-diff')].map(e => (e.hidden ? '(hidden)' : e.textContent)),
  active: [...document.querySelectorAll('[data-tool].active')].map(b => b.getAttribute('data-tool'))
}));
const meters = t => parseFloat(t);

// Hovers a spot of the map (fractions of its size), reads the tooltip, then clicks there
async function hoverAndClick(page, fx, fy) {
  const box = await page.locator('#mp-map').boundingBox();
  const x = box.x + box.width * fx, y = box.y + box.height * fy;
  await page.mouse.move(x - 15, y - 15);
  await page.mouse.move(x, y, {steps: 3});
  await page.waitForTimeout(1500);
  const tip = await page.evaluate(() => { const t = document.querySelector('.mp-pointer-height'); return t && !t.hidden ? t.textContent : '(hidden)'; });
  await page.mouse.click(x, y);
  await page.waitForTimeout(1500);
  return tip;
}

// Three dots: each label the tooltip's height there, each line's difference the labels' (within the rounding)
async function threeDots(page, where) {
  const tips = [];
  for (const [fx, fy] of [[0.35, 0.4], [0.55, 0.55], [0.7, 0.35]]) tips.push(await hoverAndClick(page, fx, fy));
  await page.waitForTimeout(1500);
  const s = await state(page);
  log('  ' + where + ': tooltips', tips, 'dots', s.dots, 'differences', s.diffs);
  expect(s.dots.length === 3 && s.dots.every(d => / m ASL$/.test(d)), where + ': three dots labelled in m ASL');
  // over the route's line the tooltip reads the route's nearest point, not the spot clicked: those are left out
  const off = tips.map((t, i) => [t, s.dots[i]]).filter(([t]) => t.indexOf('route') < 0);
  expect(off.length > 0 && off.every(([t, d]) => t === d), where + ': each dot off the route says what the tooltip said there (' + off.length + ')');
  expect(s.diffs.length === 2 && s.diffs.every((d, i) => /^[+-]\d+\.\d m$/.test(d) &&
         Math.abs(meters(d) - (meters(s.dots[i + 1]) - meters(s.dots[i]))) <= 0.11), where + ': the lines show the later dot minus the earlier');
  return s;
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
  await page.evaluate(() => localStorage.setItem('mission-planner:lidar', 'off'));
  const made = [];
  try {
    const d = 0.0015, polygon = [[LNG - d, LAT - d], [LNG + d, LAT - d], [LNG + d, LAT + d], [LNG - d, LAT + d]];
    const area = await api(page, 'POST', 'routes', {name: 'Live check measure area', route_type: 'area', model: 'm4t', settings: {polygon}});
    made.push(area.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + area.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    log('area editor');
    const tools = await page.evaluate(() => [...document.querySelectorAll('[data-tool]')].map(b => b.getAttribute('data-tool')));
    expect(tools.join() === 'pointer,polygon,rectangle,select,clear', 'Pointer first in the toolbar: ' + tools.join());
    expect((await state(page)).active.join() === 'pointer', 'a drawn route opens in Pointer');

    let s = await threeDots(page, '2D');
    expect(!(await page.evaluate(() => document.querySelector('#mp-save-button').disabled === false)), 'the dots leave the route unchanged (Save stays off)');
    await page.screenshot({path: path.join(out, 'measure-' + port + '-2d.png')});

    await page.click('[data-units="imperial"]');
    s = await state(page);
    log('  imperial', s.dots, s.diffs);
    expect(s.dots.every(t => / ft ASL$/.test(t)) && s.diffs.every(t => / ft$/.test(t)), 'imperial relabels the dots and lines');
    await page.click('[data-units="metric"]');

    await page.click('.mp-measure-dot >> nth=1', {position: {x: 6, y: 6}});
    await page.waitForTimeout(500);
    s = await state(page);
    expect(s.dots.length === 0 && s.diffs.length === 0, 'a click on a dot clears them all');

    await hoverAndClick(page, 0.4, 0.4);
    await hoverAndClick(page, 0.6, 0.6);
    await page.click('[data-tool="polygon"]');
    s = await state(page);
    expect(s.dots.length === 0 && s.active.join() === 'polygon', 'choosing Polygon clears the dots');
    await page.click('[data-tool="pointer"]');

    await layers(page, true);
    await page.waitForTimeout(5000);
    await threeDots(page, '3D');
    await page.screenshot({path: path.join(out, 'measure-' + port + '-3d.png')});
    await layers(page, false);

    log('waypoint editor');
    await page.evaluate(([lng, lat]) => localStorage.setItem('mission-planner:view', JSON.stringify({center: [lng, lat], zoom: 17})), [LNG, LAT]);
    const wp = await api(page, 'POST', 'routes', {name: 'Live check measure waypoints', route_type: 'waypoint', model: 'm4t'});
    made.push(wp.data.id);
    await page.goto(base + '/plugins/' + SLUG + '/route/' + wp.data.id);
    await page.waitForSelector('.mp-layers-button');
    await page.waitForTimeout(3000);
    const points = () => page.evaluate(() => document.querySelectorAll('.mp-wp-marker').length);
    const message = () => page.evaluate(() => document.querySelector('#mp-points-message').textContent);
    s = await state(page);
    expect(s.active.join() === 'pointer', 'a new waypoint route opens in Pointer');
    log('  message', await message());
    expect(/^Choose Add points and click the map/.test(await message()), 'the message says to choose Add points');
    await hoverAndClick(page, 0.4, 0.5);
    await hoverAndClick(page, 0.6, 0.5);
    s = await state(page);
    log('  dots', s.dots, s.diffs);
    expect(s.dots.length === 2 && (await points()) === 0, 'in Pointer a click puts a dot, not a point');
    await page.screenshot({path: path.join(out, 'measure-' + port + '-waypoint.png')});
    await page.click('[data-tool="add"]');
    s = await state(page);
    expect(s.dots.length === 0, 'choosing Add points clears the dots');
    await hoverAndClick(page, 0.4, 0.5);
    await hoverAndClick(page, 0.6, 0.5);
    expect((await points()) === 2, 'in Add points a click adds a point');
    log('  message', await message());
    await page.click('[data-tool="pointer"]');
    await hoverAndClick(page, 0.5, 0.7);
    expect((await points()) === 2 && (await state(page)).dots.length === 1, 'back in Pointer: a dot, the points kept');
  } catch (e) {
    log('ERROR', e.message);
    problems.push(e.message);
  } finally {
    await page.goto(base + '/plugins/' + SLUG + '/');
    for (const id of made.filter(Boolean)) log('delete', id, (await api(page, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(page, 'GET', 'routes')).data.map(r => r.id));
    log('console errors', errors);
    log(problems.length ? 'FAILED: ' + problems.join('; ') : 'all passed');
    await browser.close();
  }
})();
