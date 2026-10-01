// Real bundled Chromium + GSAP regression for seek-safe procedural motion.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {openBrowser} from '@remotion/renderer';

const out=path.resolve(process.argv[2]||'../tmp/ice-20260926/motion-runtime.json');
const runtime=await fs.readFile(path.resolve('src/webThemeMotion.js'),'utf8');
const gsap=await fs.readFile(path.resolve('node_modules/gsap/dist/gsap.min.js'),'utf8');
const browser=await openBrowser('chrome',{browserExecutable:path.resolve('node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe'),logLevel:'error'});
let result;
try{
  const page=await browser.newPage({context:null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  await page.goto({url:'data:text/html,'+encodeURIComponent('<style>.wt-scope{height:1080px}.placement{transform:translate(67px,13px)}.rig{color:white;font-size:48px}.shell{position:absolute}</style><div class="wt-scope"><div class="placement"><div class="root"><div class="rig"><span data-caption-text>文字与冰体共同轻颤</span><i class="shell"></i></div></div></div></div>'),timeout:10000});
  await page.evaluate(code=>(0,eval)(code),gsap);
  await page.evaluate(code=>(0,eval)(code),runtime);
  result=await page.evaluate(()=>{
    const root=document.querySelector('.root'),rig=root.querySelector('.rig');
    const track=(phase,from,to,other={})=>({selector:'.rig',phase,start:0,end:1,ease:'none',from,to,...other});
    const parameters={amplitudeX:1,amplitudeY:.65,rotation:.1,frequency:2.4,seed:1703,intensity:.6,fadeInMs:180,fadeOutMs:180};
    const spec={version:2,runtime:'gsap',buildMs:360,resolveMs:240,tracks:[
      track('build',{x:12,opacity:0},{x:0,opacity:1}),
      track('breathe',{x:0,y:0,rotation:0},{x:0,y:0,rotation:0},{wiggle:parameters}),
      track('resolve',{x:0,opacity:1},{x:18,opacity:0})]};
    const read=()=>({x:gsap.getProperty(rig,'x'),y:gsap.getProperty(rig,'y'),rotation:gsap.getProperty(rig,'rotation'),opacity:Number(getComputedStyle(rig).opacity),rootOpacity:Number(getComputedStyle(root).opacity),placement:getComputedStyle(root.parentElement).transform});
    const sample=time=>{__2byteSeekMotion(root,time);return read();};
    __2byteMountMotion(root,spec,6000,'wiggle-test');
    const times=[0,110,360,600,911,1300,2517,3981,5400,5759,5760,5810,5999,6000];
    const forward=Object.fromEntries(times.map(t=>[t,sample(t)]));
    const reverse=Object.fromEntries([...times].reverse().map(t=>[t,sample(t)]));
    const shuffled=Object.fromEntries([2517,110,5810,0,5400,6000,600,1300,5999,360,911,5759,3981,5760].map(t=>[t,sample(t)]));
    const direct=__timelines['wiggle-test'];direct.pause().seek(2.517,true);const directPose=read();
    const pure=__2byteSampleWiggle(2517,360,5760,parameters);
    const map=__2byteMotionMap(root);
    const sameTime=sample(2517);const sameTimeAgain=sample(2517);
    __2byteUnmountMotion(root);
    const unmounted={rigStyle:rig.getAttribute('style'),timelines:Object.keys(__timelines)};
    const off=JSON.parse(JSON.stringify(spec));off.tracks[1].wiggle.intensity=0;
    __2byteMountMotion(root,off,6000,'off');const offPose=sample(2517);__2byteUnmountMotion(root);
    const reduced=JSON.parse(JSON.stringify(spec));reduced.tracks[1].minCueMs=2000;reduced.tracks[1].durationMs=180;
    __2byteMountMotion(root,reduced,1500,'short');const reducedPose=sample(911);const reducedMap=__2byteMotionMap(root);__2byteUnmountMotion(root);
    __2byteMountMotion(root,spec,500,'ultrashort');const ultraPose=sample(200);const ultraEnd=sample(500);__2byteUnmountMotion(root);
    // A short shiver retains its real 180 ms window on a long cue.
    __2byteMountMotion(root,reduced,6000,'burst');const burstMap=__2byteMotionMap(root);const afterBurst=sample(911);__2byteUnmountMotion(root);
    // A decimal schedule boundary must restore EXACT identity, not e-42 CSS
    // transforms that send SVG-filtered material through another paint path.
    const decimalStart=3404800/1000000*1000;
    const decimalBoundary=__2byteSampleWiggle(3404.8,decimalStart,3584.8,parameters);
    return {forward,reverse,shuffled,directPose,pure,sameTime,sameTimeAgain,map,unmounted,offPose,reducedPose,reducedMap,ultraPose,ultraEnd,burstMap,afterBurst,decimalBoundary};
  });
  assert.deepEqual(result.forward,result.reverse,'reverse seek must not retain a procedural transform');
  assert.deepEqual(result.forward,result.shuffled,'random seek must equal sequential sampling');
  assert.deepEqual(result.sameTime,result.sameTimeAgain,'repeated same-time seek');
  for(const key of ['x','y','rotation'])assert.ok(Math.abs(result.directPose[key]-result.pure[key])<.001,`suppressed callbacks must not suppress ${key}`);
  assert.ok(Math.abs(result.forward[2517].x)>.01,'real text-bearing wrapper moves');
  assert.equal(result.offPose.x,0);assert.equal(result.offPose.y,0);assert.equal(result.offPose.rotation,0);
  assert.equal(result.forward[6000].rootOpacity,0);assert.equal(result.ultraEnd.rootOpacity,0);
  assert.equal(result.reducedPose.x,0);assert.equal(result.ultraPose.x,0);assert.equal(result.ultraPose.opacity,1);
  assert.ok(result.reducedMap.find(r=>r.procedural==='wiggle').omitted_for_duration);
  const burst=result.burstMap.find(r=>r.procedural==='wiggle');assert.equal(burst.end_ms-burst.start_ms,180);
  assert.equal(result.afterBurst.x,0);assert.equal(result.afterBurst.y,0);
  assert.deepEqual(result.decimalBoundary,{x:0,y:0,rotation:0});
  assert.ok(result.map.find(r=>r.procedural==='wiggle').affects_text);
  assert.equal(result.unmounted.rigStyle,'');assert.deepEqual(result.unmounted.timelines,[]);
  assert.equal(new Set(Object.values(result.forward).map(x=>x.placement)).size,1);
  result.passed=true;
}finally{await browser.close({silent:true});await fs.mkdir(path.dirname(out),{recursive:true});await fs.writeFile(out,JSON.stringify(result||{},null,2));}
console.log(JSON.stringify({passed:result.passed,evidence:out}));
