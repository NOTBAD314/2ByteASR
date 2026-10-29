import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {openExportBrowser} from '../renderer/export-browser.mjs';
import {resourceAllowed,installBundleBoundary,installPageBoundary,protectLiveHtml} from '../renderer/resource-boundary.mjs';

const root=path.resolve('renderer');
const executable=path.join(root,'node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
const pageOptions={context:null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}};

test('G03 missing explicit executable fails locally',async()=>{
  await assert.rejects(openExportBrowser('missing-browser.exe','missing-reference.exe'),/Local renderer browser is missing/);
});
test('G01 exact origin/path allowlist excludes proxy, traversal and files',()=>{
  const policy={origin:'http://localhost:3000',paths:new Set(['/','/bundle.js','/fonts/a.woff2'])};
  for(const url of ['http://localhost:3001/bundle.js','https://localhost:3000/bundle.js',
    'http://localhost:3000/proxy?src=http://localhost:9/','http://localhost:3000/%70roxy',
    'file:///C:/synthetic-sentinel.svg','data:text/html,bad']) assert.equal(resourceAllowed(url,policy),false,url);
  assert.equal(resourceAllowed('http://localhost:3000/fonts/a.woff2',policy),true);
});
test('real bundled Chromium: no system reference, two pages, file/LIVE boundaries and restart',async()=>{
  const folder=await fs.mkdtemp(path.resolve('tmp/release-blockers-20260923/browser-'));
  const requests=[];
  const svg='<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>';
  await fs.writeFile(path.join(folder,'safe.svg'),svg);
  const sentinel=path.join(folder,'sentinel.svg');await fs.writeFile(sentinel,svg);
  const server=http.createServer((req,res)=>{
    requests.push(req.url);res.setHeader('Content-Type',req.url==='/safe.svg'?'image/svg+xml':'text/html');
    res.end(req.url==='/safe.svg'?svg:'<!doctype html><html><body><div id="ok" style="width:80px;height:80px;background:lime">中文</div></body></html>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const origin='http://localhost:'+server.address().port;
  const blocked=[];
  let browser;
  try {
    for(let generation=0;generation<2;generation++){
      browser=await openExportBrowser(executable,path.join(folder,'nonexistent-system-chrome.exe'));
      assert.equal(browser.exportFontSource,'bundled-defaults');
      await installBundleBoundary(browser,folder,event=>blocked.push(event));
      for(let i=0;i<2;i++){
        const page=await browser.newPage(pageOptions);
        await page.goto({url:origin,timeout:10000});
        const result=await page.evaluate(async({origin,file})=>{
          const load=(src)=>new Promise(resolve=>{const img=new Image();img.onload=()=>resolve(true);img.onerror=()=>resolve(false);img.src=src;});
          const outcomes=await Promise.all([load(origin+'/safe.svg'),load(origin+'/trap.svg'),load(file),load(origin+'/proxy?src=http://127.0.0.1:9/trap')]);
          const div=document.createElement('div');div.style.cssText=`width:100px;height:100px;background-image:image-set("${origin}/css-trap.svg" 1x)`;document.body.append(div);
          await new Promise(resolve=>setTimeout(resolve,150));
          return {outcomes,width:document.getElementById('ok').getBoundingClientRect().width};
        },{origin,file:pathToFileURL(sentinel).href});
        assert.deepEqual(result,{outcomes:[true,false,false,false],width:80});
        await page.close();
      }
      // LIVE uses an exact generated file, no adjacent file privileges. The
      // injected CSP also protects file loads that Chrome may not Fetch-pause.
      const target=await browser.connection.send('Target.createTarget',{url:'about:blank'});
      const live=await (await browser.waitForTarget(t=>t._targetId===target.value.targetId)).page(pageOptions);
      const file=path.join(folder,'live.html');
      await fs.writeFile(file,protectLiveHtml(`<html><head><style>.x{background-image:image-set("${origin}/live-trap" 1x)}</style></head><body><div class="x" style="height:80px">中文</div></body></html>`));
      const documentUrl=pathToFileURL(file).href;
      await installPageBoundary(live,{documentUrl},e=>blocked.push(e));
      await live.goto({url:documentUrl,timeout:10000});
      const denied=await live.evaluate(async(url)=>{try{await fetch(url);return false}catch{return true}},pathToFileURL(sentinel).href);
      assert.equal(denied,true);
      assert.equal(await live.evaluate(()=>document.compatMode),'CSS1Compat');
      await live.close();
      await browser.close({silent:true});browser=null;
    }
    assert.equal(requests.some(url=>/trap|proxy|sentinel/.test(url)),false,JSON.stringify(requests));
    assert.ok(blocked.length>=12);
    await fs.writeFile(path.join(folder,'receipt.json'),JSON.stringify({requests,blocked,restarts:2,pages:6},null,2));
  } finally {
    if(browser) await browser.close({silent:true});
    await new Promise(r=>server.close(r));
  }
});
