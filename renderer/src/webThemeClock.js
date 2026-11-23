// Shared by the standalone/LIVE page and Remotion. Never edit authored CSS
// to fit a short cue: adjust the browser animation timing, deterministically.
(function (runtime) {
  // Declarative emphasis matches content, never character positions. The
  // author supplies phrases, but only the host's real cue supplies text.
  runtime.__2byteEmphasisSegments = function(text, raw) {
    const phrases=Array.from(new Set(String(raw||'').split('|').map(s=>s.trim())
      .filter(s=>s.length>0&&Array.from(s).length<=24))).slice(0,4).sort((a,b)=>b.length-a.length);
    const result=[];let start=0,index=0;
    while(index<text.length){
      const phrase=phrases.find(p=>text.startsWith(p,index));
      if(!phrase){index++;continue;}
      if(index>start)result.push({text:text.slice(start,index),focus:false});
      result.push({text:phrase,focus:true});index+=phrase.length;start=index;
    }
    if(start<text.length)result.push({text:text.slice(start),focus:false});
    return result;
  };
  function prepareEmphasis(root) {
    for(const node of root.querySelectorAll('[data-emphasis] > [data-caption-text]')){
      const fragments=runtime.__2byteEmphasisSegments(node.textContent,node.parentElement.getAttribute('data-emphasis'));
      if(!fragments.some(f=>f.focus))continue;
      if(node.children.length){
        // Move the existing host characters into semantic groups. Keep their
        // identities and text intact; motion expands from this real topology.
        if(!Array.from(node.children).every(n=>n.matches('.wt-w')))continue;
        const chars=Array.from(node.childNodes);let cursor=0;
        const grouped=document.createDocumentFragment();
        for(const part of fragments){
          const target=part.focus?document.createElement('span'):grouped;
          if(part.focus)target.className='wt-focus';
          let consumed='';
          while(cursor<chars.length&&consumed.length<part.text.length){const char=chars[cursor++];consumed+=char.textContent;target.appendChild(char);}
          if(part.focus)grouped.appendChild(target);
        }
        while(cursor<chars.length)grouped.appendChild(chars[cursor++]);
        node.replaceChildren(grouped);continue;
      }
      const fragment=document.createDocumentFragment();
      for(const part of fragments){
        const child=part.focus?document.createElement('span'):document.createTextNode(part.text);
        if(part.focus){child.className='wt-focus';child.textContent=part.text;}
        fragment.appendChild(child);
      }
      node.replaceChildren(fragment);
    }
  }
  // Per-cue marks (Markdown bold, highlight, strike, heading, colour) written by
  // the user or by AI 生动标记. The host sends ranges with the cue's own text;
  // this only groups the characters that are already there and never adds one.
  // Bold and highlight join the theme's own emphasis (.wt-focus), so every theme
  // that designed an emphasis shows them in its own language. The rules below have
  // no specificity: any rule a theme writes for these classes wins.
  const MARK_CLASSES=new Set(['wt-b','wt-i','wt-hl','wt-s','wt-h1','wt-h2','wt-h3','wt-h4','wt-h5','wt-h6']);
  const MARK_DEFAULTS=':where(.wt-mark.wt-b){font-weight:bolder}:where(.wt-mark.wt-i){font-style:italic}'
    +':where(.wt-mark.wt-h1){font-size:1.6em}:where(.wt-mark.wt-h2){font-size:1.4em}:where(.wt-mark.wt-h3){font-size:1.25em}'
    +':where(.wt-mark.wt-h4){font-size:1.12em}:where(.wt-mark.wt-h5){font-size:.9em}:where(.wt-mark.wt-h6){font-size:.78em}'
    +':where(.wt-focus-plain),:where(.wt-focus-plain .wt-w){text-decoration:underline;text-decoration-thickness:.07em;text-underline-offset:.16em}'
    +':where(.wt-focus-plain .wt-hl){box-shadow:inset 0 -.42em 0 rgba(255,221,87,.6)}'
    // A bar in the glyphs' own colour disappears into Chinese strokes.
    +':where(.wt-mark.wt-s),:where(.wt-mark.wt-s .wt-w){text-decoration:line-through;text-decoration-color:#FF4D6D;text-decoration-thickness:.09em}';
  function prepareMarks(root) {
    let touched=false;
    for(const node of root.querySelectorAll('[data-caption-text][data-cue-marks]')){
      let marks;
      try{marks=JSON.parse(node.getAttribute('data-cue-marks'));}catch(error){continue;}
      if(!Array.isArray(marks)||!marks.length)continue;
      // One leaf per character, in reading order, keeping the host's nodes.
      const leaves=[];
      const walk=(parent,focus)=>{
        for(const child of Array.from(parent.childNodes)){
          if(child.nodeType===3){for(const char of Array.from(child.textContent))leaves.push({node:document.createTextNode(char),focus});}
          else if(child.nodeType===1&&child.matches('.wt-w'))leaves.push({node:child,focus});
          else if(child.nodeType===1)walk(child,focus||child.matches('.wt-focus'));
        }
      };
      walk(node,false);
      const attrs=leaves.map(()=>null);
      for(const mark of marks){
        if(!Array.isArray(mark))continue;
        const classes=String(mark[2]||'').split(' ').filter(name=>MARK_CLASSES.has(name));
        const color=/^#[0-9a-fA-F]{6}$/.test(mark[3]||'')?mark[3]:'';
        const font=/^[\w \-぀-ヿ一-鿿]{1,60}$/.test(mark[4]||'')?mark[4]:'';
        if(!classes.length&&!color&&!font)continue;
        for(let i=Math.max(0,mark[0]|0);i<Math.min(leaves.length,mark[1]|0);i++){
          const row=attrs[i]||(attrs[i]={classes:new Set(),color:'',font:''});
          classes.forEach(name=>row.classes.add(name));
          if(color)row.color=color;
          if(font)row.font=font;
        }
      }
      if(!attrs.some(Boolean))continue;
      const names=i=>Array.from(attrs[i].classes).sort().join(' ');
      const signature=i=>attrs[i]?names(i)+'|'+attrs[i].color+'|'+attrs[i].font:'';
      const focused=i=>leaves[i].focus||Boolean(attrs[i]&&(attrs[i].classes.has('wt-b')||attrs[i].classes.has('wt-hl')));
      const rebuilt=document.createDocumentFragment();
      for(let i=0;i<leaves.length;){
        const focus=focused(i);
        const group=focus?document.createElement('span'):rebuilt;
        let j=i,themed=false;
        while(j<leaves.length&&focused(j)===focus){
          const key=signature(j);
          let target=group;
          if(key){
            target=document.createElement('span');target.className=('wt-mark '+names(j)).trim();
            if(attrs[j].color){target.style.color=attrs[j].color;target.style.webkitTextFillColor=attrs[j].color;}
            if(attrs[j].font)target.style.fontFamily=JSON.stringify(attrs[j].font);
            group.appendChild(target);
          }
          for(;j<leaves.length&&focused(j)===focus&&signature(j)===key;j++){themed=themed||leaves[j].focus;target.appendChild(leaves[j].node);}
        }
        if(focus){group.className=themed?'wt-focus':'wt-focus wt-focus-mark';rebuilt.appendChild(group);}
        i=j;
      }
      node.replaceChildren(rebuilt);node.normalize();touched=true;
    }
    if(!touched)return;
    const document_=root.ownerDocument;
    if(!document_.getElementById('wt-mark-defaults')){
      const style=document_.createElement('style');style.id='wt-mark-defaults';style.textContent=MARK_DEFAULTS;
      document_.head.appendChild(style);
    }
    // A theme without an emphasis of its own still has to show the mark.
    const shown=['color','fontSize','fontFamily','backgroundImage','backgroundColor','textShadow','webkitTextStrokeWidth',
      'webkitTextFillColor','filter','transform','borderBottomWidth','boxShadow','display','letterSpacing'];
    for(const group of root.querySelectorAll('.wt-focus-mark')){
      group.classList.remove('wt-focus-plain');
      const probe=document_.createElement('span');group.parentElement.appendChild(probe);
      const own=getComputedStyle(group),plain=getComputedStyle(probe);
      let designed=shown.some(name=>own[name]!==plain[name])
        ||getComputedStyle(group,'::before').content!=='none'||getComputedStyle(group,'::after').content!=='none';
      const letter=group.querySelector('.wt-w');
      if(!designed&&letter){
        const twin=document_.createElement('span');twin.className='wt-w';probe.appendChild(twin);
        const inside=getComputedStyle(letter),outside=getComputedStyle(twin);
        designed=['color','backgroundImage','textShadow','webkitTextFillColor'].some(name=>inside[name]!==outside[name])
          ||getComputedStyle(letter,'::after').content!=='none'||getComputedStyle(letter,'::before').content!=='none';
      }
      probe.remove();
      if(!designed)group.classList.add('wt-focus-plain');
    }
  }
  function prepareCaptionPunctuation(root) {
    // Opt in only the new host components. A closing mark stays with its
    // preceding glyph, while both original .wt-w animation targets survive.
    for(const node of root.querySelectorAll('.cap-type [data-caption-text], .cap-type .wt-focus, .cap-type .wt-mark, .bui-copy [data-caption-text], .bui-copy .wt-focus, .vhs-type [data-caption-text], .vhs-type .wt-focus, .vhs-type .wt-mark, .hud-type [data-caption-text], .hud-type .wt-focus, .hud-type .wt-mark')){
      for(const child of Array.from(node.children)){
        if(!child.matches('.wt-w')||! /^[，。！？、；：,.!?;:）】》」』”’]+$/.test(child.textContent))continue;
        const previous=child.previousSibling;
        if(!previous||previous.nodeType!==1||!previous.matches('.wt-w,.wt-focus,.wt-punctuation'))continue;
        let group=previous;
        if(!previous.matches('.wt-punctuation')){
          group=document.createElement('span');group.className='wt-punctuation';
          group.style.display='inline-block';group.style.whiteSpace='nowrap';
          node.insertBefore(group,previous);group.appendChild(previous);
        }
        group.appendChild(child);
      }
    }
  }
  const captionReady = new WeakMap();
  runtime.__2bytePrepareCaption = function(root) {
    if(!root)return Promise.resolve(null);
    const first=root.firstElementChild;
    const prior=captionReady.get(root);
    if(prior&&prior.first===first)return prior.promise;
    root.style.visibility='hidden';
    prepareEmphasis(root);
    prepareMarks(root);
    prepareCaptionPunctuation(root);
    const promise=(async()=>{
      root.getBoundingClientRect();
      // Measure authored layout, not an arbitrary entry/exit animation frame.
      // In particular, an exit's animated letter-spacing/translation must not
      // become the cached caption width when a short cue is first mounted.
      const effects=root.getAnimations({subtree:true}).map(animation=>({
        effect:animation.effect,keyframes:animation.effect.getKeyframes()}));
      for(const row of effects)row.effect.setKeyframes([]);
      try {
      const nodes=Array.from(root.querySelectorAll('[data-caption-text]'));
      const fontRequests=[...nodes,...root.querySelectorAll('.wt-focus')].map(node=>{
        const css=getComputedStyle(node);
        return document.fonts.load(`${css.fontStyle} ${css.fontWeight} ${css.fontSize} ${css.fontFamily}`,node.textContent);
      });
      // Do not measure and cache a temporary face while the real face loads.
      // The caller owns the bounded render timeout and surfaces load failures.
      await Promise.all(fontRequests);
      await document.fonts.ready;
      const loaded=true;
      if(root.firstElementChild!==first)return null;
      const scope=root.closest('.wt-scope');
      const available=(scope?.clientWidth||1920)*.94;
      const context=document.createElement('canvas').getContext('2d');
      const records=nodes.map(node=>{
        const css=getComputedStyle(node);
        const family=css.fontFamily;
        const size=parseFloat(css.fontSize)||52;
        context.font=`${css.fontStyle} ${css.fontWeight} ${size}px ${family}`;
        const spacing=parseFloat(css.letterSpacing)||0;
        const measured=Math.max(...node.textContent.split('\n').map(line=>context.measureText(line).width+Math.max(0,Array.from(line).length-1)*spacing));
        // Legacy themes may have a narrower authored text well beside a
        // mascot. Use its real layout width, not the whole video safe width.
        // A stroke layer is often a max-content grid item. Its own width
        // can exceed the authored text well, so include bounded ancestors.
        let usable=available, height=Infinity, parent=node.parentElement;
        while(parent && parent!==root){
          // Ignore shrink-to-fit widths: their pre-wrap width may have been
          // resolved using a temporary face. Only authored bounded wells
          // constrain the caption, otherwise the video safe width does.
          const typed=parent.computedStyleMap?.();
          const width=String(typed?.get('width')||'auto');
          const maxWidth=String(typed?.get('max-width')||'none');
          const parentStyle=getComputedStyle(parent);
          const authoredHeight=String(typed?.get('height')||'auto');
          const insetHeight=['absolute','fixed'].includes(parentStyle.position)
            && parentStyle.top!=='auto' && parentStyle.bottom!=='auto';
          if(parent.clientHeight>0 && (insetHeight || !['auto','max-content','min-content','fit-content'].includes(authoredHeight))){
            const resolvedHeight=parseFloat(parentStyle.height);
            const verticalInset=parentStyle.boxSizing==='border-box'
              ? ['paddingTop','paddingBottom','borderTopWidth','borderBottomWidth'].reduce((sum,key)=>sum+(parseFloat(parentStyle[key])||0),0) : 0;
            height=Math.min(height,Number.isFinite(resolvedHeight) ? resolvedHeight-verticalInset
              : parent.clientHeight-(parseFloat(parentStyle.paddingTop)||0)-(parseFloat(parentStyle.paddingBottom)||0));
          }
          if(parent.clientWidth>0 && (!['auto','max-content','min-content','fit-content'].includes(width)||maxWidth!=='none')){
            // clientWidth is integer-rounded: subtracting fractional padding
            // from it can make a two-character max-content well wrap by .02px.
            const resolvedWidth=parseFloat(parentStyle.width);
            const inset=parentStyle.boxSizing==='border-box'
              ? ['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,key)=>sum+(parseFloat(parentStyle[key])||0),0) : 0;
            const contentWidth=Number.isFinite(resolvedWidth) ? resolvedWidth-inset
              : parent.clientWidth-(parseFloat(parentStyle.paddingLeft)||0)-(parseFloat(parentStyle.paddingRight)||0);
            // Used CSS widths are rounded again at subpixel layout boundaries.
            // A subpixel allowance prevents an otherwise fitting final glyph
            // from wrapping; this never grants an extra whole glyph of width.
            usable=Math.min(usable,Math.max(1,Math.ceil(contentWidth)));
          }
          parent=parent.parentElement;
        }
        return {node,family,size,authoredSize:size,spacing,measured,usable,height,
          lineRatio:(parseFloat(css.lineHeight)||size*1.2)/size,stroke:parseFloat(css.webkitTextStrokeWidth)||0};
      });
      // A decorative copy of the same caption is a painted surface, not an
      // independent text layout. An absolute 1px shadow offset used to reduce
      // shrink-to-fit width, wrap the ghost twice, and shrink it separately.
      for(const row of records){
        if(!row.node.closest('[aria-hidden="true"]'))continue;
        row.replicaOf=records.find(main=>!main.node.closest('[aria-hidden="true"]') &&
          main.node.textContent===row.node.textContent && main.family===row.family &&
          main.authoredSize===row.authoredSize && main.spacing===row.spacing &&
          main.node.parentElement?.parentElement===row.node.parentElement?.parentElement);
      }
      for(const row of records){
        for(const [key,value] of Object.entries({whiteSpace:'pre-wrap',wordBreak:'normal',overflowWrap:'anywhere',
          display:'inline-block',maxWidth:`${row.usable}px`,boxSizing:'border-box',
          fontFamily:row.family,fontSize:`${row.size}px`,letterSpacing:`${row.spacing}px`})) row.node.style[key]=value;
        const css=getComputedStyle(row.node);
        // Chromium normally paints a centered stroke OVER the fill. On thin
        // pixel faces that erases the body. Preserve explicit paint orders
        // and transparent authored fills; make the default body readable.
        if(css.paintOrder==='normal' && css.webkitTextFillColor!=='transparent' && css.webkitTextFillColor!=='rgba(0, 0, 0, 0)')
          row.node.style.paintOrder='stroke fill';
      }
      // Only bounded authored text wells may reduce display size. Auto-height
      // captions retain the requested size and soft-wrap as before. Measure
      // layout dimensions (not animated/transformed screen bounds), once per
      // text replacement, with no mutation of source, layout or motion tracks.
      for(const row of records){
        if(row.replicaOf)continue;
        if(!Number.isFinite(row.height) || row.node.offsetHeight<=row.height+.5)continue;
        const setSize=size=>{
          const ratio=size/row.authoredSize;
          row.node.style.fontSize=`${size}px`;
          row.node.style.lineHeight=String(row.lineRatio);
          row.node.style.letterSpacing=`${row.spacing*ratio}px`;
          row.node.style.webkitTextStrokeWidth=`${row.stroke*ratio}px`;
        };
        let low=Math.min(row.size,Math.max(8,(scope?.clientHeight||1080)/1080*16)),high=row.size;
        setSize(low);
        if(row.node.offsetHeight<=row.height+.5){
          for(let i=0;i<12;i++){
            const mid=(low+high)/2;setSize(mid);
            if(row.node.offsetHeight<=row.height+.5 && row.node.scrollWidth<=row.node.clientWidth+1)low=mid;
            else high=mid;
          }
        }
        row.size=low;setSize(low);
      }
      for(const row of records){
        const main=row.replicaOf;if(!main)continue;
        const css=getComputedStyle(main.node);
        for(const property of ['fontSize','lineHeight','letterSpacing','whiteSpace','wordBreak','overflowWrap'])row.node.style[property]=css[property];
        row.node.style.width=css.width;row.node.style.maxWidth=css.width;
        row.size=main.size;row.height=main.height;
      }
      // Resolve once behind the font barrier, never during playback ticks.
      // A Range reports actual rendered line boxes, including per-word spans.
      for(const row of records){
        const range=document.createRange();range.selectNodeContents(row.node);
        row.lines=new Set(Array.from(range.getClientRects()).filter(r=>r.width>0&&r.height>0).map(r=>Math.round(r.top))).size;
        row.width=row.node.getBoundingClientRect().width;
      }
      const result={fontLoaded:loaded,lineCount:Math.max(0,...records.map(row=>row.lines)),maxWidth:available,
        // offsetHeight is integer-rounded while the authored well is fractional.
        // Use the same one-pixel rounding tolerance on both axes.
        overflow:records.some(row=>row.node.scrollWidth>row.node.clientWidth+1 || row.node.offsetHeight>row.height+1),
        fitted:records.map(row=>({fontFamily:row.family,fontSize:row.size,authoredFontSize:row.authoredSize,
          height:row.node.offsetHeight,maxHeight:Number.isFinite(row.height)?row.height:null,
          width:row.width,unwrappedWidth:row.measured,lineCount:row.lines})),locked:true};
      root.__captionLayout=result;
      root.style.visibility='';
      return result;
      } finally {
        for(const row of effects)row.effect.setKeyframes(row.keyframes);
      }
    })();
    captionReady.set(root,{first,promise});return promise;
  };
  runtime.__2byteApplyPlacement = function (host, value) {
    if (!host) return;
    const p=value || {};
    const n=(key,fallback)=>Number.isFinite(Number(p[key])) && p[key] != null ? Number(p[key]) : fallback;
    const x=n('x',.5), y=n('y',.5), ox=n('originX',.5), oy=n('originY',.5);
    const fixed={position:'absolute',inset:'0',width:'100%',height:'100%',margin:'0',padding:'0',
      animation:'none',transition:'none',background:'transparent',border:'none',
      'transform-origin':`${ox*100}% ${oy*100}%`,
      transform:`translate(${(x-ox)*100}%, ${(y-oy)*100}%) rotate(${n('rotation',0)}deg) scale(${n('scaleX',1)}, ${n('scaleY',1)})`};
    for (const [key,value] of Object.entries(fixed)) host.style.setProperty(key,value,'important');
  };
  const original = new WeakMap();
  const fitted = new WeakMap();
  runtime.__2byteFitCueAnimations = function (root, durationMs) {
    if (!root || !(durationMs > 0)) return;
    const animations = root.getAnimations({subtree: true});
    const prior = fitted.get(root);
    if (prior && prior.durationMs === durationMs && prior.animations.length === animations.length
        && prior.animations.every((animation,index)=>animation===animations[index])) return;
    fitted.set(root, {durationMs, animations});
    let entryEnd = 0, exitDuration = 0;
    const rows = animations.map(animation => {
      let timing = original.get(animation);
      if (!timing || (prior && prior.durationMs !== durationMs)) {
        timing = animation.effect.getTiming();
        const css = getComputedStyle(animation.effect.target);
        const names = css.animationName.split(',').map(s => s.trim());
        const index = Math.max(0, names.indexOf(animation.animationName));
        const milliseconds = (field) => {
          const entries = field.split(',');
          const raw = entries[index % entries.length].trim();
          return (parseFloat(raw) || 0) * (/ms$/.test(raw) ? 1 : 1000);
        };
        timing.duration = milliseconds(css.animationDuration);
        timing.delay = milliseconds(css.animationDelay);
        original.set(animation, {...timing});
      }
      const duration = Number(timing.duration) || 0;
      const finite = Number.isFinite(timing.iterations);
      // Authored responsive CSS also names terminal motions "retrieve" or
      // "grab". Their end is explicitly tied to --wt-dur. Counting these
      // delayed tails as entry makes the whole cue look overlong and moves
      // a correctly timed exit into the readable hold.
      const end = timing.delay + duration * timing.iterations;
      const alignedTail = timing.delay > 0 && Math.abs(end - durationMs) <= 2;
      const exit = finite && (alignedTail || /(?:^|-)(out|exit|retract|leave|hide)(?:-|$)/i.test(animation.animationName || ''));
      if (exit) exitDuration = Math.max(exitDuration, duration * timing.iterations);
      else if (finite) entryEnd = Math.max(entryEnd, timing.delay + duration * timing.iterations);
      return {animation, timing, duration, finite, exit};
    });
    // Preserve a readable hold even at 100/300/500ms. Normal-length themes
    // retain their original timing verbatim, including negative delays.
    const scale = durationMs <= 500
      ? Math.min(1, durationMs * .35 / Math.max(1,entryEnd), durationMs * .2 / Math.max(1,exitDuration))
      : Math.min(1, durationMs * .8 / Math.max(1, entryEnd + exitDuration));
    if (scale === 1 && !prior) return;
    for (const row of rows) {
      if (scale === 1) {
        row.animation.effect.updateTiming(row.timing);
        continue;
      }
      let delay = row.timing.delay * scale;
      if (row.exit) {
        const originalTail = Math.max(0, durationMs - row.timing.delay - row.duration*row.timing.iterations);
        delay = Math.max(0, durationMs - (row.duration*row.timing.iterations + originalTail)*scale);
      }
      row.animation.effect.updateTiming({delay,
        duration: row.finite ? row.duration*scale : row.duration});
    }
  };
  runtime.__2byteDriveAnimations = async function (root, timeMs) {
    if (!root) return 0;
    const motion=runtime.__2byteSeekMotion?.(root,timeMs);
    if(motion!=null)return motion;
    const scope=root.closest('.wt-scope');
    const rawDuration=scope ? getComputedStyle(scope).getPropertyValue('--wt-dur').trim() : '';
    const cueDuration=(parseFloat(rawDuration)||0)*(/ms$/.test(rawDuration)?1:1000);
    // The same explicit local clock drives legacy CSS and the exported page.
    // Sub-100ms cues use a stable hold; no invented per-character timings.
    const outside=cueDuration>0 && (timeMs<0 || timeMs>=cueDuration);
    root.style.visibility=outside ? 'hidden' : '';
    const sampleMs=cueDuration>0 && cueDuration<=100 ? cueDuration*.5 : timeMs;
    if(root.classList.contains('wt-cue'))root.dataset.timingFallback=cueDuration<=100 ? 'short-cue-static-hold' : 'authored';
    let timer;
    try {
      await Promise.race([
        (async()=>{
          // Token commits and retiming can replace a CSSAnimation. Wait for
          // the CURRENT objects to be paused, including replacements; their
          // pending-pause task must never overwrite the deterministic seek.
          for(let attempt=0;attempt<8;attempt++){
            const animations=root.getAnimations({subtree:true});
            for(const animation of animations)animation.pause();
            await Promise.all(animations.map(animation=>animation.ready.catch(error=>{
              if(error.name!=='AbortError')throw error;
            })));
            const current=root.getAnimations({subtree:true});
            if(current.length!==animations.length || current.some((animation,i)=>animation!==animations[i] || animation.pending))continue;
            if(root.classList.contains('wt-cue')){
              const raw=getComputedStyle(root).getPropertyValue('--wt-dur').trim();
              runtime.__2byteFitCueAnimations(root,(parseFloat(raw)||0)*(/ms$/.test(raw)?1:1000));
            }
            for(const animation of current)animation.currentTime=Math.max(0,sampleMs);
            return current.length;
          }
          throw new Error('CSS animations did not settle after retiming');
        })(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('animation pause timeout')), 1000); })
      ]);
    } finally { clearTimeout(timer); }
    const current = root.getAnimations({subtree:true});
    return current.length;
  };
})(globalThis);
