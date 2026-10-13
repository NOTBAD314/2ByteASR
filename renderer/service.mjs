import readline from 'node:readline';
import process from 'node:process';
import path from 'node:path';
import fs from 'node:fs/promises';
import {AsyncLocalStorage} from 'node:async_hooks';
import {fileURLToPath} from 'node:url';
import {localBrowserExecutable} from './export-browser.mjs';
import {installBundleBoundary, installPageBoundary, protectLiveHtml} from './resource-boundary.mjs';
import {
  makeCancelSignal,
  openBrowser,
  renderStill,
  selectComposition,
} from '@remotion/renderer';

const PROTOCOL_VERSION = 1;
const RENDERER_JOB_KINDS = new Set(['production', 'diagnostic', 'thumbnail', 'card_preview']);
const rendererRoot = path.dirname(fileURLToPath(import.meta.url));
const entryPoint = path.join(rendererRoot, 'src', 'index.ts');
const configuredChrome = process.env.TWOBYTEASR_RENDERER_CHROME ||
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

// Fonts live canonically in assets/fonts/ (public PR #2 by CODE-A-DUCK). Fill public/fonts/
// only where a font is missing or differs in size: an installed or signed app already ships
// them and must not be rewritten at every start.
const assetsRoot = path.resolve(rendererRoot, '..', 'assets', 'fonts');
const publicFonts = path.join(rendererRoot, 'public', 'fonts');
const BUNDLED_FONTS = [
  'Cubic11.ttf', 'SmileySans-Oblique.woff2',
  'SourceHanSansSC-Heavy.otf', 'SourceHanSansSC-Medium.otf',
  'SourceHanSansSC-Medium.woff2', 'ZCOOLKuaiLe-Regular.ttf',
  'ZCOOLQingKeHuangYou-Regular.ttf',
];
await fs.mkdir(publicFonts, {recursive: true}).catch(() => {});
await Promise.all(BUNDLED_FONTS.map(async (name) => {
  const source = path.join(assetsRoot, name);
  const target = path.join(publicFonts, name);
  try {
    const [wanted, present] = await Promise.all([fs.stat(source), fs.stat(target).catch(() => null)]);
    if (!present || present.size !== wanted.size) await fs.copyFile(source, target);
  } catch {
    // Missing source or a read-only install: the renderer keeps whatever fonts it ships with.
  }
}));

let serveUrl = null;
let browser = null;
let rendererGeneration = 0;
let queueSequence = 0;
let active = null;
let pumping = false;
let idleTimer = null;
const queue = [];
const telemetry = [];
const compositionCache = new Map();
// --- Live web preview (round 19) -------------------------------------
// One persistent page rendering the ACTIVE web-theme cue at the current
// playhead. Python pumps `live_frame` (~20Hz); each call scrubs every CSS
// animation to (cue_ms, stage_ms) deterministically, then screenshots.
// Each preview owns a page, while browser/process/font resources stay shared.
// AsyncLocalStorage preserves that ownership across concurrent CDP awaits.
const liveContext = new AsyncLocalStorage();
const liveSessions = new Map();
const createLiveState = () => ({page: null, generation: 0,
  viewport: {width: 1280, height: 720}, sequence: 0, frameSeq: 0,
  latest: null, attached: false, streaming: false, tail: Promise.resolve(),
  control: 0, captureEpochMs: 0, everyNthFrame: 0, cdpLastMs: 0, cdpIntervalMs: 0, cdpAckMs: 0});
const defaultLiveState = createLiveState();
const liveState = () => liveContext.getStore() || defaultLiveState;
let liveSetSequence = 0;
let browserStarting = null;
let bundleStarting = null;

// 二十轮：live 预览（用户正看着视频层）抢占 still 预热——取消活动渲染、
// 丢弃排队 warmers（发 STALE 让 Python 侧不悬挂）。预热只是缓存加速，
// 随时可重跑；live 卡 90 秒不可接受。
const preemptRendersForLive = () => {
  for (const entry of queue.splice(0, queue.length)) {
    record('stale_drop', {request_id: entry.request.request_id, phase: 'live_preempt'});
    send({type: 'result', request_id: entry.request.request_id, status: 'STALE', error: 'live preview preemption'});
  }
  if (active && !active.superseded) {
    active.superseded = true;
    try { active.cancel(); } catch { /* already gone */ }
    record('live_preempt', {request_id: active.request.request_id});
  }
};

const attachLiveScreencast = (client) => {
  if (liveState().attached) return;
  liveState().attached = true;
  const state = liveState();
  client.on('Page.screencastFrame', (event) => liveContext.run(state, async () => {
    const started = performance.now();
    state.cdpIntervalMs = state.cdpLastMs ? started-state.cdpLastMs : 0;
    state.cdpLastMs = started;
    liveState().frameSeq += 1;
    const captured = Number(event.metadata?.timestamp || 0) * 1000;
    if (!captured || captured >= state.captureEpochMs) {
      state.lastFrameAt = started;
      state.latest = {seq: state.frameSeq, data: event.data, ts: now(), captured_ms: captured, source: 'screencast'};
    }
    try {
      await client.send('Page.screencastFrameAck', {sessionId: event.sessionId});
      state.cdpAckMs = performance.now()-started;
    } catch {
      // Session rotated — the next live_set reattaches.
    }
  }));
};

const ensureLiveScreencast = async (everyNthFrame) => {
  const nth = Math.max(1, Number(everyNthFrame) || 1);
  if (liveState().streaming && liveState().everyNthFrame === nth) return;
  const client = liveState().page._client();
  if (liveState().streaming) await client.send('Page.stopScreencast');
  await client.send('Page.startScreencast', {
    format: 'png',
    everyNthFrame: nth,
    maxWidth: liveState().viewport.width,
    maxHeight: liveState().viewport.height,
  });
  liveState().streaming = true;
  liveState().everyNthFrame = nth;
};

// Mirror remotion's own screenshotTask param shape exactly — this headless
// shell rejects Page.captureScreenshot without an explicit clip.
const captureLivePng = async () => {
  const client = liveState().page._client();
  const viewport = liveState().viewport;
  // The private page is activated by scrub/play, and live_set pins its
  // transparent background. Reapplying emulation here invalidates the surface
  // immediately before every capture.
  const {value} = await client.send('Page.captureScreenshot', {
    format: 'png',
    quality: undefined,
    clip: {x: 0, y: 0, width: viewport.width, height: viewport.height, scale: 1},
    captureBeyondViewport: false,
    optimizeForSpeed: true,
    fromSurface: true,
  });
  return value.data;
};

const now = () => Date.now();
const elapsed = (started) => Math.round((performance.now() - started) * 1000) / 1000;
const idleTimeoutMs = Math.max(30_000, Number(process.env.TWOBYTEASR_RENDERER_IDLE_MS || 300_000));

const record = (event, fields = {}) => {
  const item = {event, ts: now(), ...fields};
  telemetry.push(item);
  if (telemetry.length > 400) telemetry.splice(0, telemetry.length - 400);
  return item;
};

const send = (payload) => {
  process.stdout.write(`${JSON.stringify({version: PROTOCOL_VERSION, ...payload})}\n`);
};

const closeBrowser = async (reason) => {
  const current = browser;
  browser = null;
  for (const state of [defaultLiveState, ...liveSessions.values()]) {
    state.page = null; state.latest = null; state.attached = false; state.streaming = false;
  }
  liveState().page = null;
  liveState().latest = null;
  liveState().attached = false;  // the old client's listeners died with it
  if (!current) return;
  try {
    await current.close({silent: true});
  } catch {
    // A crashed browser is already closed from the service's perspective.
  }
  record('browser_stop', {reason});
};

const clearIdleTimer = () => {
  if (idleTimer) clearTimeout(idleTimer);
  idleTimer = null;
};

// 二十四轮：live 页流量也必须续期 idle 定时器——此前只有 render/warm/
// live_frame 触碰它，纯 live 会话 300s 后 closeBrowser+process.exit(0)，
// 播放中的条带录制/种子帧全灭（用户实测"连续播放一段时间后完全静止帧"）。
// live_latest 是 10-15ms 高频轮询，不在这里续期（set/play/pause 足够密集）。
const touchLiveIdle = () => {
  clearIdleTimer();
  armIdleShutdown();
};

const armIdleShutdown = () => {
  clearIdleTimer();
  idleTimer = setTimeout(async () => {
    if (active || queue.length) return armIdleShutdown();
    record('idle_shutdown', {idle_ms: idleTimeoutMs});
    await closeBrowser('idle_timeout');
    process.exit(0);
  }, idleTimeoutMs);
  idleTimer.unref();
};

const ensureBrowser = async () => {
  if (browser) return [];
  if (browserStarting) return browserStarting;
  browserStarting = (async () => {
    const started = performance.now();
    const browserExecutable = await localBrowserExecutable(rendererRoot, configuredChrome);
    browser = await openBrowser('chrome', {browserExecutable,
      chromiumOptions: {headless: true}, logLevel: 'error'});
    if (serveUrl) await installBundleBoundary(browser, serveUrl, event => record('resource_blocked',event));
    rendererGeneration += 1;
    return [record('browser_start', {duration_ms: elapsed(started), renderer_generation: rendererGeneration, executable:browserExecutable})];
  })();
  try { return await browserStarting; } finally { browserStarting = null; }
};

const ensureWarm = async () => {
  const events = await ensureBrowser();
  if (!serveUrl) {
    if (!bundleStarting) bundleStarting = (async () => {
      const started = performance.now();
      const {bundle} = await import('@remotion/bundler');
      serveUrl = await bundle({entryPoint, enableCaching: true, onProgress: () => undefined});
      await installBundleBoundary(browser, serveUrl, event => record('resource_blocked',event));
      return record('bundle_ready', {duration_ms: elapsed(started)});
    })();
    try { events.push(await bundleStarting); } finally { bundleStarting = null; }
  }
  return events;
};

const expired = (request) =>
  Number.isFinite(request.deadline_epoch_ms) && now() >= request.deadline_epoch_ms;
const isCancelledError = (error) =>
  /cancelled|canceled/i.test(String(error?.message || error));

const renderJob = async (request, job, cancelSignal, index) => {
  if (expired(request)) throw new Error('renderer deadline exceeded');
  const output = path.resolve(String(job.output));
  const partial = `${output}.partial-${request.request_id}-${index}.png`;
  await fs.mkdir(path.dirname(output), {recursive: true});
  const inputProps = job.input_props || {};
  const compositionId = String(job.composition_id || 'SubtitleOverlay');
  const compositionKey = JSON.stringify([
    compositionId,
    inputProps.width,
    inputProps.height,
    inputProps.fps,
    inputProps.durationInFrames,
  ]);
  let composition = compositionCache.get(compositionKey);
  if (!composition) {
    composition = await selectComposition({
      serveUrl,
      id: compositionId,
      inputProps,
      puppeteerInstance: browser,
      logLevel: 'error',
    });
    compositionCache.set(compositionKey, composition);
    record('composition_ready', {composition_key: compositionKey});
  }
  // Remotion renders the component from composition.props, not directly from
  // inputProps. Our calculateMetadata only derives structural video metadata,
  // so reuse that metadata while keeping every job's visual props distinct.
  const renderComposition = {...composition, props: inputProps};
  try {
    await renderStill({
      serveUrl,
      composition: renderComposition,
      inputProps,
      frame: Math.max(0, Number(job.frame || 0)),
      output: partial,
      imageFormat: 'png',
      overwrite: true,
      puppeteerInstance: browser,
      cancelSignal,
      logLevel: 'error',
    });
    await fs.rename(partial, output);
  } finally {
    await fs.rm(partial, {force: true}).catch(() => undefined);
  }
  return {
    output,
    frame: Math.max(0, Number(job.frame || 0)),
    job_id: String(job.job_id || ''),
    job_kind: String(job.job_kind || 'production'),
    cue_id: String(job.cue_id || ''),
    project_id: String(job.project_id || ''),
    appearance_generation: Math.max(0, Number(job.appearance_generation || 0)),
    snapshot_hash: String(job.snapshot_hash || ''),
    graph_hash: String(job.graph_hash || ''),
    requested_at: Number(job.requested_at || 0),
  };
};

const execute = async (entry) => {
  const {request} = entry;
  const requestStarted = performance.now();
  const events = [record('queue_wait', {
    request_id: request.request_id,
    queue_ms: Math.max(0, now() - entry.queuedAt),
  })];
  const cancellation = makeCancelSignal();
  active = {...entry, cancel: cancellation.cancel, superseded: false};
  let restarted = false;
  try {
    events.push(...await ensureWarm());
    const results = [];
    const renderStarted = performance.now();
    events.push(record('render_start', {
      request_id: request.request_id,
      render_type: request.render_type,
      batch_size: request.jobs.length,
    }));
    for (let index = 0; index < request.jobs.length; index += 1) {
      if (active?.superseded) throw new Error('renderer request superseded');
      try {
        results.push(await renderJob(request, request.jobs[index], cancellation.cancelSignal, index));
      } catch (error) {
        if (active?.superseded || isCancelledError(error)) throw error;
        if (restarted) throw error;
        restarted = true;
        events.push(record('restart', {request_id: request.request_id, reason: 'browser_render_failure'}));
        await closeBrowser('render_failure');
        events.push(...await ensureWarm());
        results.push(await renderJob(request, request.jobs[index], cancellation.cancelSignal, index));
      }
    }
    events.push(record('render_complete', {
      request_id: request.request_id,
      render_ms: elapsed(renderStarted),
      memory: process.memoryUsage().rss,
    }));
    events.push(record('publish', {request_id: request.request_id, count: results.length}));
    send({
      type: 'result',
      request_id: request.request_id,
      generation: request.generation,
      status: 'OK',
      renderer_generation: rendererGeneration,
      queue_ms: Math.max(0, now() - entry.queuedAt),
      render_ms: elapsed(renderStarted),
      total_ms: elapsed(requestStarted),
      results,
      telemetry: events,
    });
  } catch (error) {
    const stale = Boolean(active?.superseded);
    events.push(record(stale ? 'stale_drop' : 'render_error', {
      request_id: request.request_id,
      error: String(error?.message || error),
    }));
    send({
      type: 'result',
      request_id: request.request_id,
      generation: request.generation,
      status: stale ? 'STALE' : (isCancelledError(error) ? 'CANCELLED' : 'ERROR'),
      renderer_generation: rendererGeneration,
      total_ms: elapsed(requestStarted),
      error: String(error?.message || error),
      telemetry: events,
    });
  } finally {
    active = null;
  }
};

const pump = async () => {
  if (pumping) return;
  pumping = true;
  try {
    while (queue.length) {
      queue.sort((a, b) => b.request.priority - a.request.priority || a.sequence - b.sequence);
      const entry = queue.shift();
      if (expired(entry.request)) {
        send({type: 'result', request_id: entry.request.request_id, status: 'ERROR', error: 'renderer deadline exceeded'});
        continue;
      }
      await execute(entry);
    }
  } finally {
    pumping = false;
    armIdleShutdown();
  }
};

const validateRenderRequest = (request) => {
  if (request.version !== PROTOCOL_VERSION) throw new Error('unsupported renderer protocol version');
  if (!request.request_id || !Array.isArray(request.jobs) || !request.jobs.length) {
    throw new Error('invalid renderer request');
  }
  request.priority = Number(request.priority || 0);
  request.generation = Number(request.generation || 0);
  request.batch_group = String(request.batch_group || request.snapshot_identity || request.request_id);
  for (const job of request.jobs) {
    if (
      !job.job_id ||
      !RENDERER_JOB_KINDS.has(String(job.job_kind || '')) ||
      !Number.isFinite(Number(job.requested_at))
    ) {
      throw new Error('renderer job identity is incomplete');
    }
  }
  return request;
};

const productionScopes = (request) => new Set(
  request.jobs
    .filter((job) => String(job.job_kind || '') === 'production')
    .map((job) => [
      String(job.project_id || ''),
      String(job.cue_id || ''),
      String(job.appearance_generation || 0),
    ].join(':'))
    .filter((scope) => !scope.startsWith('::')),
);

const sharesProductionScope = (left, right) => {
  const leftScopes = productionScopes(left);
  if (!leftScopes.size) return false;
  return [...productionScopes(right)].some((scope) => leftScopes.has(scope));
};

const enqueue = (raw) => {
  clearIdleTimer();
  const request = validateRenderRequest(raw);
  for (let index = queue.length - 1; index >= 0; index -= 1) {
    if (
      queue[index].request.batch_group === request.batch_group ||
      sharesProductionScope(queue[index].request, request)
    ) {
      const stale = queue.splice(index, 1)[0];
      record('stale_drop', {request_id: stale.request.request_id, replaced_by: request.request_id});
      send({type: 'result', request_id: stale.request.request_id, status: 'STALE', error: 'superseded before render'});
    }
  }
  if (
    active?.request.batch_group === request.batch_group ||
    (active && sharesProductionScope(active.request, request))
  ) {
    active.superseded = true;
    active.cancel();
    record('cancel', {request_id: active.request.request_id, replaced_by: request.request_id});
  }
  queue.push({request, sequence: ++queueSequence, queuedAt: now()});
  void pump();
};

const ensureLivePage = async (width, height) => {
  await ensureBrowser();
  if (!liveState().page) {
    // Each LIVE consumer needs its own headless window. Tabs in one window
    // stop producing compositor frames when another consumer seeks/activates.
    // Keep the browser process shared, but give pages independent visibility.
    const {value:{targetId}} = await browser.connection.send('Target.createTarget', {
      url:'about:blank',newWindow:true,background:false,
    });
    const target = await browser.waitForTarget(t => t._targetId === targetId);
    liveState().page = await target.page({sourceMapGetter:undefined,logLevel:'error',indent:false,pageIndex:0});
    liveState().page.setDefaultTimeout(8000);
    const state = liveState();
    state.scriptErrors = [];
    state.page._client().on('Runtime.exceptionThrown', event => {
      state.scriptErrors.push(String(event.exceptionDetails?.exception?.description || event.exceptionDetails?.text));
      state.scriptErrors = state.scriptErrors.slice(-20);
    });
    liveState().viewport = {width: 1280, height: 720};
    liveState().generation += 1;
    record('live_page_open', {renderer_generation: rendererGeneration, live_generation: liveState().generation});
  }
  liveState().viewport = {
    width: Math.max(1, Number(width) || 1280),
    height: Math.max(1, Number(height) || 720),
  };
  await liveState().page.setViewport({width: liveState().viewport.width, height: liveState().viewport.height, deviceScaleFactor: 1});
  return liveState().page;
};

const handleLiveSet = async (message) => {
  const started = performance.now();
  touchLiveIdle();
  // LIVE has its own pages and does not cancel unrelated export/card jobs.
  const page = await ensureLivePage(Number(message.width || 1280), Number(message.height || 720));
  liveState().scriptErrors = [];
  liveState().playing = false;
  // The wrapped page has no setContent — park the HTML in a temp file and
  // navigate to it (file:// keeps CJK + big CSS out of URL encoding limits).
  const os = await import('node:os');
  const pathMod = await import('node:path');
  const urlMod = await import('node:url');
  const fsSync = await import('node:fs');
  const liveDir = pathMod.join(os.tmpdir(), '2ByteASR-live-preview');
  fsSync.mkdirSync(liveDir, {recursive: true});
  const htmlPath = pathMod.join(liveDir, `live-${++liveSetSequence}.html`);
  fsSync.writeFileSync(htmlPath, protectLiveHtml(message.html || ''), 'utf-8');
  try {
    if (liveState().streaming) await page._client().send('Page.stopScreencast');
    liveState().streaming = false;
    liveState().everyNthFrame = 0;
    const documentUrl = urlMod.pathToFileURL(htmlPath).href;
    await installPageBoundary(page, {documentUrl}, event => record('resource_blocked',event));
    await page.goto({url: documentUrl, timeout: 15000});
  } finally { fsSync.rmSync(htmlPath, {force: true}); }
  // 二十一轮：持久透明背景——screencast 推帧与截图共用；不设则推帧是
  // 页面默认白底，整个视频被白背景盖住（暂停种子帧透明→播放全白=闪烁）。
  await page._client().send('Emulation.setDefaultBackgroundColorOverride', {
    color: {r: 0, g: 0, b: 0, a: 0},
  });
  // Fonts must resolve before the first frame or pixel-font spans render in
  // the fallback face and get baked into screenshots.
  await page.evaluate(async () => {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
  });
  fsSync.rmSync(htmlPath, {force: true});
  attachLiveScreencast(page._client());
  liveState().latest = null;
  record('live_set', {total_ms: elapsed(started), live_generation: liveState().generation});
  send({type: 'result', request_id: message.request_id, status: 'OK', total_ms: elapsed(started), live_generation: liveState().generation});
};

const liveScrub = async (cueMs, stageMs) => {
  await liveState().page._client().send('Target.activateTarget', {
    targetId: liveState().page.target()._targetId,
  });
  await liveState().page.evaluate(async (cue, stage) => {
    window.__2byteStopReplay?.();
    const driver = window.__2byteSeek;
    if (typeof driver !== 'function') throw new Error('live driver missing');
    await driver(cue, stage);
  }, Math.max(0, Number(cueMs) || 0), Math.max(0, Number(stageMs) || 0));
};

const handleLivePlay = async (message) => {
  const started = performance.now();
  touchLiveIdle();
  // LIVE has its own pages and does not cancel unrelated export/card jobs.
  if (!liveState().page) throw new Error('live page not configured (live_set first)');
  liveState().latest = null;
  liveState().captureEpochMs = now();
  const cueMs = Math.max(0, Number(message.cue_ms || 0));
  const stageMs = Math.max(0, Number(message.stage_ms || cueMs));
  const rate = Math.min(4.0, Math.max(0.1, Number(message.rate || 1.0)));
  // Deterministic sync point, then let the compositor run the animations —
  // screencast pushes frames without any per-frame request round trip. The
  // screencast must be watching BEFORE the sync point: a paused page that
  // changes only once (scrub) would otherwise never push that frame.
  await ensureLiveScreencast(Number(message.every_nth_frame || 1));
  await liveState().page._client().send('Target.activateTarget', {
    targetId: liveState().page.target()._targetId,
  });
  await liveState().page.evaluate(async (cue, stage, r) => {
    const driver = window.__2bytePlay;
    if (typeof driver !== 'function') throw new Error('live play driver missing');
    await driver(cue, stage, r);
  }, cueMs, stageMs, rate);
  liveState().playing = true;
  liveState().lastFrameAt = performance.now();
  record('live_play', {total_ms: elapsed(started), cue_ms: cueMs, rate});
  send({type: 'result', request_id: message.request_id, status: 'OK', total_ms: elapsed(started), cue_ms: cueMs, stage_ms: stageMs, rate});
};

const handleLivePause = async (message) => {
  const started = performance.now();
  const control = liveState().control;
  const checkCurrent = () => {
    if (control !== liveState().control) throw new Error('superseded paused frame');
  };
  touchLiveIdle();
  // LIVE has its own pages and does not cancel unrelated export/card jobs.
  if (!liveState().page) throw new Error('live page not configured (live_set first)');
  liveState().playing = false;
  await ensureLiveScreencast(Number(message.every_nth_frame || 1));
  checkCurrent();
  liveState().latest = null;
  liveState().captureEpochMs = now();
  await liveScrub(message.cue_ms, message.stage_ms);
  checkCurrent();
  const drivenAt = performance.now();
  const readyAt = performance.now();
  // The shared driver now awaits WAAPI readiness and freezes every animation
  // at the requested time. Capture that surface directly, as export does;
  // queued RAF callbacks and old screencast bitmaps are not a paint barrier.
  const seed = await captureLivePng();
  checkCurrent();
  const phases = {driver_ms: drivenAt-started, settle_ms: readyAt-drivenAt, capture_ms: performance.now()-readyAt};
  record('live_pause', {total_ms: elapsed(started), ...phases});
  send({type: 'result', request_id: message.request_id, status: 'OK', total_ms: elapsed(started), ...phases, png_base64: seed});
};

const handleLiveText = async (message) => {
  const started = performance.now();
  if (!liveState().page) throw new Error('live page not configured (live_set first)');
  const metrics = await liveState().page.evaluate((text, speaker, duration, placement, prepared) => {
    const fn = window.__2byteSetCue;
    if (typeof fn !== 'function') throw new Error('set-cue driver missing');
    if (!fn(text, speaker, duration)) throw new Error('cue template missing');
    if (typeof window.__2byteSetPlacement === 'function') window.__2byteSetPlacement(placement);
    for(const cue of prepared.slice(0,4)) window.__2bytePrepareCue?.(cue.text, cue.speaker);
    return {...window.__2byteMetrics};
  }, String(message.text || ''), String(message.speaker || ''), Number(message.duration_ms || 2400), message.placement || {}, message.prepared_cues || []);
  liveState().latest = null;
  record('live_text', {total_ms: elapsed(started)});
  send({type: 'result', request_id: message.request_id, status: 'OK', total_ms: elapsed(started), metrics});
};

const handleLiveLatest = async (message) => {
  if (!liveState().page) throw new Error('live page not configured (live_set first)');
  const since = Number(message.since_seq || 0);
  const state = liveState();
  // Chromium screencast can stop sending damage notifications while CSS
  // switches between layout and compositor-only animations. Request actual
  // pixels from the same running page after three 60 Hz frames without a push;
  // do not pause, replay, change the clock, or reuse a cached bitmap.
  if (state.playing && !state.capturePending && performance.now()-state.lastFrameAt > 50) {
    const control = state.control, sequence = state.frameSeq;
    const page = state.page, generation = state.generation, capturedAfter = now();
    const started = performance.now();
    state.capturePending = true;
    try {
      const data = await captureLivePng();
      if (control === state.control && state.playing && sequence === state.frameSeq
          && page === state.page && generation === state.generation) {
        state.captureEpochMs = Math.max(state.captureEpochMs, capturedAfter);
        state.latest = {seq: ++state.frameSeq, data, ts: now(), captured_ms: capturedAfter, source: 'fresh_capture'};
        state.lastFrameAt = performance.now();
        record('live_stream_recovery', {total_ms: elapsed(started), live_generation: state.generation});
      }
    } finally { state.capturePending = false; }
  }
  const latest = state.latest;
  if (!latest || latest.seq <= since) {
    send({type: 'result', request_id: message.request_id, status: 'OK', seq: since, unchanged: true});
    return;
  }
  send({
    type: 'result',
    request_id: message.request_id,
    status: 'OK',
    seq: latest.seq,
    captured_ms: latest.captured_ms,
    frame_source: latest.source,
    received_ms: latest.ts,
    cdp_interval_ms: liveState().cdpIntervalMs,
    cdp_ack_ms: liveState().cdpAckMs,
    latest_age_ms: now()-latest.ts,
    skipped_sequences: Math.max(0, latest.seq-since-1),
    png_base64: latest.data,
  });
};

const handleLiveFrame = async (message) => {
  const started = performance.now();
  if (!liveState().page) throw new Error('live page not configured (live_set first)');
  liveState().latest = null;
  liveState().captureEpochMs = now();
  const cueMs = Math.max(0, Number(message.cue_ms || 0));
  const stageMs = Math.max(0, Number(message.stage_ms || cueMs));
  await liveScrub(cueMs, stageMs);
  const png = await captureLivePng();
  record('live_frame', {total_ms: elapsed(started)});
  clearIdleTimer();
  send({
    type: 'result',
    request_id: message.request_id,
    status: 'OK',
    total_ms: elapsed(started),
    live_generation: liveState().generation,
    cue_ms: cueMs,
    stage_ms: stageMs,
    png_base64: png,
  });
  armIdleShutdown();
};

const handleMessage = async (message) => {
  if (message.type === 'live_material_frame') {
    const page=liveState().page;if(!page)throw new Error('live page not configured');
    await page.evaluate((semanticOnly)=>{
      const cue=document.querySelector('.wt-cue');
      const explicit=cue?.querySelector('[data-semantic-text="true"]');
      const nodes=Array.from(cue?.querySelectorAll('[data-caption-text]')||[]).filter(n=>
        !semanticOnly||(!n.closest('[aria-hidden="true"]')&&(!explicit||n.closest('[data-semantic-text="true"]'))));
      window.__2byteProbeRestore=nodes.flatMap(n=>[n,...n.querySelectorAll('*')]).map(n=>[n,n.getAttribute('style')]);
      for(const [n] of window.__2byteProbeRestore)n.style.setProperty('visibility','hidden','important');
    },Boolean(message.semantic_only));
    let png;
    try {png=await captureLivePng();}
    finally {await page.evaluate(()=>{
      for(const [n,style] of window.__2byteProbeRestore||[]){
        if(style===null)n.removeAttribute('style');else n.setAttribute('style',style);
      }
      delete window.__2byteProbeRestore;
    });}
    send({type:'result',request_id:message.request_id,status:'OK',png_base64:png});return;
  }
  if (message.type === 'live_caption_review') {
    const page=liveState().page;
    if(!page)throw new Error('live page not configured');
    const metrics=await page.evaluate(async()=>{
      await window.__trialReady;
      if(!window.__trialMetrics)throw new Error('static caption trial required');
      const root=document.querySelector('.caption').getBoundingClientRect();
      const style=selector=>{const s=getComputedStyle(document.querySelector(selector));return {font:s.font,stroke:s.webkitTextStrokeColor,strokeWidth:s.webkitTextStrokeWidth,filter:s.filter,opacity:s.opacity};};
      return {...window.__trialMetrics,root:[root.x,root.y,root.width,root.height],
        outer:style('.outer'),inner:style('.inner'),shadow:style('.shadow')};
    });
    const clip={x:96,y:810,width:1728,height:216};
    const captured=await page._client().send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false,clip:{...clip,scale:1}});
    const detail=captured.value.data;
    send({type:'result',request_id:message.request_id,status:'OK',metrics,detail_png_base64:detail,script_errors:liveState().scriptErrors||[]});
    return;
  }
  if (message.type === 'live_close') {
    const state = liveState();
    if (state.page) await state.page.close();
    state.page = null; state.latest = null;
    liveSessions.delete(String(message.session_id));
    send({type: 'result', request_id: message.request_id, status: 'OK'});
    return;
  }
  if (message.type === 'live_selection_geometry') {
    const geometry=await liveState().page.evaluate(async()=>{
      await document.fonts.ready;
      await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
      const rect=e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];};
      const style=e=>{const c=getComputedStyle(e);return {fontFamily:c.fontFamily,fontSize:c.fontSize,
        fontWeight:c.fontWeight,lineHeight:c.lineHeight,letterSpacing:c.letterSpacing,transform:c.transform,
        strokeWidth:c.webkitTextStrokeWidth,strokeColor:c.webkitTextStrokeColor,fill:c.webkitTextFillColor};};
      const cue=document.querySelector('.wt-cue');
      const text=Array.from(cue?.querySelectorAll('[data-caption-text]')||[]).filter(e=>!e.closest('[aria-hidden="true"]'));
      const elements=new Set(text);
      for(const e of text){for(let a=e.parentElement;a&&a!==cue;a=a.parentElement){
        const r=a.getBoundingClientRect();if(r.width<innerWidth*.95&&r.height<innerHeight*.65)elements.add(a);
      }}
      // Include local decorations bound to a text group, excluding stage-wide effects.
      for(const a of Array.from(elements))for(const e of a.querySelectorAll('*')){
        const r=e.getBoundingClientRect();if(r.width<innerWidth*.95&&r.height<innerHeight*.65)elements.add(e);
      }
      const boxes=Array.from(elements).map(e=>{
        const r=rect(e),s=getComputedStyle(e);
        const b=parseFloat(s.webkitTextStrokeWidth)||0;
        // SVG decorations have no offsetWidth/offsetHeight. NaN padding was
        // serialized as null and made Python restart the otherwise ready page.
        const scale=Math.max(r[2]/Math.max(1,Number(e.offsetWidth)||r[2]),
                             r[3]/Math.max(1,Number(e.offsetHeight)||r[3]));
        const pad=b*scale+2;return [r[0]-pad,r[1]-pad,r[2]+2*pad,r[3]+2*pad];
      }).filter(r=>r.every(Number.isFinite));
      const x=Math.min(...boxes.map(r=>r[0])),y=Math.min(...boxes.map(r=>r[1]));
      const right=Math.max(...boxes.map(r=>r[0]+r[2])),bottom=Math.max(...boxes.map(r=>r[1]+r[3]));
      return {viewport:[innerWidth,innerHeight],dpr:devicePixelRatio,fonts_ready:document.fonts.status==='loaded',
        subject_rect:boxes.length?[x,y,right-x,bottom-y]:null,
        roots:cue?[{rect:rect(cue),style:style(cue)},...Array.from(cue.children).map(e=>({rect:rect(e),style:style(e)}))]:[],
        text_nodes:text.map(e=>({rect:rect(e),style:style(e)}))};
    });
    send({type:'result',request_id:message.request_id,status:'OK',geometry});return;
  }
  if (message.type === 'live_diagnostics') {
    const diagnostics = await liveState().page.evaluate((selectors) => ({
      metrics: window.__2byteMetrics || {},
      motion_map: window.__2byteMotionMap?.(document.querySelector('.wt-cue')) || [],
      timelines: Object.entries(window.__timelines || {}).map(([id,tl])=>({id,paused:tl.paused(),time:tl.time(),duration:tl.duration()})),
      dom_elements: document.querySelectorAll('*').length,
      animations: document.getAnimations().map(a => {
        const e=a.effect.target, t=a.effect.getTiming();
        return {name:a.animationName,time:a.currentTime,state:a.playState,
          end:a.effect.getComputedTiming().endTime,delay:t.delay,duration:t.duration,iterations:t.iterations,
          cue:!!e.closest('.wt-cue'),affects_text:!!e.closest('.wt-w') || !!e.querySelector('.wt-w') ||
            (e.closest('.wt-cue') && !!e.textContent.trim()),target:e.className?.baseVal ?? e.className};
      }),
      viewport: [innerWidth, innerHeight],
      dpr: devicePixelRatio,
      fonts_ready: document.fonts.status==='loaded',
      caption_layout: document.querySelector('.wt-cue')?.__captionLayout || null,
      cue_text: document.querySelector('.wt-cue')?.textContent || '',
      semantic_text_runs: (() => {
        const cue=document.querySelector('.wt-cue');if(!cue)return [];
        const explicit=cue.querySelector('[data-semantic-text="true"]');
        return Array.from(cue.querySelectorAll('[data-caption-text]'))
          .filter(n=>!n.closest('[aria-hidden="true"]')&&(!explicit||n.closest('[data-semantic-text="true"]')))
          .flatMap(n=>n.querySelectorAll('.wt-w').length?Array.from(n.querySelectorAll('.wt-w')):[n])
          .map(e=>{
            const r=e.getBoundingClientRect();let opacity=1;const composition=[];
            for(let p=e;p&&p!==document.body;p=p.parentElement){const c=getComputedStyle(p);opacity*=c.visibility==='hidden'||c.display==='none'?0:Number(c.opacity);
              if(c.clipPath!=='none'||c.maskImage!=='none'||c.transform!=='none'||c.overflow!=='visible'||c.mixBlendMode!=='normal')
                composition.push({class:p.className,clipPath:c.clipPath,maskImage:c.maskImage,transform:c.transform,overflow:c.overflow,mixBlendMode:c.mixBlendMode});}
            const c=getComputedStyle(e);
            return {text:e.textContent,rect:[r.x,r.y,r.width,r.height],opacity,fontFamily:c.fontFamily,fontSize:c.fontSize,
              fontWeight:c.fontWeight,color:c.color,textFillColor:c.webkitTextFillColor,
              textStrokeWidth:c.webkitTextStrokeWidth,textStrokeColor:c.webkitTextStrokeColor,
              paintOrder:c.paintOrder,textShadow:c.textShadow,backgroundImage:c.backgroundImage,backgroundClip:c.backgroundClip,zIndex:c.zIndex,whiteSpace:c.whiteSpace,lineHeight:c.lineHeight,composition};
          });
      })(),
      words: Array.from(document.querySelectorAll('.wt-cue .wt-w')).map(e => {
        const r=e.getBoundingClientRect(); let opacity=1;
        for (let p=e;p && p!==document.body;p=p.parentElement) opacity*=Number(getComputedStyle(p).opacity);
        return {text:e.textContent,rect:[r.x,r.y,r.width,r.height],opacity};
      }),
      text_runs: (() => {
        const cue=document.querySelector('.wt-cue');if(!cue)return [];
        const walker=document.createTreeWalker(cue,NodeFilter.SHOW_TEXT),runs=[];
        while(walker.nextNode()) {
          const node=walker.currentNode;if(!node.textContent.trim())continue;
          const range=document.createRange();range.selectNodeContents(node);const r=range.getBoundingClientRect();
          let opacity=1;for(let e=node.parentElement;e&&e!==document.body;e=e.parentElement) {
            const s=getComputedStyle(e);opacity*=s.visibility==='hidden'?0:Number(s.opacity);
          }
          runs.push({text:node.textContent,rect:[r.x,r.y,r.width,r.height],opacity});
        }
        return runs;
      })(),
      missing_svg_ids: Array.from(document.querySelectorAll('[fill],[filter],[mask],[clip-path]')).flatMap(e =>
        Array.from(e.attributes).flatMap(a => Array.from(a.value.matchAll(/url\(["']?#([^)'" ]+)/g))
          .filter(m => !document.getElementById(m[1])).map(m => m[1]))),
      roots: ['html','body','.wt-frame','.wt-stage','.wt-cue',...selectors].map(s => {
        const e=document.querySelector(s);
        if (!e) return {selector:s, missing:true};
        const r=e.getBoundingClientRect();
        const c=getComputedStyle(e);
        return {selector:s,rect:[r.x,r.y,r.width,r.height],background:c.backgroundColor,
          opacity:c.opacity,transform:c.transform,fontSize:c.fontSize,fontFamily:c.fontFamily,clipPath:c.clipPath,
          textShadow:c.textShadow,backgroundImage:c.backgroundImage,textFillColor:c.webkitTextFillColor,textStrokeWidth:c.webkitTextStrokeWidth,zIndex:c.zIndex,
          gsap:window.gsap?Object.fromEntries(['rotation','xPercent','yPercent','scaleX','scaleY'].map(k=>[k,window.gsap.getProperty(e,k)])):null,
          top:c.top,bottom:c.bottom,left:c.left,right:c.right,
          animation:c.animation,display:c.display,overflow:c.overflow};
      })
    }), message.selectors || []);
    if (message.include_fonts) {
      const probe = liveState().page._client();
      try {
        await probe.send('DOM.enable');
        await probe.send('CSS.enable');
        const {value:{root}} = await probe.send('DOM.getDocument');
        const {value:{nodeIds}} = await probe.send('DOM.querySelectorAll', {nodeId:root.nodeId,
          selector:'.wt-cue [data-caption-text], .wt-cue .wt-w'});
        diagnostics.rendered_fonts=[];
        for (const nodeId of nodeIds.slice(0,80)) {
          const {value:{fonts}} = await probe.send('CSS.getPlatformFontsForNode',{nodeId});
          diagnostics.rendered_fonts.push({node_id:nodeId,fonts});
        }
      } catch(error) { diagnostics.font_probe_error=String(error); }
    }
    diagnostics.script_errors = liveState().scriptErrors || [];
    send({type:'result',request_id:message.request_id,status:'OK',diagnostics,
      live_generation:liveState().generation});
    return;
  }
  if (message.type === 'render') {
    enqueue(message);
    return;
  }
  if (message.type === 'cancel') {
    const requestId = String(message.request_id || '');
    const index = queue.findIndex((item) => item.request.request_id === requestId);
    if (index >= 0) {
      queue.splice(index, 1);
      record('cancel', {request_id: requestId, phase: 'queued'});
      send({type: 'result', request_id: requestId, status: 'CANCELLED'});
    } else if (active?.request.request_id === requestId) {
      active.cancel();
      record('cancel', {request_id: requestId, phase: 'active'});
    }
    return;
  }
  if (message.type === 'warm') {
    clearIdleTimer();
    const started = performance.now();
    const events = await ensureWarm();
    send({type: 'result', request_id: message.request_id, status: 'OK', total_ms: elapsed(started), telemetry: events});
    armIdleShutdown();
    return;
  }
  if (message.type === 'warm_live') {
    const started = performance.now();
    const events = await ensureBrowser();
    send({type:'result',request_id:message.request_id,status:'OK',total_ms:elapsed(started),telemetry:events});
    armIdleShutdown();
    return;
  }
  if (message.type === 'live_set') {
    await handleLiveSet(message);
    return;
  }
  if (message.type === 'live_frame') {
    await handleLiveFrame(message);
    return;
  }
  if (message.type === 'live_play') {
    await handleLivePlay(message);
    return;
  }
  if (message.type === 'live_pause') {
    await handleLivePause(message);
    return;
  }
  if (message.type === 'live_text') {
    await handleLiveText(message);
    return;
  }
  if (message.type === 'live_latest') {
    await handleLiveLatest(message);
    return;
  }
  if (message.type === 'telemetry') {
    send({type: 'result', request_id: message.request_id, status: 'OK', telemetry: [...telemetry]});
    return;
  }
  if (message.type === 'inject_failure') {
    if (message.failure === 'node_crash') process.exit(86);
    if (message.failure === 'browser_crash') await closeBrowser('failure_injection');
    if (message.failure === 'malformed_response') process.stdout.write('{malformed\n');
    send({type: 'result', request_id: message.request_id, status: 'OK'});
    return;
  }
  if (message.type === 'shutdown') {
    await closeBrowser('shutdown');
    process.exit(0);
  }
  throw new Error('unknown renderer message type');
};

const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
input.on('line', (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch (error) {
    send({type: 'protocol_error', error: String(error?.message || error)});
    return;
  }
  let dispatched;
  if (String(message.type).startsWith('live_')) {
    const key = String(message.session_id || 'default');
    if (!liveSessions.has(key)) liveSessions.set(key, createLiveState());
    const state = liveSessions.get(key);
    if (message.type === 'live_cancel') {
      state.control += 1;
      send({type:'result',request_id:message.request_id,status:'OK'});
      return;
    }
    if (message.type === 'live_latest') {
      dispatched = liveContext.run(state, () => handleMessage(message));
    } else {
      const control = ++state.control;
      const task = () => liveContext.run(state, async () => {
        if (['live_play','live_pause','live_frame'].includes(message.type) && control !== state.control) {
          send({type:'result',request_id:message.request_id,status:'STALE',error:'superseded playback time'});
          return;
        }
        await handleMessage(message);
      });
      dispatched = state.tail.then(task, task);
      state.tail = dispatched.catch(() => undefined);
    }
  } else dispatched = handleMessage(message);
  Promise.resolve(dispatched).catch((error) => {
    send({type: 'result', request_id: message.request_id, status: 'ERROR', error: String(error?.message || error)});
  });
});

input.on('close', async () => {
  await closeBrowser('stdin_closed');
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await closeBrowser('sigterm');
  process.exit(0);
});

send({type: 'service_ready', renderer_generation: rendererGeneration, pid: process.pid});
armIdleShutdown();
