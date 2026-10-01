// Real DOM ownership and remount regression for the opt-in paint layer.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {openBrowser} from '@remotion/renderer';
const input=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const code=await fs.readFile('src/webThemeMotion.js','utf8');
const gsap=await fs.readFile('node_modules/gsap/dist/gsap.min.js','utf8');
const browser=await openBrowser('chrome',{browserExecutable:path.resolve('node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'),logLevel:'error'});
const results=[];
try {
 const page=await browser.newPage({context:null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
 for(const theme of input){
  await page.goto({url:'data:text/html,'+encodeURIComponent(`<style>.wt-scope{height:1080px;width:1920px;position:relative;--wt-font:Arial;--wt-size:66px;--wt-weight:400}${theme.cueCss}</style><div class="wt-scope"><div class="root">${theme.cueHtml.replace('{{words}}','<span class="wt-w">这瓶药剂，真的能喝吗？</span>')}</div></div>`),timeout:10000});
  await page.evaluate(code=>(0,eval)(code),gsap);await page.evaluate(code=>(0,eval)(code),code);
  const result=await page.evaluate(spec=>{
   const root=document.querySelector('.root'),read=root.querySelector('.nt-read'),glyph=root.querySelector('.nt-copy');
   const original=Array.from(read.children),rows=[];
   for(const duration of [6000,2400,1500,100,6000]){
    __2byteMountMotion(root,spec,duration,'ownership');
    for(const t of [0,duration*.04,duration*.4,duration*.95,duration])__2byteSeekMotion(root,t);
    rows.push({duration,layerCount:root.querySelectorAll('[data-pixel-paint-layer]').length,semanticCount:root.querySelectorAll('[data-semantic-text]').length,sameGlyph:root.querySelector('.nt-copy')===glyph});
    __2byteUnmountMotion(root);
    if(Array.from(read.children).some((n,i)=>n!==original[i]))throw Error('original node order not restored');
    if(root.querySelector('[data-pixel-paint-layer]')||root.querySelector('filter'))throw Error('runtime layer/filter leaked');
   }
   return {rows,text:glyph.textContent,timelines:Object.keys(__timelines)};
  },theme.motionSpec);
  for(const row of result.rows){assert.equal(row.semanticCount,1);assert.equal(row.sameGlyph,true);assert.ok(row.layerCount<=1);}
  assert.deepEqual(result.timelines,[]);results.push(result);
 }
 await fs.writeFile(process.argv[3],JSON.stringify({passed:true,directions:results},null,2));
 console.log(JSON.stringify({passed:true,directions:results.length,remounts:20}));
} finally {await browser.close({silent:true});}
