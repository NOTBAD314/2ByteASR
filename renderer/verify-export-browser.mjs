// Local visual gate for the production browser change. No app/project writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {openBrowser,selectComposition,renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';
const [propsFile,out]=process.argv.slice(2);
const source=JSON.parse(await fs.readFile(propsFile,'utf8'));
const spans=[100,300,500,1500,3000,6000],fps=60;
let offset=500;
const targets=new Set(),cases=[];
const props={...source,cues:spans.map((span,i)=>{
 const first=Math.round(offset*fps/1000),last=Math.round((offset+span)*fps/1000);
 const frames=[first-1,first,...[.02,.08,.2,.33,.5,.66,.8,.9,.98].map(p=>Math.min(last-1,Math.round((offset+span*p)*fps/1000))),last,last+1];
 frames.forEach(f=>targets.add(f));cases.push({span,startMs:offset,frames:[...new Set(frames)]});
 const cue={...source.cues[0],id:'duration-'+span,text:'一二三四五六七八九十甲乙丙丁戊',startMs:offset,endMs:offset+span};offset+=span+300;return cue;
}),durationInFrames:Math.ceil((offset+200)*fps/1000),fps};
await fs.mkdir(out,{recursive:true});await fs.writeFile(path.join(out,'cases.json'),JSON.stringify({cases,props},null,2));
const serveUrl=await bundle({entryPoint:path.resolve('src/index.ts'),onProgress:()=>{}});
for(const mode of (process.env.TWOBYTE_MATRIX_REVERSE_ONLY==='1'?['after']:['before','after'])){
 const folder=path.join(out,mode);await fs.mkdir(folder,{recursive:true});
 const reference='C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
 const browser=mode==='before'?await openBrowser('chrome',{browserExecutable:reference,logLevel:'error'}):await openExportBrowser(path.resolve('node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'),reference);
 if(browser.exportFontFamilies)await fs.writeFile(path.join(folder,'generic-fonts.json'),JSON.stringify(browser.exportFontFamilies,null,2));
 let reverseDone=false,rendering=false,reverseStarted=false;
 const closes=[];
 const create=browser._createPageInContext.bind(browser);
 browser._createPageInContext=async(...args)=>{
  const page=await create(...args),close=page.close.bind(page);
  page.close=(...a)=>{const task=(async()=>{
   if(rendering){
    const typography=await page.evaluate(()=>[...document.querySelectorAll('.mult-value,.plate-stamp,.line')].map(n=>{const c=getComputedStyle(n);return {selector:n.className,font:c.font,fontFamily:c.fontFamily,fontWeight:c.fontWeight,fontSize:c.fontSize};})).catch(()=>[]);
    if(typography.length){
     const client=page._client();await client.send('DOM.enable');await client.send('CSS.enable');
     const doc=(await client.send('DOM.getDocument')).value.root.nodeId;
     for(const row of typography){const node=(await client.send('DOM.querySelector',{nodeId:doc,selector:'.'+row.selector})).value.nodeId;if(node)row.actualFonts=(await client.send('CSS.getPlatformFontsForNode',{nodeId:node})).value.fonts;}
     await fs.writeFile(path.join(folder,'typography.json'),JSON.stringify(typography,null,2));
    }
   }
   if(mode==='after'&&rendering&&!reverseStarted&&process.env.TWOBYTE_MATRIX_SINGLE_ONLY!=='1'){
    reverseStarted=true;
    const state=await page.evaluate(()=>typeof window.remotion_setFrame).catch(()=>null);
    // This uses the same mounted DOM after the production forward sequence.
    if(state==='function'){
     reverseDone=true;
     for(const frame of [...targets].sort((a,b)=>b-a)){
      await page.evaluate((f)=>window.remotion_setFrame(f,'SubtitleOverlay',0),frame);
      await page.evaluate(()=>new Promise((resolve,reject)=>{const t=performance.now();const ready=()=>{if(window.remotion_cancelledError)reject(new Error(window.remotion_cancelledError));else if(window.remotion_renderReady)document.fonts.ready.then(resolve);else if(performance.now()-t>10000)reject(new Error('ready timeout'));else requestAnimationFrame(ready);};requestAnimationFrame(ready);}));
      const client=page._client();await client.send('Emulation.setDefaultBackgroundColorOverride',{color:{r:0,g:0,b:0,a:0}});
      const reply=await client.send('Page.captureScreenshot',{format:'png',fromSurface:true,optimizeForSpeed:true,clip:{x:0,y:0,width:1920,height:1080,scale:1}});
      await fs.writeFile(path.join(folder,`reverse-${frame}.png`),Buffer.from(reply.value.data,'base64'));
     }
    }
   }
   return close(...a);
  })();closes.push(task);return task;
  };return page;
 };
 const writes=[];const began=performance.now();
 try{
  const composition=await selectComposition({serveUrl,id:'SubtitleOverlay',inputProps:props,puppeteerInstance:browser,logLevel:'error'});
  rendering=true;
  await renderFrames({serveUrl,composition,inputProps:props,puppeteerInstance:browser,outputDir:null,imageFormat:'png',concurrency:4,
    ...((process.env.TWOBYTE_MATRIX_REVERSE_ONLY==='1'||process.env.TWOBYTE_MATRIX_SINGLE_ONLY==='1')?{frameRange:[Math.round((props.cues.at(-1).startMs+3000)*fps/1000),Math.round((props.cues.at(-1).startMs+3000)*fps/1000)]}:{}),
    logLevel:'error',onStart:()=>{},onFrameUpdate:()=>{},onFrameBuffer:(buffer,frame)=>{if(targets.has(frame))writes.push(fs.writeFile(path.join(folder,`frame-${frame}.png`),buffer));}});
  await Promise.all(writes);await Promise.all(closes);console.log(mode,performance.now()-began,'reverse',reverseDone);
 }finally{await browser.close({silent:true});}
}
