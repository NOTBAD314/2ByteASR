// Static members of a mixed export keep the SAME production DOM/font renderer.
// Render each immutable cue once, rather than a ProRes frame for its lifetime.
import fs from 'node:fs/promises';
import {writeFileSync} from 'node:fs';
import {selectComposition, renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
import {installBundleBoundary} from './resource-boundary.mjs';
import {exportBundle} from './export-bundle.mjs';

const manifest = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const props = JSON.parse(await fs.readFile(manifest.props, 'utf8'));
const started=performance.now();
const emit=(type,value={})=>process.stdout.write(JSON.stringify({type,atMs:performance.now()-started,...value})+'\n');
emit('process_ready',{rss:process.memoryUsage().rss});
const prepared=await exportBundle(emit);
const serveUrl=prepared.serveUrl;
let browser;
try {
  browser=await openExportBrowser(manifest.browser, manifest.referenceBrowser,emit);
  await installBundleBoundary(browser, serveUrl, event => process.stdout.write(JSON.stringify({type:'resource_blocked', ...event})+'\n'));
  const composition = await selectComposition({serveUrl, id:'SubtitleOverlay', inputProps:props,
    puppeteerInstance:browser, logLevel:'error'});
  emit('static_page_and_composition_ready');
  const outputs = new Map(manifest.stills.map(item => [item.frame, item.output]));
  let writeMs=0, bytes=0;
  await renderFrames({serveUrl, composition, inputProps:props, outputDir:null,
    frames:[...outputs.keys()], imageFormat:'png', concurrency:2,
    puppeteerInstance:browser, logLevel:'error', onStart:()=>{},
    // Remotion's callback is synchronous. Apply backpressure here, so a slow
    // temporary disk cannot retain an unbounded list of PNG buffers/promises.
    onFrameBuffer:(buffer, frame) => {const at=performance.now();writeFileSync(outputs.get(frame),buffer,{flag:'wx'});writeMs+=performance.now()-at;bytes+=buffer.length;},
    onFrameUpdate:done => process.stdout.write(JSON.stringify({type:'still', done, total:outputs.size})+'\n'),
  });
  emit('static_frames_complete',{writeMs,bytes,pagesCreated:browser.exportPagesCreated});
} finally {
  if(browser)await browser.close({silent:true});
  await prepared.release();
  emit('browser_closed');
}
