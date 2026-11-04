// Static members of a mixed export keep the SAME production DOM/font renderer.
// Render each immutable cue once, rather than a ProRes frame for its lifetime.
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {selectComposition, renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
import {installBundleBoundary} from './resource-boundary.mjs';

const manifest = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const props = JSON.parse(await fs.readFile(manifest.props, 'utf8'));
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts'), onProgress: () => {}});
const browser = await openExportBrowser(manifest.browser, manifest.referenceBrowser);
try {
  await installBundleBoundary(browser, serveUrl, event => process.stdout.write(JSON.stringify({type:'resource_blocked', ...event})+'\n'));
  const composition = await selectComposition({serveUrl, id:'SubtitleOverlay', inputProps:props,
    puppeteerInstance:browser, logLevel:'error'});
  const outputs = new Map(manifest.stills.map(item => [item.frame, item.output]));
  const writes = [];
  await renderFrames({serveUrl, composition, inputProps:props, outputDir:null,
    frames:[...outputs.keys()], imageFormat:'png', concurrency:2,
    puppeteerInstance:browser, logLevel:'error', onStart:()=>{},
    onFrameBuffer:(buffer, frame) => writes.push(fs.writeFile(outputs.get(frame), buffer, {flag:'wx'})),
    onFrameUpdate:done => process.stdout.write(JSON.stringify({type:'still', done, total:outputs.size})+'\n'),
  });
  await Promise.all(writes);
} finally {
  await browser.close({silent:true});
}
