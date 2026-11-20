// Production HTML overlays: one bundle/browser, bounded Remotion pages.
import fs from 'node:fs/promises';
import {writeFileSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {selectComposition, renderMedia, renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
import {installBundleBoundary} from './resource-boundary.mjs';
import {exportBundle} from './export-bundle.mjs';

const manifest=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const inputProps=JSON.parse(await fs.readFile(manifest.props,'utf8'));
const started=performance.now();
const emit=(type,value)=>process.stdout.write(JSON.stringify({type,atMs:performance.now()-started,...value})+'\n');
emit('process_ready',{rss:process.memoryUsage().rss});

// Animated caption windows are mostly fully transparent. ProRes 4444 10-bit
// encoded 4K overlays at ~8 fps with its memory-bounded thread pool. QuickTime
// RLE (lossless 8-bit ARGB, standard MOV) runs ~10x faster, decodes ~2.5x
// faster and is smaller; the final output is 8-bit, so 8-bit alpha suffices.
// Remotion's minimal FFmpeg has no RLE encoder, so the app's full FFmpeg
// (manifest.ffmpeg) receives Remotion's PNG frames in frame order.
// All windows render in ONE renderFrames pass: a pass per window cost ~0.45 s
// of setup, which dominated once captions render only entrance/exit frames.
// Each window's encoder opens at its first frame and closes after its last.
async function renderWindowsRle(composition,segments,onFrame,onWindow){
  const owner=new Map();
  segments.forEach((segment,index)=>{for(let f=segment.start;f<=segment.end;f++)owner.set(f,index);});
  const states=segments.map(segment=>({segment,next:segment.start,waiting:new Map(),encoder:null,exited:null,stderr:'',failed:null}));
  const closing=[];
  const open=state=>{
    const {segment}=state;
    const encoder=spawn(manifest.ffmpeg,['-hide_banner','-loglevel','error','-y',
      '-f','image2pipe','-c:v','png','-framerate',String(composition.fps),'-i','pipe:0',
      '-frames:v',String(segment.end-segment.start+1),'-c:v','qtrle','-pix_fmt','argb','-threads','2',
      '-video_track_timescale','90000',segment.output],{stdio:['pipe','ignore','pipe']});
    encoder.stderr.on('data',chunk=>{state.stderr=(state.stderr+chunk.toString()).slice(-4000);});
    encoder.stdin.on('error',error=>{state.failed=state.failed||error;});
    state.exited=new Promise((resolve,reject)=>{encoder.once('error',reject);encoder.once('close',code=>resolve(code));});
    state.encoder=encoder;
  };
  await renderFrames({serveUrl,composition,inputProps,puppeteerInstance:browser,outputDir:null,
    imageFormat:'png',frames:[...owner.keys()].sort((a,b)=>a-b),
    // Python sizes pages from cores and free memory (overlay_render_pages).
    concurrency:Math.min(4,Math.max(1,manifest.pages)),logLevel:'error',onStart:()=>{},
    onFrameUpdate:()=>{},
    onFrameBuffer:(buffer,frame)=>{
      const state=states[owner.get(frame)];
      if(!state.encoder)open(state);
      state.waiting.set(frame,buffer);
      while(state.waiting.has(state.next)){state.encoder.stdin.write(state.waiting.get(state.next));state.waiting.delete(state.next);state.next++;}
      if(state.next===state.segment.end+1&&!state.closed){
        state.closed=true;state.encoder.stdin.end();
        const done=state.exited.then(code=>{
          if(state.failed||code!==0)throw new Error(`overlay RLE encode failed (exit ${code}): ${state.failed?state.failed.message:''} ${state.stderr}`);
          onWindow(state.segment);
        });
        done.catch(()=>{});  // observed by Promise.all below; never an unhandled rejection
        closing.push(done);
      }
      onFrame();
    },
  });
  await Promise.all(closing);
  const unfinished=states.find(state=>!state.closed);
  if(unfinished)throw new Error(`overlay window ${unfinished.segment.start}-${unfinished.segment.end} incomplete (${unfinished.next-unfinished.segment.start} frames)`);
}

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
      frames:[...outputs.keys()],imageFormat:'png',concurrency:Math.max(1,manifest.pages),
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
  if(manifest.ffmpeg&&manifest.segments.length){
    let rendered=0,reported=-1,finished=0;
    emit('dynamic_segment_start',{start:manifest.segments[0].start,end:manifest.segments.at(-1).end,
      windows:manifest.segments.length,encoder:'qtrle'});
    await renderWindowsRle(composition,manifest.segments,()=>{
      rendered++;
      if(rendered-reported>=Math.max(1,total/200)){reported=rendered;emit('progress',{done:rendered,total,renderedFrames:rendered,encodedFrames:rendered});}
    },segment=>{finished+=segment.end-segment.start+1;emit('segment',{start:segment.start,end:segment.end,done:finished,total});});
    emit('frames_complete',{start:manifest.segments[0].start,end:manifest.segments.at(-1).end,encodedFrames:total});
    manifest.segments=[];
  }
  for(const segment of manifest.segments){
    let reported=-1,framesComplete=false;
    emit('dynamic_segment_start',{start:segment.start,end:segment.end,encoder:'prores'});
    await renderMedia({serveUrl,composition,inputProps,puppeteerInstance:browser,
      outputLocation:segment.output,frameRange:[segment.start,segment.end],
      codec:'prores',proResProfile:'4444',pixelFormat:'yuva444p10le',imageFormat:'png',
      concurrency:Math.min(4,Math.max(1,manifest.pages)),logLevel:'error',
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
