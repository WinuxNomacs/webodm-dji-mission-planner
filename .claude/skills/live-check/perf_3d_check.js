// How long the 3D view takes to load and draw (Phase 21), headless, against a dev stack:
//   MP_ADMIN_USER=... MP_ADMIN_PASSWORD=... node .claude/skills/live-check/perf_3d_check.js <port> [runs] [lidar: off|on|both]
// Imports the Illinois sample (its lidar units must be built already: "on" over unbuilt units would start builds) and
// times, in the area editor: a cold first switch into 3D (a fresh browser, empty cache), the second switch (3D, 2D,
// 3D again), a reload with the browser's cache warm, and a pan in 3D. Each is timed from the click to the map's last
// "idle" (everything loaded and drawn, nothing more for 1.5 s), with the requests (count and bytes by host) and the
// main thread's long tasks. MP_PROFILE=1 also prints where the main thread spent its time,
// MP_TRACE=1 each request's start and end, MP_SHOTS=<folder> a screenshot after the first switch into 3D. Prints a table of medians over the runs. Deletes its route.
const path = require('path');
const fs = require('fs');
const repo = path.join(__dirname, '../../..');
const {chromium} = require(path.join(repo, 'node_modules/playwright'));
const port = process.argv[2] || '8009', RUNS = +(process.argv[3] || 3), which = process.argv[4] || 'both';
const base = 'http://localhost:' + port, SLUG = 'mission_planner';
const KMZ = path.join(repo, 'mission_planner/tests/fixtures/dji-kmz/m4t-testkmz-oblique-AGL.kmz');
const QUIET_MS = 1500, DEADLINE_MS = 60000;
const log = (...a) => console.log(...a);
const trace = {t0: 0};          // MP_TRACE=1: each request's start and end, from the action's start

// Before the page's scripts: the map made reachable (window.__mpMap), its idle and render times recorded, long tasks summed
const INIT = () => {
  let ml;
  Object.defineProperty(window, 'maplibregl', {configurable: true, get: () => ml, set: v => {
    const o = Object.assign({}, v);
    window.__mpLoads = [];            // each protocol load: [url, start, end] (MP_TRACE)
    o.addProtocol = (name, fn) => v.addProtocol(name, (params, ac) => {
      const rec = [params.url.replace(/\?.*/, ''), performance.now(), null];
      window.__mpLoads.push(rec);
      return fn(params, ac).then(r => { rec[2] = performance.now(); return r; });
    });
    o.Map = class extends v.Map {
      constructor(a) {
        super(a);
        window.__mpMap = this;
        window.__mpIdle = [];
        window.__mpData = 0;
        window.__mpFrames = [];
        this.on('idle', () => window.__mpIdle.push(performance.now()));
        this.on('render', () => window.__mpFrames.push(performance.now()));
        window.__mpTiles = [];          // each elevation tile ready: [key, time] (MP_TRACE)
        this.on('sourcedata', e => { if (e.sourceId === 'mp-dem' && e.tile) window.__mpTiles.push([e.tile.tileID.canonical.z + '/' + e.tile.tileID.canonical.x + '/' + e.tile.tileID.canonical.y, performance.now(), e.tile.state]); });
        this.on('sourcedataloading', () => { window.__mpData = performance.now(); });
        this.on('data', () => { window.__mpData = performance.now(); });
      }
    };
    ml = o;
  }});
  window.__mpLong = 0;
  try { new PerformanceObserver(l => l.getEntries().forEach(e => { window.__mpLong += e.duration; })).observe({type: 'longtask', buffered: true}); } catch (e) { /* none */ }
};

function host(url) {
  if (url.includes('elevation-tiles-prod')) return 'aws';
  if (url.includes('/lidar/tiles/')) return 'lidar';
  if (url.startsWith(base)) return 'app';
  return 'basemap';
}

function watchRequests(page) {
  const seen = [];
  if (process.env.MP_TRACE) page.on('request', req => { req.__t = Date.now(); });
  page.on('requestfinished', async req => {
    if (process.env.MP_TRACE) log('    ' + String(req.__t - trace.t0).padStart(6) + ' -> ' + String(Date.now() - trace.t0).padStart(6) + ' ms  ' + host(req.url()) + '  ' + req.url().replace(/^https?:\/\/[^/]+/, '').slice(0, 70));
    let bytes = 0;
    try { bytes = (await req.sizes()).responseBodySize; } catch (e) { /* gone */ }
    const resp = await req.response().catch(() => null);
    seen.push({host: host(req.url()), bytes: Math.max(bytes, 0), cached: bytes <= 0 || (resp && resp.status() === 304)});
  });
  return {mark: () => seen.length, since: from => seen.slice(from)};
}

// The time from t0 (performance.now in the page) to the map's last idle, once QUIET_MS pass with no idle or data after it
async function untilDrawn(page, t0) {
  const start = Date.now();
  while (Date.now() - start < DEADLINE_MS) {
    await page.waitForTimeout(250);
    const s = await page.evaluate(() => ({idle: window.__mpIdle[window.__mpIdle.length - 1] || 0, data: window.__mpData, now: performance.now(),
                                          moving: window.__mpMap.isMoving(), loaded: window.__mpMap.loaded()}));
    if (s.idle > t0 && s.idle >= s.data && !s.moving && s.loaded && s.now - s.idle > QUIET_MS) return s.idle - t0;
  }
  return null;
}

// The layers panel's 2D or 3D, clicked inside the page in one go (Playwright's clicks wait for the panel to settle,
// which the timing would count)
async function layers(page, view3d) {
  const ok = await page.evaluate(label => {
    const b = [...document.querySelectorAll('.mp-layers-view')].find(e => e.textContent.trim().indexOf(label) >= 0);
    if (b) b.click();
    return !!b;
  }, view3d ? '3D' : '2D');
  if (!ok) throw new Error('no ' + (view3d ? '3D' : '2D') + ' in the layers panel');
}

// The functions the main thread spent the most time in (self time), from a CDP profile (MP_PROFILE=1)
function profileTop(what, profile) {
  const byId = {}, self = {};
  profile.nodes.forEach(n => { byId[n.id] = n; });
  profile.samples.forEach((id, i) => {
    const f = byId[id].callFrame, key = (f.functionName || '(anonymous)') + ' ' + (f.url.split('/').pop() || f.url) + ':' + (f.lineNumber + 1);
    self[key] = (self[key] || 0) + (profile.timeDeltas[i] || 0) / 1000;
  });
  log('  profile of ' + what + ':');
  Object.entries(self).sort((a, b) => b[1] - a[1]).slice(0, 15).forEach(([k, ms]) => log('    ' + String(Math.round(ms)).padStart(6) + ' ms  ' + k));
}

async function timed(page, reqs, what, act) {
  const from = reqs.mark();
  const long0 = await page.evaluate(() => window.__mpLong);
  trace.t0 = Date.now();
  if (process.env.MP_TRACE) log('  ' + what + ':');
  const t0 = await page.evaluate(() => performance.now());
  const cdp = process.env.MP_PROFILE ? await page.context().newCDPSession(page) : null;
  if (cdp) { await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', {interval: 1000}); await cdp.send('Profiler.start'); }
  await act();
  const ms = await untilDrawn(page, t0);
  const frames = await page.evaluate(t0 => {
    const f = window.__mpFrames.filter(t => t > t0), gaps = f.slice(1).map((t, i) => t - f[i]).sort((a, b) => a - b);
    return {n: f.length, median: gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0, last: f.length ? f[f.length - 1] - t0 : 0};
  }, t0);
  if (process.env.MP_TRACE) {
    const t = await page.evaluate(t0 => ({loads: window.__mpLoads.filter(l => l[1] > t0).map(l => [l[0], Math.round(l[1] - t0), l[2] === null ? null : Math.round(l[2] - t0)]),
                                          tiles: window.__mpTiles.filter(x => x[1] > t0).map(x => [x[0], Math.round(x[1] - t0), x[2]])}), t0);
    t.loads.forEach(l => log('    load  ' + String(l[1]).padStart(6) + ' -> ' + String(l[2]).padStart(6) + '  ' + l[0]));
    t.tiles.forEach(x => log('    ready ' + String(x[1]).padStart(6) + '  ' + x[0] + ' ' + x[2]));
  }
  if (cdp) { profileTop(what, (await cdp.send('Profiler.stop')).profile); await cdp.detach(); }
  await page.waitForTimeout(300);
  const r = reqs.since(from);
  const by = {};
  r.forEach(x => { const b = by[x.host] = by[x.host] || {n: 0, kb: 0, cached: 0}; b.n++; b.kb += x.bytes / 1024; if (x.cached) b.cached++; });
  const long = (await page.evaluate(() => window.__mpLong)) - long0;
  return {what, ms, by, long, frames};
}

async function login(context) {
  const page = await context.newPage();
  await page.goto(base + '/login/');
  await page.fill('input[name=username]', process.env.MP_ADMIN_USER);
  await page.fill('input[name=password]', process.env.MP_ADMIN_PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], input[type=submit]')]);
  return page;
}

async function api(page, method, p, body) {
  return page.evaluate(async ([method, p, body, SLUG]) => {
    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
    const res = await fetch('/api/plugins/' + SLUG + '/' + p, {method, headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: body ? JSON.stringify(body) : undefined});
    let data = null; try { data = await res.json(); } catch (e) {}
    return {status: res.status, data};
  }, [method, p, body, SLUG]);
}

async function oneRun(browser, id, lidar) {
  const context = await browser.newContext({viewport: {width: 1400, height: 900}});
  await context.addInitScript(INIT);
  const page = await login(context);
  await page.evaluate(v => localStorage.setItem('mission-planner:lidar', v), lidar);
  const reqs = watchRequests(page);
  const open = async () => {
    await page.goto(base + '/plugins/' + SLUG + '/route/' + id);
    await page.waitForSelector('.mp-layers-button');
    await untilDrawn(page, 0);          // the 2D map drawn first
  };
  const out = [];
  await open();
  out.push(await timed(page, reqs, 'first 3D (cold)', () => layers(page, true)));
  if (process.env.MP_SHOTS) await page.screenshot({path: path.join(process.env.MP_SHOTS, 'perf-3d-lidar-' + lidar + '.png')});
  await layers(page, false);
  await untilDrawn(page, await page.evaluate(() => performance.now()));
  out.push(await timed(page, reqs, 'second 3D', () => layers(page, true)));
  out.push(await timed(page, reqs, 'pan in 3D', () => page.evaluate(() => window.__mpMap.panBy([400, 0], {duration: 0}))));
  await open();
  out.push(await timed(page, reqs, '3D after reload', () => layers(page, true)));
  await context.close();
  return out;
}

const median = a => { const s = a.filter(x => x !== null).sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : null; };

(async () => {
  // MP_CANVAS=gpu keeps the 2D canvas on SwiftShader's emulated GPU, where reading its pixels back takes seconds a tile
  // (measured 2026-11-20): not what a browser with a GPU does, so the default draws 2D canvases in software
  const args = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'].concat(process.env.MP_CANVAS === 'gpu' ? [] : ['--disable-accelerated-2d-canvas']);
  const browser = await chromium.launch({headless: true, args});
  const admin = await login(await browser.newContext());
  log('routes before', (await api(admin, 'GET', 'routes')).data.map(r => r.id));
  let id = null;
  try {
    const up = await admin.evaluate(async ([b64, SLUG]) => {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1];
      const form = new FormData();
      form.append('file', new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))]), 'Live check perf.kmz');
      const res = await fetch('/api/plugins/' + SLUG + '/routes/import', {method: 'POST', headers: {'X-CSRFToken': csrf}, body: form});
      return {status: res.status, data: await res.json()};
    }, [fs.readFileSync(KMZ).toString('base64'), SLUG]);
    id = up.data && (up.data.id || (up.data.route && up.data.route.id));
    log('import', up.status, 'id', id);
    for (const lidar of which === 'both' ? ['off', 'on'] : [which]) {
      const all = [];
      for (let i = 0; i < RUNS; i++) all.push(await oneRun(browser, id, lidar));
      log('\nlidar ' + lidar + ' (' + RUNS + ' runs; medians; ms to drawn, long tasks ms, requests n/KB by host, how many from the cache)');
      all[0].forEach((row, k) => {
        const rows = all.map(r => r[k]);
        const hosts = {};
        rows.forEach(r => Object.keys(r.by).forEach(h => { hosts[h] = 1; }));
        const req = Object.keys(hosts).sort().map(h => h + ' ' + median(rows.map(r => (r.by[h] || {n: 0}).n)) + '/' +
                                                      Math.round(median(rows.map(r => (r.by[h] || {kb: 0}).kb))) + ' (' + median(rows.map(r => (r.by[h] || {cached: 0}).cached)) + ' cached)').join(', ');
        log('  ' + row.what.padEnd(18) + String(median(rows.map(r => r.ms === null ? null : Math.round(r.ms)))).padStart(6) + ' ms  [' +
            rows.map(r => r.ms === null ? 'timeout' : Math.round(r.ms)).join(', ') + ']  long ' + Math.round(median(rows.map(r => r.long))) + '  frames ' + median(rows.map(r => r.frames.n)) + ' (' +
            Math.round(median(rows.map(r => r.frames.median))) + ' ms apart)  ' + req);
      });
    }
  } catch (e) {
    log('ERROR', e.message);
  } finally {
    if (id) log('delete', id, (await api(admin, 'DELETE', 'routes/' + id)).status);
    log('routes after', (await api(admin, 'GET', 'routes')).data.map(r => r.id));
    await browser.close();
  }
})();
