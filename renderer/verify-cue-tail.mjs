// Browser regression: responsive terminal animations must preserve their hold.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {openBrowser} from '@remotion/renderer';
const [out,legacyFile]=process.argv.slice(2);
const current=await fs.readFile(path.resolve('src/webThemeClock.js'),'utf8');
const browser=await openBrowser('chrome',{browserExecutable:path.resolve('node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'),logLevel:'error'});
const rows=[];
try {
  for(const [version,runtime] of [...(legacyFile?[['before',await fs.readFile(legacyFile,'utf8')]]:[]),['after',current]]) {
    const page=await browser.newPage({context:null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
    for(const duration of [100,300,500,1150,1500,3000,6000]) {
      await page.goto({url:'data:text/html,'+encodeURIComponent(`<style>
        .wt-cue{--wt-dur:${duration}ms;--enter:min(440ms,calc(var(--wt-dur)*.34));--tail:min(380ms,calc(var(--wt-dur)*.26));}
        .card{width:200px;height:60px;background:red;animation:wt-slam var(--enter) both,wt-retrieve var(--tail) calc(var(--wt-dur) - var(--tail)) forwards;animation-play-state:paused;}
        @keyframes wt-slam{from{opacity:0;transform:translateX(-80px)}to{opacity:1;transform:translateX(0)}}
        @keyframes wt-retrieve{from{opacity:1;transform:translateX(0)}to{opacity:0;transform:translateX(-200px)}}
        </style><div class="wt-cue"><div class="card"></div></div>`),timeout:10000});
      await page.evaluate(code=>(0,eval)(code),runtime);
      const value=await page.evaluate(async duration=>{
        const root=document.querySelector('.wt-cue');await window.__2byteDriveAnimations(root,duration*.6);
        const card=root.firstElementChild,css=getComputedStyle(card);
        return {opacity:Number(css.opacity),transform:css.transform,animations:root.getAnimations({subtree:true}).map(a=>({name:a.animationName,duration:a.effect.getTiming().duration,delay:a.effect.getTiming().delay}))};
      },duration);
      const tail=value.animations.find(a=>a.name==='wt-retrieve');
      const expectedDelay=duration-Math.min(380,duration*.26);
      const correct=Math.abs(tail.delay-expectedDelay)<.01 && value.opacity===1 && value.transform==='matrix(1, 0, 0, 1, 0, 0)';
      rows.push({version,duration,expectedDelay,correct,...value});
      if(version==='after')assert.ok(correct,JSON.stringify(rows.at(-1)));
    }
    await page.close();
  }
} finally {await browser.close({silent:true});await fs.writeFile(out,JSON.stringify(rows,null,2));}
if(legacyFile)assert.ok(rows.some(row=>row.version==='before'&&!row.correct),'legacy must reproduce the regression');
console.log(JSON.stringify({after:rows.filter(r=>r.version==='after').length,afterPassed:rows.filter(r=>r.version==='after'&&r.correct).length,beforeFailures:rows.filter(r=>r.version==='before'&&!r.correct).length}));
