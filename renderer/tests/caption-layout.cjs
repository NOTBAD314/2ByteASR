/* Render the actual component: a newline is a break even in letter effects. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.tsx'] = (module, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020},
    fileName: filename,
  });
  module._compile(result.outputText, filename);
};
require.extensions['.ts'] = require.extensions['.tsx'];
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const {TrustedSubtitle} = require('../src/components/TrustedSubtitle.tsx');

const recipe = {
  typography: {fontFamily: 'sans-serif', fontSize: 80, bold: false, italic: false, spacing: 0},
  fill: {type: 'solid', color: '#fff'}, strokes: [], glow: {blur: 0},
  shadow: {enabled: false}, decorations: [],
  layout: {playResX: 1920, playResY: 1080, fitLocked: true, maxWidthPx: 1600, lineHeightPx: 100},
  motion: {mode: 'explicit', entrance: {type: 'letter_stagger', duration_ms: 300}},
};
const render = (text, override = {}) => renderToStaticMarkup(React.createElement(TrustedSubtitle, {
  text, recipe: {...recipe, ...override}, frame: 30, durationFrames: 90, fps: 30,
}));

for (const text of ['甲乙\n丙丁', 'First line\n\nLast line', '第一行\nEnglish second line\n第三行']) {
  const html = render(text);
  assert.equal((html.match(/<br\/>/g) || []).length, text.split('\n').length - 1);
  assert.match(html, /white-space:pre;/);
  assert.match(html, /line-height:100px/);
  assert.match(html, /max-width:1600px/);
  const visible = html.replace(/<br\/>/g, '\n').replace(/<[^>]*>/g, '');
  assert.equal(visible, text);
}
const bounce = render('一\n二', {motion: {mode: 'explicit', hold: {type: 'per_letter_bounce'}}});
assert.equal((bounce.match(/<br\/>/g) || []).length, 1);
const manual = render('第一行\n第二行', {motion: {mode: 'none'}});
assert.ok(manual.includes('第一行\n第二行'));
const emphasized = render('甲乙\n丙丁', {wordAnimation: {marks: [{start: 1, end: 4, bold: true, highlight: true}]}});
assert.equal((emphasized.match(/<br\/>/g) || []).length, 1);
assert.match(emphasized, /font-weight:700/);
assert.match(emphasized, /color:#FFD166/);
const staticEmphasis = render('甲乙\n丙丁', {motion: {mode: 'none'}, wordAnimation: {marks: [{start: 1, end: 4, bold: true}]}});
assert.match(staticEmphasis, /font-weight:700/);
const {captionInkAnchor} = require('../src/components/captionInkAnchor.ts');
let measurements = 0;
global.document = {fonts: {check: () => true}, createElement: () => ({getContext: () => ({
  measureText: text => { measurements++; return {width: text.length*10, actualBoundingBoxLeft: 0,
    actualBoundingBoxRight: Math.max(0,text.length*10-10), actualBoundingBoxAscent: 8,
    actualBoundingBoxDescent: 0, fontBoundingBoxAscent: 8, fontBoundingBoxDescent: 2}; },
})})};
const measured = {text:'AB\nC',family:'fixture',size:10,weight:400,italic:false,spacing:0,lineHeight:10,anchorX:.5,anchorY:1};
assert.deepEqual(captionInkAnchor(measured), {x:5,y:2});
const firstCount = measurements;
for (let frame=0;frame<100;frame++) captionInkAnchor(measured);
assert.equal(measurements, firstCount, 'animation frames must reuse measured glyph metrics');
for (let i=0;i<513;i++) captionInkAnchor({...measured,text:`Case ${i}`});
const beforeRevisit = measurements;
captionInkAnchor(measured);
assert.ok(measurements > beforeRevisit, 'the oldest layout must leave the bounded cache');
console.log(JSON.stringify({passed: true, checks: 24, component: 'TrustedSubtitle and ink-anchor cache'}));
