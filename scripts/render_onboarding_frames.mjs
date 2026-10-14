// Capture the onboarding animations frame by frame (2026-10-14).
// usage: tools/node/node.exe scripts/render_onboarding_frames.mjs <out-dir> [fps] [source.html] [only,these]
// Loads assets/onboarding/source/scenes.html (the first-run chooser; ?scene=) or
// tutorial.html (the tutorial gestures; ?op=) in the bundled headless Chromium
// (renderer/node_modules/.remotion), seeks every animation to each frame time
// and saves transparent PNGs at 2x: <out>/<scene>-<theme>/0000.png ...
// The page tells its own size (window.SIZE) and scene list (window.SCENES).
// scripts/render_onboarding_scenes.py packs them into animated WebP.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const {openBrowser} = await import(pathToFileURL(path.join(root, 'renderer/node_modules/@remotion/renderer/dist/esm/index.mjs')));
const shell = path.join(root, 'renderer/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
const out = path.resolve(process.argv[2] || 'tmp/onboarding-frames');
const fps = Number(process.argv[3] || 24);
const sourceFile = path.resolve(root, process.argv[4] || 'assets/onboarding/source/scenes.html');
const source = pathToFileURL(sourceFile).href;
const param = path.basename(sourceFile) === 'tutorial.html' ? 'op' : 'scene';
const only = (process.argv[5] || '').split(',').filter(Boolean);

const browser = await openBrowser('chrome', {browserExecutable: shell, logLevel: 'error'});
try {
  const page = await browser.newPage({context: null, logLevel: 'error', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {}});
  const client = page._client();
  await client.send('Emulation.setDefaultBackgroundColorOverride', {color: {r: 0, g: 0, b: 0, a: 0}});
  const load = async (query) => {
    await client.send('Page.navigate', {url: `${source}?${query}`});
    for (let i = 0; i < 200; i += 1) {
      await new Promise((r) => setTimeout(r, 50));
      try {
        const ready = await page.evaluate((p) => document.readyState === 'complete' && typeof window.seek === 'function'
          && location.search.includes(p + '=') && document.fonts.status === 'loaded', param);
        if (ready) break;
      } catch {
        // still navigating
      }
    }
    await new Promise((r) => setTimeout(r, 150));
  };
  await client.send('Emulation.setDeviceMetricsOverride', {width: 400, height: 400, deviceScaleFactor: 2, mobile: false});
  await load(`${param}=__list__&theme=dark`);
  const [width, height] = await page.evaluate(() => window.SIZE || [260, 124]);
  const scenes = (await page.evaluate(() => window.SCENES || ['local', 'cloud', 'light', 'apple']))
    .filter((name) => !only.length || only.includes(name));
  await client.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 2, mobile: false});
  for (const scene of scenes) {
    for (const theme of ['dark', 'light']) {
      await client.send('Page.navigate', {url: `${source}?${param}=${scene}&theme=${theme}`});
      for (let i = 0; i < 200; i += 1) {
        await new Promise((r) => setTimeout(r, 50));
        try {
          const ready = await page.evaluate(() => document.readyState === 'complete' && typeof window.seek === 'function'
            && location.search.includes('scene=') && document.fonts.status === 'loaded');
          if (ready) break;
        } catch {
          // still navigating
        }
      }
      await new Promise((r) => setTimeout(r, 150));
      const total = await page.evaluate(() => window.SCENE_MS);
      const frames = Math.round(total / 1000 * fps);
      const dir = path.join(out, `${scene}-${theme}`);
      await fs.mkdir(dir, {recursive: true});
      for (let f = 0; f < frames; f += 1) {
        const ms = f * 1000 / fps;
        await page.evaluate((t) => window.seek(t), ms);
        // Let the compositor draw the seeked state before capturing (a layer can lag one frame).
        await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
        const shot = await client.send('Page.captureScreenshot', {format: 'png', fromSurface: true,
          clip: {x: 0, y: 0, width, height, scale: 1}});
        const data = shot?.data ?? shot?.value?.data;
        if (!data) throw new Error('no screenshot data: ' + JSON.stringify(Object.keys(shot || {})));
        await fs.writeFile(path.join(dir, String(f).padStart(4, '0') + '.png'), Buffer.from(data, 'base64'));
      }
      console.log(scene, theme, frames, 'frames');
    }
  }
} finally {
  await browser.close({silent: true});
}
