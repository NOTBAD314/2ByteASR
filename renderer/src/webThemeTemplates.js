// Application-owned caption motion templates, shared by the LIVE page and Remotion.
//
// An AI design picks a template and a few bounded parameters; it never ships
// code. The host expands the template's static HTML/CSS in Python
// (twobyteasr/caption_design/caption_templates.py), then webThemeMotion.js calls
// the builder here to add every movement to the cue's single paused timeline.
// Rules that keep preview and export identical:
//  - only property tweens and sets on that timeline; no callbacks (seeks
//    suppress them), no wall clock, no unseeded randomness;
//  - side effects (counters, per-frame jitter) go through a driver property
//    whose setter writes the DOM, the same way the wiggle track works;
//  - the caption characters are the host's .wt-w nodes. A template may show a
//    scramble glyph in one for a few frames; at every other time it holds the
//    real character, and cleanup restores them all.
(function (runtime) {
  const templates = runtime.__2byteTemplates || (runtime.__2byteTemplates = {});
  const F = 1 / 30;
  const rng = seed => () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  const hash = text => { let h = 2166136261; for (const c of String(text)) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const layer = (parent, cls, html) => { const e = document.createElement('div'); e.className = cls; e.setAttribute('aria-hidden', 'true'); e.innerHTML = html; parent.appendChild(e); return e; };
  // A frame-exact driver: GSAP writes `v` on every seek, the setter paints.
  const driver = (tl, start, end, paint) => {
    let value = start; const target = {};
    Object.defineProperty(target, 'v', { get: () => value, set: next => { value = next; paint(next); } });
    tl.fromTo(target, { v: start }, { v: end, duration: Math.max(F, end - start), ease: 'none', immediateRender: false }, start);
  };

  // Horizontal slice displacement plus a red/cyan channel split, as one SVG
  // filter that is attached only for the frames of an event.
  function glitchFilter(root, id) {
    const e = layer(root, 'tpl-fx', `<svg width="0" height="0" style="position:absolute"><filter id="${id}" x="-15%" y="-40%" width="130%" height="180%" color-interpolation-filters="sRGB">
      <feTurbulence class="nz" type="fractalNoise" baseFrequency="0.00001 0.045" numOctaves="1" seed="1" result="n"/>
      <feComponentTransfer in="n" result="bands"><feFuncR type="discrete" tableValues="0.5 0.5 0.15 0.5 0.85 0.5 0.5 0.3 0.5 0.7"/><feFuncG type="linear" slope="0" intercept="0.5"/></feComponentTransfer>
      <feDisplacementMap class="dm" in="SourceGraphic" in2="bands" scale="0" xChannelSelector="R" yChannelSelector="G" result="d"/>
      <feColorMatrix in="d" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r"/><feOffset class="or" in="r" dx="0" result="ro"/>
      <feColorMatrix in="d" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1 0" result="gb"/><feOffset class="ob" in="gb" dx="0" result="bo"/>
      <feBlend in="ro" in2="bo" mode="screen"/></filter></svg>`);
    e.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
    return { el: e, id, nz: e.querySelector('.nz'), dm: e.querySelector('.dm'), or: e.querySelector('.or'), ob: e.querySelector('.ob') };
  }
  function glitch(tl, fx, target, at, dur, strength, r, scale) {
    const n = Math.max(1, Math.round(dur / F));
    tl.set(target, { filter: `url(#${fx.id})` }, at);
    for (let k = 0; k < n; k++) {
      const s = strength * (1 - k / n * .5), t = at + k * F;
      tl.set(fx.dm, { attr: { scale: (r() * 2 - .3) * 120 * s * scale } }, t)
        .set(fx.nz, { attr: { seed: Math.floor(r() * 900) } }, t)
        .set(fx.or, { attr: { dx: (6 + r() * 10) * s * scale } }, t)
        .set(fx.ob, { attr: { dx: -(6 + r() * 10) * s * scale } }, t);
    }
    const end = at + n * F;
    tl.set(fx.dm, { attr: { scale: 0 } }, end).set([fx.or, fx.ob], { attr: { dx: 0 } }, end).set(target, { filter: 'none' }, end);
    return end;
  }
  function staticLayer(parent, id, cls, frequency, alphaTable) {
    const e = layer(parent, cls, `<svg width="100%" height="100%" preserveAspectRatio="none"><filter id="${id}" x="0" y="0" width="100%" height="100%"><feTurbulence class="tb" type="fractalNoise" baseFrequency="${frequency}" numOctaves="1" seed="3"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="${alphaTable}"/></feComponentTransfer></filter><rect width="100%" height="100%" filter="url(#${id})"/></svg>`);
    return { el: e, tb: e.querySelector('.tb') };
  }

  /* ------------------------------------------------------------------ vhs-signal
     A tape OSD caption: white-outlined smoked box, pixel OSD labels, red/cyan
     colour bleed, a head-switching line, tracking noise; it rolls in and
     rewinds out. */
  templates['vhs-signal'] = function ({ root, timeline: tl, params, duration: D, scale, shortCue, id }) {
    const g = root.querySelector('.vhs-g');
    if (!g) throw new Error('vhs-signal template is missing .vhs-g');
    const type = g.querySelector('.vhs-type'), box = g.querySelector('.vhs-box'), head = g.querySelector('.vhs-head');
    const osd = Array.from(g.querySelectorAll('.vhs-osd')), play = g.querySelector('.vhs-play'), tc = g.querySelector('.vhs-tc');
    const chars = Array.from(type.querySelectorAll('.wt-w'));
    const focus = new Set(Array.from(type.querySelectorAll('.wt-focus .wt-w')));
    const level = { calm: .6, normal: 1, heavy: 1.35 }[params.intensity] || 1;
    const r = rng((params.seed | 0) ^ hash(type.textContent));
    const fx = glitchFilter(root, 'vhs-gl-' + id);
    const snow = staticLayer(g, 'vhs-sn-' + id, 'vhs-snow', '1.4 .9', '1 1');
    const band = staticLayer(g, 'vhs-bd-' + id, 'vhs-band', '.9 .02', '0 .9 0');
    const cleanup = () => { fx.el.remove(); snow.el.remove(); band.el.remove(); };
    const H = g.offsetHeight, ink = getComputedStyle(type).color;
    const startCode = (params.seed | 0) % 3000;
    const clock = frame => { const s = Math.floor((startCode * 30 + frame) / 30); return `SP 0:${String(12 + Math.floor(s / 60) % 48).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
    if (shortCue) {
      // A few frames only: the settled reading pose, nothing moves.
      tl.set([box, ...osd, type, ...chars], { opacity: 1 }, 0);
      if (tc) tc.textContent = clock(0);
      return { cleanup, animationMap: [] };
    }
    const brief = D < 1.6;
    const E = Math.max(D * .55, D - (brief ? .22 : .4));
    // 0: static burst, vertical roll, wide colour bleed
    tl.set(snow.el, { opacity: 1 }, 0).set(snow.el, { opacity: .6 }, 2 * F).set(snow.el, { opacity: .25 }, 4 * F).set(snow.el, { opacity: 0 }, 6 * F);
    for (let k = 0; k < 8; k++) tl.set(snow.tb, { attr: { seed: k * 7 + 1 } }, k * F);
    const roll = brief ? [[-18, 0], [6, 2], [0, 4]] : [[-46, 0], [22, 2], [-12, 4], [6, 6], [-3, 8], [0, 10]];
    for (const [y, f] of roll) tl.set(g, { y: y * scale * level }, f * F);
    glitch(tl, fx, g, 0, brief ? 3 * F : .17, .9 * level, r, scale);
    tl.fromTo(type, { '--vhs-ca': '.25em' }, { '--vhs-ca': '.045em', duration: brief ? .3 : .6, ease: 'power3.out', immediateRender: false }, .15);
    tl.set(type, { '--vhs-ca': '.25em' }, 0);
    // letters land about one per frame, inverse block letters in dark ink
    const t0 = brief ? .1 : .22, each = Math.min(1.2 * F, (brief ? .35 : Math.max(.5, D * .3)) / Math.max(1, chars.length));
    tl.set(chars, { opacity: 0 }, 0);
    // An inverse block appears with its first letter, never empty ahead of it.
    const blocks = Array.from(type.querySelectorAll('.wt-focus'));
    tl.set(blocks, { opacity: 0 }, 0);
    blocks.forEach(b => { const first = b.querySelector('.wt-w'); const i = chars.indexOf(first); if (i >= 0) tl.set(b, { opacity: 1 }, t0 + i * each); });
    chars.forEach((c, i) => {
      const at = t0 + i * each, inv = focus.has(c);
      tl.set(c, { opacity: 1, color: inv ? '#5a5a5a' : '#ffffff' }, at).set(c, { color: inv ? '#0b0b0b' : ink }, at + 2 * F);
    });
    const typed = t0 + chars.length * each + 2 * F;
    [1, 0, 1, 0, 1].forEach((v, k) => tl.set(osd, { opacity: v }, .1 + k * F));
    tl.set(osd, { opacity: 0 }, 0);
    tl.fromTo(band.el, { y: -30 * scale, opacity: .9 }, { y: H + 4 * scale, duration: .5, ease: 'none', immediateRender: false }, .24).set(band.el, { opacity: 0 }, .74);
    tl.set(band.el, { opacity: 0 }, 0);
    // reading: PLAY blinks, the frame twitches, one more tracking band
    const H0 = Math.min(E, Math.max(typed, .9)), span = E - H0;
    for (let s = H0; s < E - .3; s += .8) tl.set(play, { opacity: .25 }, s).set(play, { opacity: 1 }, s + .4);
    [H0 + .4, H0 + 1.6, H0 + 2.6].filter(x => x < E - .2).forEach((s, i) => tl.set(g, { x: (i % 2 ? 3 : -4) * scale * level }, s).set(g, { x: 0 }, s + F * (1 + i % 2)));
    if (span > 1.6) tl.fromTo(band.el, { y: -30 * scale, opacity: .6 }, { y: H + 4 * scale, duration: .55, ease: 'none', immediateRender: false }, H0 + span * .5).set(band.el, { opacity: 0 }, H0 + span * .5 + .55);
    driver(tl, 0, D, v => {
      const f = Math.floor(v * 30);
      if (head) { head.style.transform = `translateX(${(((f * 37) % 9) - 4) * scale}px)`; head.style.opacity = f % 3 ? .6 : .25; }
      if (tc) tc.textContent = clock(f);
    });
    // rewind out
    glitch(tl, fx, g, E, brief ? 4 * F : .3, level, r, scale);
    tl.to(g, { scaleX: 1.25, scaleY: .86, duration: brief ? .14 : .22, ease: 'power2.in' }, E + .04);
    const cut = E + (brief ? .2 : .32);
    tl.set(snow.el, { opacity: .9 }, cut - .12).set(snow.el, { opacity: .5 }, cut - .12 + 2 * F);
    for (let k = 0; k < 6; k++) tl.set(snow.tb, { attr: { seed: 100 + k * 5 } }, cut - .12 + k * F);
    tl.set(g, { opacity: 0 }, cut);
    return {
      cleanup, clearAt: Math.min(D, cut + F),
      animationMap: [
        { phase: 'build', start: t0, end: typed, targets: chars.length, affects_text: true, selector: '.vhs-type .wt-w', properties: ['opacity', 'color'] },
        { phase: 'resolve', start: E, end: Math.min(D, cut + F), targets: 1, affects_text: true, selector: '.vhs-g', properties: ['filter', 'scaleX', 'scaleY', 'opacity'] },
      ],
    };
  };

  /* ------------------------------------------------------------------ hud-lock
     The round-2 B1 effects on a neutral graphite plate: white hairlines and
     corner brackets, grey micro type, one accent colour that only marks the
     locked emphasis and the REC light. Power-on flicker, block-code decode,
     target lock, screen switch-off. */
  const SCRAMBLE = '▓▒░█▚▞▙▟';
  templates['hud-lock'] = function ({ root, gsap, timeline: tl, params, duration: D, scale, shortCue, id }) {
    const g = root.querySelector('.hud-g');
    if (!g) throw new Error('hud-lock template is missing .hud-g');
    const q = s => g.querySelector(s), qa = s => Array.from(g.querySelectorAll(s));
    const type = q('.hud-type'), plate = q('.hud-plate'), cur = q('.hud-cur');
    const halves = qa('.hud-rule i'), brackets = qa('.hud-br'), head = q('.hud-head'), foot = q('.hud-foot');
    const label = q('.hud-label'), tc = q('.hud-tc'), sig = q('.hud-sig'), rec = q('.hud-rec i'), ring = q('.hud-ring');
    const cells = qa('.hud-seg i');
    const chars = Array.from(type.querySelectorAll('.wt-w'));
    const focusChars = Array.from(type.querySelectorAll('.wt-focus .wt-w'));
    const css = getComputedStyle(g), accent = css.getPropertyValue('--hud-accent').trim() || '#FFB020';
    const ink = getComputedStyle(type).color, hot = '#FFFFFF', dim = css.getPropertyValue('--hud-dim').trim() || '#6F757E';
    const level = { calm: .6, normal: 1, heavy: 1.35 }[params.intensity] || 1;
    const r = rng((params.seed | 0) ^ hash(type.textContent));
    const fx = glitchFilter(root, 'hud-gl-' + id);
    // The switch-off dot sits beside the plate (which itself collapses to nothing).
    const dot = layer(g.parentElement, 'hud-dot', '');
    dot.style.cssText = `position:absolute;left:${g.offsetLeft + g.offsetWidth / 2}px;top:${g.offsetTop + g.offsetHeight / 2}px;width:${26 * scale}px;height:${26 * scale}px;margin:${-13 * scale}px;border-radius:50%;background:#fff;box-shadow:0 0 ${26 * scale}px #fff;opacity:0`;
    // Fixed glyph widths: a scramble glyph must not move its neighbours.
    const widths = chars.map(c => c.style.width);
    chars.forEach(c => { c.style.width = getComputedStyle(c).width; c.dataset.c = c.dataset.c || c.textContent; });
    const marks = [];
    const focus = type.querySelector('.wt-focus');
    let tag = null;
    const cleanup = () => { fx.el.remove(); dot.remove(); marks.forEach(m => m.remove()); if (tag) tag.remove(); chars.forEach((c, i) => { c.style.width = widths[i]; c.textContent = c.dataset.c; }); };
    const labelText = label ? label.textContent : '';
    const startCode = ((params.seed | 0) % 3000) * 30;
    const clock = f => { const n = startCode + f, s = Math.floor(n / 30), p = v => String(v).padStart(2, '0'); return `00:${p(12 + Math.floor(s / 60) % 48)}:${p(s % 60)}:${p(n % 30)}`; };
    // emphasis lock marks, placed around the real emphasis box
    if (focus) {
      let x = 0, y = 0, n = focus;
      while (n && n !== g) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
      const w = focus.offsetWidth, h = focus.offsetHeight, pad = .12 * h, size = .22 * h;
      [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
        const m = document.createElement('div'); m.className = 'hud-mk'; m.setAttribute('aria-hidden', 'true');
        const left = sx < 0 ? x - pad : x + w + pad - size, top = sy < 0 ? y - pad * .4 : y + h + pad * .4 - size;
        m.style.cssText = `left:${left}px;top:${top}px;width:${size}px;height:${size}px;` +
          `border-${sx < 0 ? 'left' : 'right'}-width:${Math.max(2, .045 * h)}px;border-${sy < 0 ? 'top' : 'bottom'}-width:${Math.max(2, .045 * h)}px`;
        m._sx = sx; m._sy = sy; g.appendChild(m); marks.push(m);
      });
      tag = document.createElement('div'); tag.className = 'hud-tag'; tag.setAttribute('aria-hidden', 'true'); tag.textContent = 'LOCK';
      tag.style.left = (x + w + pad - 2) + 'px'; tag.style.top = (y - pad * .4) + 'px'; g.appendChild(tag);
    }
    const settled = () => {
      tl.set([plate, head, foot, ...halves, ...brackets, ...marks].filter(Boolean), { opacity: 1 }, 0);
      tl.set(chars, { opacity: 1, color: ink }, 0); tl.set(focusChars, { color: accent }, 0);
      if (tag) tl.set(tag, { opacity: 1 }, 0);
      cells.forEach(c => c.classList.add('on'));
    };
    if (shortCue) { settled(); if (tc) tc.textContent = clock(0); return { cleanup, animationMap: [] }; }
    const brief = D < 1.8;
    const E = Math.max(D * .55, D - (brief ? .26 : .42));
    // power on: frame-by-frame flicker (0.7, 0.1, 1, 0.45) and one strong tear
    tl.set([...halves, ...brackets, ring].filter(Boolean), { opacity: 0 }, 0);
    [.7, .1, 1, .45, 1].forEach((v, k) => tl.set([...halves, ring].filter(Boolean), { opacity: v }, k * F));
    glitch(tl, fx, g, 0, brief ? 3 * F : .2, level, r, scale);
    tl.fromTo(halves, { scaleX: 0 }, { scaleX: 1, duration: brief ? .18 : .32, ease: 'expo.out', stagger: .02, immediateRender: false }, .03);
    tl.set(halves, { scaleX: 0 }, 0);
    const W = g.offsetWidth, H = g.offsetHeight;
    brackets.forEach((b, i) => {
      const sx = b.classList.contains('r') ? 1 : -1, sy = b.classList.contains('b') ? 1 : -1, at = .06 + i * F;
      tl.fromTo(b, { x: -sx * W * .4, y: -sy * H * .35, scale: 1.4, opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1, duration: 8 * F, ease: 'power3.out', immediateRender: false }, at);
      if (!brief) tl.set(b, { x: sx * 12 * scale, y: sy * 8 * scale }, at + 8 * F).set(b, { x: -sx * 5 * scale, y: -sy * 3 * scale }, at + 9 * F).set(b, { x: 0, y: 0 }, at + 10 * F);
    });
    tl.fromTo(plate, { clipPath: 'inset(0% 50% 0% 50%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: brief ? .18 : .3, ease: 'power4.out', immediateRender: false }, .12);
    tl.set(plate, { clipPath: 'inset(0% 50% 0% 50%)' }, 0);
    tl.set([head, foot].filter(Boolean), { opacity: 0 }, 0).set([head, foot].filter(Boolean), { opacity: 1 }, .34);
    // micro type: the label types on at 120 characters a second, digits roll then settle
    const sigValue = sig ? sig.textContent : '';
    driver(tl, 0, D, v => {
      const f = Math.floor(v * 30);
      if (label) label.textContent = labelText.slice(0, Math.max(0, Math.floor((v - .36) * 120)));
      if (tc) tc.textContent = v < .5 ? clock(Math.floor(r() * 99999)) : clock(f);
      if (sig) sig.textContent = v < .62 && v >= .45 ? (((f * 7919) % 990) / 10).toFixed(1).padStart(4, '0') : sigValue;
      const lit = Math.floor(Math.max(0, Math.min(1, (v - .45) / Math.max(.1, E - .6))) * cells.length);
      cells.forEach((c, i) => c.classList.toggle('on', i < lit));
    });
    // the caption decodes behind a block cursor
    // Long lines decode faster: the whole line is readable within about a third of the cue.
    const T0 = brief ? .2 : .45, frames = brief ? 2 : 3;
    const step = Math.min(brief ? F : 2 * F, Math.max(.25, Math.min(.8, D * .22)) / Math.max(1, chars.length));
    const start = chars.map((_, i) => T0 + F + i * step);
    tl.set(chars, { opacity: 0, color: dim }, 0);
    chars.forEach((c, i) => tl.set(c, { opacity: 1, color: dim }, start[i]).set(c, { color: hot }, start[i] + frames * F).set(c, { color: ink }, start[i] + (frames + 2) * F));
    const glyphSeed = chars.map(() => Math.floor(r() * 997));
    driver(tl, 0, D, v => chars.forEach((c, i) => {
      const k = Math.floor((v - start[i]) / F);
      c.textContent = k >= 0 && k < frames ? SCRAMBLE[(glyphSeed[i] + k * 3) % SCRAMBLE.length] : c.dataset.c;
    }));
    if (cur) {
      const offsets = chars.map(c => { let x = 0, y = 0, n = c; while (n && n !== g) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; } return [x + c.offsetWidth + 3 * scale, y + c.offsetHeight * .12]; });
      tl.set(cur, { opacity: 0 }, 0);
      chars.forEach((c, i) => tl.set(cur, { x: offsets[i][0], y: offsets[i][1], opacity: 1 }, T0 + i * step));
    }
    const done = start[start.length - 1] + (frames + 2) * F;
    if (cur) tl.set(cur, { opacity: 0 }, done);
    // lock the emphasis in the accent colour
    if (focus) {
      tl.set(marks, { opacity: 0 }, 0);
      marks.forEach(m => tl.fromTo(m, { x: m._sx * 26 * scale, y: m._sy * 18 * scale, scale: 1.4, opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1, duration: 6 * F, ease: 'power3.out', immediateRender: false }, done));
      tl.set(focusChars, { color: accent }, done + 6 * F);
      glitch(tl, fx, g, done + 6 * F, .1, .45 * level, r, scale);
      tl.set(tag, { opacity: 0 }, 0);
      [1, 0, 1, 0, 1].forEach((v, k) => tl.set(tag, { opacity: v }, done + 7 * F + k * F));
    }
    // reading: REC blinks once a second, the ring turns, one micro tear
    const H0 = Math.min(E, done + .4), span = E - H0;
    if (ring) tl.to(ring, { rotation: 360, duration: D, ease: 'none' }, 0);
    if (rec) for (let s = 0; s < D; s += 1) tl.set(rec, { opacity: 1 }, s).set(rec, { opacity: .15 }, s + .5);
    if (span > 1.2) glitch(tl, fx, g, H0 + span * .55, 2 * F, .3 * level, r, scale);
    // exit: a stronger tear, then the screen switches off to a line and a dot
    glitch(tl, fx, g, E, brief ? 3 * F : .13, .85 * level, r, scale);
    const off = E + (brief ? .08 : .13);
    tl.to(g, { scaleY: .02, filter: 'brightness(2.6)', duration: .12, ease: 'power4.in' }, off)
      .to(g, { scaleX: 0, duration: .1, ease: 'power3.in' }, off + .12)
      .fromTo(dot, { opacity: 0, scale: 1 }, { keyframes: { opacity: [0, 1, 1, 0], scale: [1.3, 1, .6, 0] }, duration: .16, ease: 'none', immediateRender: false }, off + .18);
    const clearAt = Math.min(D, off + .36);
    return {
      cleanup, clearAt,
      animationMap: [
        { phase: 'build', start: T0, end: done, targets: chars.length, affects_text: true, selector: '.hud-type .wt-w', properties: ['opacity', 'color'] },
        { phase: 'resolve', start: E, end: clearAt, targets: 1, affects_text: true, selector: '.hud-g', properties: ['filter', 'scaleX', 'scaleY'] },
      ],
    };
  };
})(globalThis);
