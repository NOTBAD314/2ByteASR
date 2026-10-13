// Capture the first-run chooser animations frame by frame (2026-10-14).
// usage: tools/node/node.exe scripts/render_onboarding_frames.mjs <out-dir> [fps]
// Loads assets/onboarding/source/scenes.html in the bundled headless Chromium
// (renderer/node_modules/.remotion), seeks every animation to each frame time
// and saves transparent PNGs at 2x: <out>/<scene>-<theme>/0000.png ...
// scripts/render_onboarding_scenes.py packs them into animated WebP.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const {openBrowser} = await import(pathToFileURL(path.join(root, 'renderer/node_modules/@remotion/renderer/dist/esm/index.mjs')));
const shell = path.join(root, 'renderer/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
const out = path.resolve(process.argv[2] || 'tmp/onboarding-frames');
const fps = Number(process.argv[3] || 24);
const source = pathToFileURL(path.join(root, 'assets/onboarding/source/scenes.html')).href;

const browser = await openBrowser('chrome', {browserExecutable: shell, logLevel: 'error'});
try {
  const page = await browser.newPage({context: null, logLevel: 'error', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {}});
  const client = page._client();
  await client.send('Emulation.setDeviceMetricsOverride', {width: 260, height: 124, deviceScaleFactor: 2, mobile: false});
  await client.send('Emulation.setDefaultBackgroundColorOverride', {color: {r: 0, g: 0, b: 0, a: 0}});
  for (const scene of ['local', 'cloud', 'light', 'apple']) {
    for (const theme of ['dark', 'light']) {
      await client.send('Page.navigate', {url: `${source}?scene=${scene}&theme=${theme}`});
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
          clip: {x: 0, y: 0, width: 260, height: 124, scale: 1}});
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
