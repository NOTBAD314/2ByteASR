// The single MotionSpec compiler used by HTML, Studio LIVE and Remotion.
// GSAP owns motion; consumers supply only a cue-relative time in milliseconds.
(function(runtime){
  const mounted=new WeakMap();let serial=0;
  runtime.__timelines=runtime.__timelines||{};
  // SourceGraphic is the browser's already laid-out RGBA, including real
  // glyphs, border paint and alpha. Only the masks are generated. No DOM text
  // copies, screenshot per tick, video sampling, callbacks or second clock.
  const pixelHash=(x,y,seed)=>{let n=(Math.imul(x+11,73856093)^Math.imul(y+7,19349663)^seed)>>>0;
    n=Math.imul(n^(n>>>16),0x7feb352d);return ((n^(n>>>15))>>>0)/4294967295;};
  const clamp=v=>Math.max(0,Math.min(1,v));
  function pixelSurface(root,target,entries,scale){
    const owner=target,originalChildren=Array.from(owner.children);let layer=null,children=[];
    if(!(target instanceof HTMLElement)||!target.offsetWidth||!target.offsetHeight)throw new Error('pixels requires a visible HTML surface with layout dimensions');
    if(entries[0].pixels.surface==='panel'){
      // One temporary paint layer around the existing non-text children.
      // Original glyph DOM stays above it; no text or artwork is copied.
      children=Array.from(owner.children).filter(n=>!n.matches('[data-semantic-text="true"]'));
      layer=document.createElement('div');layer.dataset.pixelPaintLayer='panel';
      layer.style.cssText='position:absolute;inset:0;pointer-events:none';
      owner.insertBefore(layer,owner.firstChild);for(const child of children)layer.appendChild(child);
      target=layer;
    }
    if(!(target instanceof HTMLElement))throw new Error('pixels requires an HTML surface with layout dimensions');
    const width=target.offsetWidth,height=target.offsetHeight;
    if(!width||!height)throw new Error('pixels target has no visible layout size');
    const ns='http://www.w3.org/2000/svg',id=`wt-pixel-${++serial}`,pad=Math.ceil(80*scale);
    const node=(name,attrs,parent)=>{const e=document.createElementNS(ns,name);
      for(const [k,v] of Object.entries(attrs||{}))e.setAttribute(k,String(v));if(parent)parent.appendChild(e);return e;};
    const svg=node('svg',{'aria-hidden':'true',width:0,height:0},root);
    svg.style.cssText='position:absolute;width:0;height:0;pointer-events:none';
    const filter=node('filter',{id,filterUnits:'userSpaceOnUse',primitiveUnits:'userSpaceOnUse',
      x:-pad,y:-pad,width:width+2*pad,height:height+2*pad,'color-interpolation-filters':'sRGB'},svg);
    const original=target.style.filter,originalClip=target.style.clipPath;let current=null,groups=[];
    const settled=()=>{target.style.filter=original;target.style.clipPath=entries[0].pixels.clipToBounds?'inset(0% 0% 0% 0%)':originalClip;target.style.visibility='';};
    function prepare(parameters){
      filter.replaceChildren();groups=[];
      const factor={draft:1.75,standard:1.25,full:1}[parameters.quality||'full'];
      const layered=parameters.surface&&parameters.surface!=='whole';
      const cell=Math.max(2,Math.round(parameters.blockSize*scale*factor*(parameters.mode==='mineral'&&!layered?2:1)));
      const edge=parameters.clipToBounds?0:Math.ceil(6*scale),cols=Math.ceil((width+2*edge)/cell),rows=Math.ceil((height+2*edge)/cell),buckets=new Map();
      function addCell(index,px,py,w,h){
        const bucket=buckets.get(index)||{rects:[],x:0,y:0,n:0,r:pixelHash(index,71,parameters.seed)};
        bucket.rects.push(`<rect x="${px+edge}" y="${py+edge}" width="${w}" height="${h}"/>`);
        bucket.x+=px+w/2;bucket.y+=py+h/2;bucket.n++;buckets.set(index,bucket);
      }
      for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
        const r=pixelHash(x,y,parameters.seed),sx=Math.min(5,Math.floor(x/cols*6)),sy=Math.min(1,Math.floor(y/rows*2));
        const index=parameters.mode==='mineral'&&!layered?y*cols+x:layered?Math.min(4,Math.floor(x/cols*5))*4+Math.floor(r*4):(sy*6+sx)*3+Math.floor(r*3);
        const px=x*cell-edge,py=y*cell-edge,w=Math.min(cell,width+edge-px),h=Math.min(cell,height+edge-py);
        if(layered&&r<.42&&cell>=4){
          const half=cell/2,lane=Math.floor(index/4)*4;
          for(let yy=0;yy<h;yy+=half)for(let xx=0;xx<w;xx+=half){
            const rank=Math.floor(pixelHash(x*2+xx/half,y*2+yy/half,parameters.seed)*4);
            addCell(lane+rank,px+xx,py+yy,Math.min(half,w-xx),Math.min(half,h-yy));
          }
        }else addCell(index,px,py,w,h);
      }
      let i=0;
      for(const bucket of buckets.values()){
        const prefix='p'+i++,x=bucket.x/bucket.n,y=bucket.y/bucket.n;
        const mask=`<svg xmlns="${ns}" width="${width+2*edge}" height="${height+2*edge}"><g fill="white" shape-rendering="crispEdges">${bucket.rects.join('')}</g></svg>`;
        node('feImage',{href:'data:image/svg+xml,'+encodeURIComponent(mask),x:-edge,y:-edge,
          width:width+2*edge,height:height+2*edge,preserveAspectRatio:'none',result:prefix+'mask'},filter);
        node('feComposite',{in:'SourceGraphic',in2:prefix+'mask',operator:'in',result:prefix+'cut'},filter);
        const offset=node('feOffset',{in:prefix+'cut',dx:0,dy:0,result:prefix+'moved'},filter);
        const tint=node('feColorMatrix',{in:prefix+'moved',type:'matrix',result:prefix+'paint'},filter);
        groups.push({...bucket,x,y,offset,tint,result:prefix+'paint',cell});
      }
      const merge=node('feMerge',{},filter);for(const g of groups)node('feMergeNode',{in:g.result},merge);
      current=parameters;
    }
    const paint=(time)=>{
      const active=entries.find(e=>time<e.start_ms||time<=e.end_ms);
      if(!active){settled();target.style.visibility=entries.at(-1).phase==='build'?'':'hidden';return;}
      const build=active.phase==='build',parameters=active.pixels;
      // Between entrance and exit, exact original artwork and live details.
      if(!build&&time<active.start_ms){settled();return;}
      const p=clamp((time-active.start_ms)/Math.max(.001,active.end_ms-active.start_ms));
      if(build&&p>=1){settled();return;}
      if(p===0&&build||p===1&&!build){target.style.filter=original;target.style.visibility='hidden';return;}
      if(current!==parameters)prepare(parameters);
      target.style.visibility='';target.style.clipPath=originalClip;target.style.filter=`url(#${id})`;
      const strength=parameters.intensity*(active.short_cue_settled?.5:1),quant=Math.max(1,Math.round(2*scale));
      for(const g of groups){
        const anchorX=g.x<width/2?0:width,anchorY=height*.5;
        const distance=Math.hypot((g.x-anchorX)/width,(g.y-anchorY)/Math.max(height,1));
        const rank=parameters.mode==='sigil'?clamp(distance*.7+g.r*.3):parameters.mode==='mineral'?clamp(g.y/height*.45+g.r*.55):g.r;
        const delay=rank*(build?.48:.38),q=clamp((p-delay)/(1-delay));
        let dx=0,dy=0,alpha=1,tint=0,color=[1,.68,.25];
        if(parameters.surface&&parameters.surface!=='whole'){
          const role=parameters.surface,brief=active.cue_tier==='short';
          const edgeRank=clamp(Math.min(g.x,width-g.x)/Math.max(width*.3,1)*.45+Math.min(g.y,height-g.y)/Math.max(height*.5,1)*.3+g.r*.25);
          const rank=build?g.r:edgeRank;
          const local=clamp((p-rank*(build?.32:.30))/(1-rank*(build?.32:.30)));
          const rem=(1-local)**3;
          const travel=(role==='text'?6:role==='ornament'?8:14)*scale*(brief?.18:1);
          if(build){
            alpha=local>0?1:0;
            dx=(g.r-.5)*travel*rem;
            dy=travel*(parameters.mode==='mineral'?-1:1)*rem;
            if(parameters.mode==='sigil')dx=(anchorX-g.x)*.12*rem*(brief?.1:1);
          }else{
            // Support is lost at different edges before each source fragment
            // drifts away. No blanket opacity fade or reverse build path.
            const released=local<.14?0:(local-.14)/.86;
            dx=(g.r-.42)*travel*2*released;
            dy=-(travel*.8*released+travel*2*released*released);
            if(parameters.mode==='mineral')dy=travel*(released+3*released*released);
            if(parameters.mode==='sigil')dx=(anchorX-g.x)*released*released*.6;
            alpha=local<.6?1:clamp((1-local)/.4);
            tint=brief?0:Math.min(.28,released*.28);
          }
        }else if(parameters.mode==='alchemy'){
          if(build){const rem=(1-q)**2;dx=(g.r-.5)*16*scale*rem;dy=12*scale*rem;alpha=q>0?1:0;tint=q<.18?.35:0;}
          else{dx=(12+g.r*18)*scale*q*(parameters.direction||1);dy=-(14*q+26*q*q)*scale;alpha=q<.82?1:clamp((1-q)/.18);tint=q>0?(q<.3?.35:q<.65?.72:1):0;color=q<.65?[1,.71,.27]:[.76,.32,.12];}
        }else if(parameters.mode==='mineral'){
          if(build){const rem=(1-q)**2;dx=(g.r-.5)*36*scale*rem;dy=-32*scale*rem+Math.sin(q*Math.PI*2)*2*scale*(1-q);alpha=q>0?1:0;}
          else{dx=(g.r-.35)*26*scale*q;dy=(10*q+56*q*q)*scale;alpha=q<.72?1:clamp((1-q)/.28);}
        }else{
          const travel=build?(1-q)**2:q*q;
          dx=(anchorX-g.x)*travel*.72;dy=(anchorY-g.y)*travel*.72;
          alpha=build?(q>0?1:0):(q<.8?1:clamp((1-q)/.2));
          tint=(build?1-q:q)*.65;color=[.72,.81,.45];
        }
        dx=Math.round(dx*strength/quant)*quant;dy=Math.round(dy*strength/quant)*quant;
        g.offset.setAttribute('dx',dx);g.offset.setAttribute('dy',dy);
        const keep=1-tint;
        g.tint.setAttribute('values',`${keep} 0 0 0 ${color[0]*tint} 0 ${keep} 0 0 ${color[1]*tint} 0 0 ${keep} 0 ${color[2]*tint} 0 0 0 ${alpha} 0`);
      }
    };
    return {paint,destroy:()=>{target.style.filter=original;target.style.clipPath=originalClip;target.style.visibility='';svg.remove();
      if(layer){for(const child of originalChildren)owner.appendChild(child);layer.remove();}}};
  }
  // Seeded C2-continuous value noise, sampled from absolute cue time. No
  // random state, callbacks, ticker or wall clock is involved in the result.
  const smooth=t=>t*t*t*(t*(t*6-15)+10);
  const noise=(time,seed)=>{
    const hash=cell=>{let n=(cell^(seed>>>0))>>>0;n=Math.imul(n^(n>>>16),0x7feb352d);
      n=Math.imul(n^(n>>>15),0x846ca68b);return ((n^(n>>>16))>>>0)/4294967295*2-1;};
    const cell=Math.floor(time),mix=smooth(time-cell);
    return hash(cell)*(1-mix)+hash(cell+1)*mix;
  };
  runtime.__2byteSampleWiggle=function(cueTimeMs,startMs,endMs,parameters,scale=1){
    // Match the schedule's integer-microsecond domain. GSAP rounds its driver
    // property whereas seconds * 1000 can retain a ~1e-13 ms residue. Without
    // canonicalization a backwards seek before a delayed burst can write a
    // ~1e-42 transform; Chromium then composites SVG filters differently from
    // exact identity even though the geometry is visually indistinguishable.
    const cueTick=Math.floor(cueTimeMs*1000+.5),startTick=Math.floor(startMs*1000+.5),endTick=Math.floor(endMs*1000+.5);
    const elapsed=(cueTick-startTick)/1000,remaining=(endTick-cueTick)/1000;
    if(elapsed<=0||remaining<=0||!parameters.intensity)return {x:0,y:0,rotation:0};
    const envelope=smooth(parameters.fadeInMs?Math.min(1,elapsed/parameters.fadeInMs):1)*
      smooth(parameters.fadeOutMs?Math.min(1,remaining/parameters.fadeOutMs):1)*parameters.intensity;
    const time=cueTick/1000000*parameters.frequency,seed=parameters.seed;
    return {x:noise(time,seed^0x68bc21eb)*parameters.amplitudeX*scale*envelope,
      y:noise(time,seed^0x02e5be93)*parameters.amplitudeY*scale*envelope,
      rotation:noise(time,seed^0x967a889b)*parameters.rotation*envelope};
  };
  // Canonical integer microseconds; see motion_ownership.py. Adjacent phase
  // endpoints are shared integers, never independently accumulated floats.
  runtime.__2byteMotionSchedule=function(spec,durationMs){
    const readable=spec.timingProfile==='readable-pixel';
    const short=durationMs<=(readable?260:spec.version===2?700:100),ticks=ms=>Math.floor(ms*1000+.5);
    const duration=ticks(Math.max(50,short?1000:durationMs));
    let build=Math.min(ticks(spec.buildMs),Math.floor(duration*.20+.5));
    let resolve=Math.min(ticks(spec.resolveMs),Math.floor(duration*.15+.5));
    if(spec.version===2&&!short&&durationMs<1600){build=Math.min(build,ticks(160));resolve=Math.min(resolve,ticks(100));}
    const boundaries={build:[0,build],breathe:[build,duration-resolve],resolve:[duration-resolve,duration]};
    if(spec.version===2&&!short){
      const clear=Math.min(ticks(45),Math.floor(resolve*.45+.5));
      boundaries.resolve=[duration-resolve,duration-clear];
    }
    const tier=durationMs>3000?'full':durationMs>=1800?'compact':'short';
    if(readable){
      build=ticks(Math.min(spec.buildMs,tier==='full'?620:tier==='compact'?320:110,durationMs*.3));
      resolve=ticks(Math.min(spec.resolveMs,tier==='full'?500:tier==='compact'?280:110,durationMs*.25));
      const clear=Math.min(ticks(45),Math.floor(resolve*.45+.5));
      boundaries.build=[0,build];boundaries.breathe=[build,duration-resolve];boundaries.resolve=[duration-resolve,duration-clear];
    }
    return spec.tracks.map((track,index)=>{
      const [begin,finish]=boundaries[track.phase],span=finish-begin;
      const start=begin+Math.floor(track.start*span+.5);let end=begin+Math.floor(track.end*span+.5);
      const requested=track.repeat??0,yoyo=track.yoyo??false;
      if(!Number.isInteger(requested)||requested<0||requested>24||typeof yoyo!=='boolean'||(requested&&track.phase!=='breathe'))throw new Error('MotionSpec requires bounded material repetition');
      const cycle=track.durationMs;
      if(cycle!==undefined&&(!Number.isFinite(cycle)||cycle<120||cycle>30000||track.phase!=='breathe'))throw new Error('MotionSpec durationMs requires a bounded reading cadence');
      if(track.sustain!==undefined&&(typeof track.sustain!=='boolean'||spec.version!==2||track.phase!=='breathe'||cycle===undefined||requested))throw new Error('MotionSpec sustain requires v2 reading cadence without repeat');
      if(cycle!==undefined&&!track.sustain)end=Math.min(end,start+ticks(cycle)*(requested+1));
      return {track_index:index,selector:track.selector,phase:track.phase,start_tick:start,end_tick:end,
        start_ms:start/1000,end_ms:end/1000,repeat:track.sustain?Math.max(0,Math.ceil((end-start)/ticks(cycle))-1):cycle!==undefined?requested:Math.min(requested,Math.max(0,Math.floor((end-start)/120000)-1)),
        ...(cycle!==undefined?{cycle_ms:cycle}:{}),
        ...(track.sustain?{sustain:true}:{}),
        ...(track.minCueMs!==undefined?{min_cue_ms:track.minCueMs,omitted_for_duration:durationMs<track.minCueMs}:{}),
        ...(track.wiggle?{procedural:'wiggle'}:{}),
        ...(readable?{cue_tier:tier}:{}),
        requested_repeat:requested,yoyo,properties:Object.keys(track.to),source:'authored',short_cue_settled:short};
    });
  };
  runtime.__2bytePreflightMotion=function(root,spec,durationMs){
    const rows=runtime.__2byteMotionSchedule(spec,durationMs),nodes=Array.from(root.querySelectorAll('*'));
    const ownership=new Map(),issues=[],prepared=[];
    for(const row of rows){
      const targets=Array.from(root.querySelectorAll(row.selector));
      const track=spec.tracks[row.track_index];
      if(!targets.length&&spec.version===2&&track.optional)continue;
      prepared.push({...row,targets});
      if(!targets.length){issues.push({category:'motion_target',path:`motionSpec.tracks[${row.track_index}].selector`,
        track_indices:[row.track_index],selector:row.selector,actual:'selector匹配0个实际节点',duration_ms:durationMs});continue;}
      if(row.end_tick===row.start_tick)continue;
      for(const element of targets){
        const properties=ownership.get(element)||new Map();ownership.set(element,properties);
        for(const property of row.properties){
          const intervals=properties.get(property)||[];
          for(const prior of intervals)if(row.start_tick<prior.end_tick&&row.end_tick>prior.start_tick)
            issues.push({category:'motion_conflict',path:`motionSpec.tracks[${row.track_index}]`,
              track_indices:[prior.track_index,row.track_index],node:{index:nodes.indexOf(element),tag:element.tagName.toLowerCase(),classes:Array.from(element.classList).sort()},
              property,intervals:[prior,row],duration_ms:durationMs,
              actual:`节点${nodes.indexOf(element)}的${property}由tracks[${prior.track_index}]和tracks[${row.track_index}]在重叠时间写入`});
          intervals.push(row);properties.set(property,intervals);
        }
      }
    }
    if(issues.length){const error=new Error('MotionSpec preflight: '+issues.map(i=>`${i.path}: ${i.actual}`).join('; '));
      error.name='MotionOwnershipError';error.issues=issues;throw error;}
    return prepared;
  };
  runtime.__2byteUnmountMotion=function(root){
    const old=mounted.get(root);if(!old)return;
    old.context.revert();for(const surface of old.pixelSurfaces||[])surface.destroy();delete runtime.__timelines[old.id];mounted.delete(root);
  };
  runtime.__2byteMountMotion=function(root,spec,durationMs,compositionId){
    if(!root||!spec)return false;
    const signature=JSON.stringify([spec,durationMs,root.clientHeight]);
    const prior=mounted.get(root);
    if(prior&&prior.signature===signature&&prior.first===root.firstElementChild)return prior.timeline;
    runtime.__2byteUnmountMotion(root);
    if(!runtime.gsap)throw new Error('GSAP runtime is missing');
    // Validate before creating a timeline, including short-cue settled poses.
    const schedule=runtime.__2bytePreflightMotion(root,spec,durationMs);
    const duration=Math.max(.05,durationMs/1000);
    const shortCue=durationMs<=(spec.timingProfile==='readable-pixel'?260:spec.version===2?700:100);
    const exits=schedule.filter(row=>row.phase==='resolve').map(row=>row.end_ms/1000);
    const clearAt=spec.version===2&&!shortCue&&exits.length?Math.max(...exits):duration;
    const scale=(root.closest('.wt-scope')?.clientHeight||1080)/1080;
    const id=compositionId||root.dataset.compositionId||`2byte-cue-${++serial}`;
    if(!compositionId)root.dataset.compositionId=id;
    root.dataset.duration=String(duration);
    const initial=new Map();const prepared=[];const animationMap=[];const pixelSurfaces=[];let timeline;
    if(!shortCue){
      const pixelTargets=new Map();
      for(const row of schedule){
        const pixels=spec.tracks[row.track_index].pixels;if(!pixels)continue;
        for(const target of row.targets){const entries=pixelTargets.get(target)||[];entries.push({...row,pixels});pixelTargets.set(target,entries);}
      }
      for(const [target,entries] of pixelTargets)pixelSurfaces.push(pixelSurface(root,target,entries.sort((a,b)=>a.start_ms-b.start_ms),scale));
    }
    const context=runtime.gsap.context(()=>{},root);
    try{context.add(()=>{
      timeline=runtime.gsap.timeline({paused:true});
      timeline.set(root,{opacity:1},0);
      if(shortCue){
        // Below a few display frames, preserve the author's settled reading
        // pose for the entire cue. Never extend it or borrow the previous cue.
        const poses=new Map();
        for(const phase of ['build','breathe','resolve'])for(const track of spec.tracks){
          if(track.phase!==phase)continue;
          const targets=Array.from(root.querySelectorAll(track.selector));
          if(!targets.length&&spec.version===2&&track.optional)continue;
          if(!targets.length)throw new Error(`MotionSpec selector has no target: ${track.selector}`);
          for(const target of targets){
            const pose=poses.get(target)||{};
            if(track.pixels?.clipToBounds)pose.clipPath='inset(0% 0% 0% 0%)';
            for(const [property,value] of Object.entries(phase==='build'?track.to:track.from)){
              if(phase==='build'||!(property in pose))pose[property]=
                ['x','y','backgroundPositionX','backgroundPositionY'].includes(property)?value*scale:value;
            }
            poses.set(target,pose);
          }
        }
        for(const [target,pose] of poses)timeline.set(target,{...pose,...(spec.version===2?{force3D:false}:{})},0);
        timeline.set(root,{opacity:0},duration);
        return;
      }
      for(const row of schedule){
        const track=spec.tracks[row.track_index],targets=row.targets;
        if(track.pixels){
          const explicit=root.querySelector('[data-semantic-text="true"]');
          const textNodes=Array.from(root.querySelectorAll('[data-caption-text]')).filter(n=>
            !n.closest('[aria-hidden="true"]')&&(!explicit||n.closest('[data-semantic-text="true"]')));
          animationMap.push({...row,start:row.start_ms/1000,end:row.end_ms/1000,targets:targets.length,
            affects_text:targets.some(e=>textNodes.some(n=>e.contains(n)||n.contains(e))),procedural:'source_pixels',mode:track.pixels.mode});continue;
        }
        const start=row.start_tick/1000000,end=row.end_tick/1000000;
        const from={...track.from},to={...track.to};
        for(const state of [from,to])for(const p of ['x','y','backgroundPositionX','backgroundPositionY'])if(p in state)state[p]*=scale;
        const {repeat,yoyo}=row;
        for(const element of targets){
          for(const property of Object.keys(to)){
            const first=initial.get(element)||new Map();initial.set(element,first);
            if(!first.has(property)||start<first.get(property).start)first.set(property,{start,value:from[property]});
          }
        }
        const stagger=spec.version===2?track.stagger:null;
        if(row.omitted_for_duration){
          prepared.push({targets,settled:track.phase==='build'?to:from});
        }else if(stagger&&targets.length>1){
          const groups=Math.ceil(targets.length/stagger.groupSize);
          const ranks=Array.from({length:groups},(_,i)=>i);
          if(stagger.order==='reverse')ranks.reverse();
          if(stagger.order==='center')ranks.sort((a,b)=>Math.abs(a-(groups-1)/2)-Math.abs(b-(groups-1)/2)||a-b);
          // Total offset is capped, regardless of actual text length. No audio timestamps are inferred.
          const window=Math.min(stagger.amountMs/1000,(end-start)*.4);
          targets.forEach((target,index)=>{
            const rank=ranks.indexOf(Math.floor(index/stagger.groupSize));
            const offset=groups>1?window*rank/(groups-1):0;
            prepared.push({targets:[target],from,to,start:start+offset,end:end-window+offset,ease:track.ease,repeat,yoyo});
          });
        }else prepared.push({targets,from,to,start,end,ease:track.ease,repeat,yoyo,cycleMs:row.cycle_ms,
          wiggle:track.wiggle});
        const explicit=root.querySelector('[data-semantic-text="true"]');
        const textNodes=Array.from(root.querySelectorAll('[data-caption-text]')).filter(n=>
          !n.closest('[aria-hidden="true"]')&&(!explicit||n.closest('[data-semantic-text="true"]')));
        const affectsText=targets.some(e=>textNodes.some(n=>e.contains(n)||n.contains(e)));
        animationMap.push({...row,start,end,targets:targets.length,affects_text:affectsText});
      }
      // A delayed entrance must already be in its FROM pose before it starts.
      // Otherwise GSAP restores the static hero on a backwards seek, then
      // jumps to the entry pose at the delayed start.
      for(const [element,properties] of initial)timeline.set(element,{...Object.fromEntries(
        Array.from(properties,([property,value])=>[property,value.value])),...(spec.version===2?{force3D:false}:{})},0);
      for(const item of prepared){
        if(item.settled){
          // Omit secondary events instead of accelerating a long performance.
          // The author supplies a reading pose through build.to / other.from.
          timeline.set(item.targets,{...item.settled,force3D:false},0);
        }
        else if(item.wiggle){
          const setters=item.targets.map(target=>({x:runtime.gsap.quickSetter(target,'x','px'),
            y:runtime.gsap.quickSetter(target,'y','px'),rotation:runtime.gsap.quickSetter(target,'rotation','deg')}));
          let cueMs=item.start*1000;
          const driver={};Object.defineProperty(driver,'cueMs',{get:()=>cueMs,set:value=>{
            cueMs=value;const pose=runtime.__2byteSampleWiggle(value,item.start*1000,item.end*1000,item.wiggle,scale);
            for(const setter of setters){setter.x(pose.x);setter.y(pose.y);setter.rotation(pose.rotation);}
          }});
          // GSAP writes properties even for seek(t,true), which suppresses
          // event callbacks. The existing timeline owns this driver and its
          // teardown, including when HyperFrames seeks __timelines directly.
          timeline.fromTo(driver,{cueMs:item.start*1000},{cueMs:item.end*1000,
            duration:item.end-item.start,ease:'none',immediateRender:false},item.start);
        }
        else if(item.start===item.end)timeline.set(item.targets,{...item.to,...(spec.version===2?{force3D:false}:{})},item.start);
        else if(item.cycleMs!==undefined){
          // A paused child retains real-time speed. The parent seeks only the
          // available prefix, so short cues omit later events instead of
          // accelerating an entire repeated material motion into the hold.
          const material=runtime.gsap.timeline({paused:true}).fromTo(item.targets,item.from,{...item.to,...(spec.version===2?{force3D:false}:{}),
            duration:item.cycleMs/1000,repeat:item.repeat,yoyo:item.yoyo,ease:item.ease,immediateRender:false});
          timeline.fromTo(material,{time:0},{time:item.end-item.start,duration:item.end-item.start,
            ease:'none',immediateRender:false},item.start);
        }
        else timeline.fromTo(item.targets,{...item.from},{...item.to,...(spec.version===2?{force3D:false}:{}),
          duration:(item.end-item.start)/(item.repeat+1),repeat:item.repeat,yoyo:item.yoyo,
          ease:item.ease,immediateRender:false},item.start);
      }
      timeline.set(root,{opacity:0},clearAt);
      if(pixelSurfaces.length){
        let cueMs=0;const driver={};Object.defineProperty(driver,'cueMs',{get:()=>cueMs,set:value=>{
          cueMs=value;for(const surface of pixelSurfaces)surface.paint(value);
        }});
        timeline.fromTo(driver,{cueMs:0},{cueMs:duration*1000,duration,ease:'none',immediateRender:false},0);
      }
    });}catch(error){context.revert();for(const surface of pixelSurfaces)surface.destroy();throw error;}
    // Rewind through the canonical initial pose. A backwards seek from a
    // partially transformed clip can otherwise retain Chromium's rasterized
    // clip edge even though computed transforms report the correct values.
    // Wrap the registered timeline as well, so direct consumers share this.
    const rawSeek=timeline.seek.bind(timeline);
    timeline.seek=function(position,suppressEvents){
      if(typeof position==='number'&&position>=0&&position<timeline.time()){
        rawSeek(0,true);
        const display=root.style.display;root.style.display='none';void root.offsetHeight;root.style.display=display;
      }
      return rawSeek(position,suppressEvents);
    };
    const state={signature,id,context,timeline,first:root.firstElementChild,duration,clearAt,animationMap,pixelSurfaces};
    mounted.set(root,state);runtime.__timelines[id]=timeline;
    // Initialize every fromTo before the first exact-zero seek. GSAP defers
    // immediateRender:false tweens until they are visited; without this a
    // newly mounted t=0 differs from a backwards seek to t=0.
    timeline.pause().seek(duration,true).seek(0,true);return timeline;
  };
  runtime.__2byteSeekMotion=function(root,timeMs){
    const state=mounted.get(root);if(!state)return null;
    state.timeline.pause().seek(Math.max(0,Math.min(state.duration,timeMs/1000)),true);
    // Explicit boundaries also work when a consumer seeks backwards from EOF.
    root.style.opacity=timeMs<0||timeMs>=state.clearAt*1000?'0':'1';
    return state.animationMap.length;
  };
  runtime.__2byteMotionMap=function(root){return mounted.get(root)?.animationMap||[];};
})(globalThis);
