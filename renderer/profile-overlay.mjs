// Isolated Remotion diagnostic. No changes to installed renderer dependencies.
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {openBrowser, selectComposition, renderFrames} from '@remotion/renderer';
import {openExportBrowser} from './export-browser.mjs';

const [propsFile, output, workers='2', gl='default', surface='true', start='60', end='299'] = process.argv.slice(2);
const props=JSON.parse(await fs.readFile(propsFile,'utf8'));
await fs.mkdir(output,{recursive:true});
const samples={}, frames=[], pages=[], writes=[];
const summary=a=>{const b=[...a].sort((a,b)=>a-b);return {n:b.length,total_ms:b.reduce((a,b)=>a+b,0),p50:b[Math.floor(b.length*.5)],p95:b[Math.min(b.length-1,Math.floor(b.length*.95))],p99:b[Math.min(b.length-1,Math.floor(b.length*.99))]};};
const measured=async(key,fn)=>{const t=performance.now();try{return await fn();}finally{(samples[key]??=[]).push(performance.now()-t);}};
const began=performance.now();
const serveUrl=await measured('bundle',()=>bundle({entryPoint:path.resolve('src/index.ts'),onProgress:()=>{}}));
const browser=await measured('browser',()=>process.env.TWOBYTE_PROFILE_BROWSER?.includes('headless-shell')?openExportBrowser(process.env.TWOBYTE_PROFILE_BROWSER,'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'):openBrowser('chrome',{browserExecutable:process.env.TWOBYTE_PROFILE_BROWSER || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',chromiumOptions:gl==='default'?{}:{gl},logLevel:'error'}));
const create=browser._createPageInContext.bind(browser);
browser._createPageInContext=async(...args)=>{
  const page=await measured('page',()=>create(...args));
  const client=page._client(), send=client.send.bind(client), record={index:pages.length,commands:{}};
  pages.push(record);
  await send('Performance.enable');
  client.send=async(command,params,...rest)=>{
    if(command==='Target.activateTarget' && process.env.TWOBYTE_PROFILE_NO_ACTIVATE==='1')return {value:{}};
    if(command==='Page.captureScreenshot' && surface==='false')params={...params,fromSurface:false};
    const t=performance.now();
    try{return await send(command,params,...rest);}
    finally{
      const ms=performance.now()-t;(record.commands[command]??=[]).push(ms);
    }
  };
  const close=page.close.bind(page);
  page.close=async(...args)=>{try{record.metrics=(await send('Performance.getMetrics')).value.metrics;}catch{}return close(...args);};
  return page;
};
let error;
try{
  const composition=await measured('composition',()=>selectComposition({serveUrl,id:'SubtitleOverlay',inputProps:props,puppeteerInstance:browser,logLevel:'error'}));
  await measured('render',()=>renderFrames({serveUrl,composition,inputProps:props,puppeteerInstance:browser,
    outputDir:null,imageFormat:'png',frameRange:[Number(start),Number(end)],concurrency:Number(workers),
    logLevel:'error',onStart:()=>{},onFrameUpdate:(done,frame,ms)=>frames.push({frame,ms}),
    onFrameBuffer:(buffer,frame)=>{if([Number(start),Number(start)+1,Number(start)+15,Number(start)+60,Number(end)].includes(frame))writes.push(fs.writeFile(path.join(output,`frame-${frame}.png`),buffer));},
  }));
  await Promise.all(writes);
}catch(e){error=e.stack;}
finally{
  await browser.close({silent:true});
  const report={workers:Number(workers),gl,surface,frames,elapsed_ms:performance.now()-began,error,
    stages:Object.fromEntries(Object.entries(samples).map(([k,v])=>[k,summary(v)])),
    pages:pages.map(p=>({...p,commands:Object.fromEntries(Object.entries(p.commands).map(([k,v])=>[k,summary(v)]))}))};
  await fs.writeFile(path.join(output,'profile.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({workers,gl,surface,elapsed_ms:report.elapsed_ms,stages:report.stages,error}));
}
if(error)process.exitCode=1;
