// Production HTML overlays: one bundle/browser, bounded Remotion pages.
import fs from 'node:fs/promises';
import {writeFileSync} from 'node:fs';
import {selectComposition, renderMedia, renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
import {installBundleBoundary} from './resource-boundary.mjs';
import {exportBundle} from './export-bundle.mjs';

const manifest=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const inputProps=JSON.parse(await fs.readFile(manifest.props,'utf8'));
const started=performance.now();
const emit=(type,value)=>process.stdout.write(JSON.stringify({type,atMs:performance.now()-started,...value})+'\n');
emit('process_ready',{rss:process.memoryUsage().rss});
const prepared=await exportBundle(emit);
const serveUrl=prepared.serveUrl;
let browser;
try {
  browser=await openExportBrowser(manifest.browser,manifest.referenceBrowser,emit);
  emit('browser',{genericFonts:browser.exportFontFamilies,fontSource:browser.exportFontSource,executable:browser.exportExecutable});
  await installBundleBoundary(browser,serveUrl,(event)=>emit('resource_blocked',event));
  if(manifest.stillsManifest){
    const stills=JSON.parse(await fs.readFile(manifest.stillsManifest,'utf8'));
    const staticProps=JSON.parse(await fs.readFile(stills.props,'utf8'));
    const staticComposition=await selectComposition({serveUrl,id:'SubtitleOverlay',inputProps:staticProps,puppeteerInstance:browser,logLevel:'error'});
    emit('static_page_and_composition_ready',{});
    const outputs=new Map(stills.stills.map(item=>[item.frame,item.output]));
    let writeMs=0,bytes=0;
    await renderFrames({serveUrl,composition:staticComposition,inputProps:staticProps,outputDir:null,
      frames:[...outputs.keys()],imageFormat:'png',concurrency:Math.min(2,manifest.pages),
      puppeteerInstance:browser,logLevel:'error',onStart:()=>{},
      onFrameBuffer:(buffer,frame)=>{const at=performance.now();writeFileSync(outputs.get(frame),buffer,{flag:'wx'});writeMs+=performance.now()-at;bytes+=buffer.length;},
      onFrameUpdate:done=>emit('still',{done,total:outputs.size}),
    });
    emit('static_frames_complete',{writeMs,bytes,pagesCreated:browser.exportPagesCreated});
  }
  const composition=await selectComposition({serveUrl,id:'SubtitleOverlay',inputProps,puppeteerInstance:browser,logLevel:'error'});
  emit('composition',{});
  let completed=0;
  const total=manifest.segments.reduce((sum,s)=>sum+s.end-s.start+1,0);
  for(const segment of manifest.segments){
    let reported=-1,framesComplete=false;
    emit('dynamic_segment_start',{start:segment.start,end:segment.end});
    await renderMedia({serveUrl,composition,inputProps,puppeteerInstance:browser,
      outputLocation:segment.output,frameRange:[segment.start,segment.end],
      codec:'prores',proResProfile:'4444',pixelFormat:'yuva444p10le',imageFormat:'png',
      concurrency:Math.min(2,Math.max(1,manifest.pages)),logLevel:'error',
      // The automatic ProRes frame-thread pool retained 8.21 GB for 62 4K
      // frames. Browser page concurrency does not bound this encoder pool.
      ffmpegOverride:({type,args})=>type==='stitcher'&&args.includes('prores_ks')
        ? [...args.slice(0,-1),'-threads:v','4',args.at(-1)] : args,
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
  if(browser)await browser.close({silent:true});
  await prepared.release();
  emit('browser_closed',{pagesCreated:browser?.exportPagesCreated});
}
emit('complete',{});
