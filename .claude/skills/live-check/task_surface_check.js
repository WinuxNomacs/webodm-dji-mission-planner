// Live check of a WebODM task in the editors' map (Phase 23), headless:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node task_surface_check.js <port> <out folder> <route id> <task name> [brave]
// Opens the route, picks the task in Map layers (its DSM is cut), screenshots its orthophoto in 2D, both in 3D, the DSM
// alone and the lidar again, reads the pointer's heights, reloads (the choice remembered per route) and the collision
// line. "brave" adds Brave's canvas noise (one step in some pixels' red). A fresh browser profile: nothing is kept.
// Afterwards remove the tiles it cut: mission_planner_data/tasks/<task id> in the plugin media.
const path = require('path');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2], out = process.argv[3], routeId = process.argv[4], taskName = process.argv[5];
const brave = process.argv[6] === 'brave';
const base = 'http://localhost:' + port;
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const context = await browser.newContext({viewport: {width: 1400, height: 900}});
  if (brave) await context.addInitScript(() => {
    for (const C of [self.OffscreenCanvasRenderingContext2D, self.CanvasRenderingContext2D]) {
      if (!C) continue;
      const g = C.prototype.getImageData;
      C.prototype.getImageData = function (...a) { const d = g.apply(this, a); for (let i = 0; i < d.data.length; i += 997) d.data[i] = Math.min(255, d.data[i] + 1); return d; };
    }
  });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('request', r => { const u = r.url(); if (u.includes('task-surface') || u.includes('orthophoto/tiles')) requests.push(u.replace(base, '').replace(/\/tiles\/\d+\/\d+\/\d+\.png.*/, '/tiles/...')); });
  const log = (...a) => console.log(...a);
  try {
    await page.goto(base + '/login/');
    await page.fill('input[name=username]', process.env.MP_ADMIN_USER); await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
    await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
    await page.goto(base + '/plugins/mission_planner/route/' + routeId);
    await page.waitForTimeout(4000);
    await page.click('.mp-layers-button');
    const options = await page.$$eval('.mp-layers-task option', os => os.map(o => o.textContent));
    log('tasks listed:', JSON.stringify(options));
    const id = await page.$$eval('.mp-layers-task option', (os, name) => (os.find(o => o.textContent.startsWith(name)) || {}).value, taskName);
    await page.selectOption('.mp-layers-task', id);
    await page.waitForTimeout(3000);
    const note = () => page.$eval('.mp-layers-task-note', e => e.textContent);
    log('note:', await note());
    log('checkboxes:', JSON.stringify(await page.$$eval('.mp-layers-task-dsm input, .mp-layers-task-ortho input', es => es.map(e => [e.checked, e.disabled]))));
    await page.click('.mp-layers-button');
    await page.waitForTimeout(3000);
    await page.screenshot({path: out + '/2d-ortho.png'});
    // the height under the pointer at the map's middle (the task)
    const box = await page.$eval('.maplibregl-canvas', c => { const r = c.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; });
    await page.mouse.move(box[0], box[1]); await page.waitForTimeout(1500);
    log('pointer 2D:', await page.$eval('.mp-pointer-height', e => e.textContent + ' [' + e.getAttribute('data-source') + ']').catch(() => 'none'));
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-view:has-text("3D")');
    await page.click('.mp-layers-button');
    await page.waitForTimeout(12000);
    await page.screenshot({path: out + '/3d-both.png'});
    await page.mouse.move(box[0], box[1] + 40); await page.waitForTimeout(1500);
    log('pointer 3D:', await page.$eval('.mp-pointer-height', e => e.textContent + ' [' + e.getAttribute('data-source') + ']').catch(() => 'none'));
    // the orthophoto off: the DSM alone, with the basemap
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-task-ortho input');
    await page.click('.mp-layers-button');
    await page.waitForTimeout(6000);
    await page.screenshot({path: out + '/3d-dsm-only.png'});
    // the DSM off too: the lidar again
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-task-dsm input');
    await page.click('.mp-layers-button');
    await page.waitForTimeout(6000);
    await page.screenshot({path: out + '/3d-lidar.png'});
    // DSM back on, then a reload: remembered
    await page.click('.mp-layers-button');
    await page.click('.mp-layers-task-dsm input');
    await page.click('.mp-layers-button');
    await page.waitForTimeout(2000);
    await page.reload(); await page.waitForTimeout(5000);
    await page.click('.mp-layers-button');
    log('after reload:', await page.$eval('.mp-layers-task', s => s.options[s.selectedIndex].textContent),
        JSON.stringify(await page.$$eval('.mp-layers-task-dsm input, .mp-layers-task-ortho input', es => es.map(e => e.checked))), await note());
    log('route status:', await page.$eval('#mp-collision-status, .mp-collisions, [id*=collision]', e => e.textContent.trim()).catch(() => 'n/a'));
  } finally {
    log('requests:', JSON.stringify([...new Set(requests)]));
    log('errors:', JSON.stringify(errors));
    await browser.close();
  }
})();
