// Production HTML overlays: one bundle/browser, bounded Remotion pages.
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {openBrowser, selectComposition, renderMedia} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
import {installBundleBoundary} from './resource-boundary.mjs';

const manifest=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const inputProps=JSON.parse(await fs.readFile(manifest.props,'utf8'));
const started=performance.now();
const emit=(type,value)=>process.stdout.write(JSON.stringify({type,atMs:performance.now()-started,...value})+'\n');
const serveUrl=await bundle({entryPoint:path.resolve('src/index.ts'),onProgress:()=>{}});
emit('bundle',{});
const browser=await openExportBrowser(manifest.browser,manifest.referenceBrowser);
emit('browser',{genericFonts:browser.exportFontFamilies,fontSource:browser.exportFontSource,executable:browser.exportExecutable});
try {
  await installBundleBoundary(browser,serveUrl,(event)=>emit('resource_blocked',event));
  const composition=await selectComposition({serveUrl,id:'SubtitleOverlay',inputProps,puppeteerInstance:browser,logLevel:'error'});
  emit('composition',{});
  let completed=0;
  const total=manifest.segments.reduce((sum,s)=>sum+s.end-s.start+1,0);
  for(const segment of manifest.segments){
    let reported=-1,framesComplete=false;
    await renderMedia({serveUrl,composition,inputProps,puppeteerInstance:browser,
      outputLocation:segment.output,frameRange:[segment.start,segment.end],
      codec:'prores',proResProfile:'4444',pixelFormat:'yuva444p10le',imageFormat:'png',
      concurrency:Math.min(4,Math.max(1,manifest.pages)),logLevel:'error',
      onProgress:({renderedFrames,encodedFrames})=>{
        const done=completed+renderedFrames;
        if(!framesComplete&&renderedFrames>=segment.end-segment.start+1){framesComplete=true;emit('frames_complete',{start:segment.start,end:segment.end,encodedFrames});}
        if(done-reported>=Math.max(1,total/200)){reported=done;emit('progress',{done,total,renderedFrames,encodedFrames});}
      },
    });
    completed+=segment.end-segment.start+1;
    emit('segment',{start:segment.start,end:segment.end,done:completed,total});
  }
} finally {
  await browser.close({silent:true});
}
emit('complete',{});
