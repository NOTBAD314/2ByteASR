#!/usr/bin/env node
// Populate renderer/public/fonts/ from canonical assets/fonts/ before build/serve.
// Run: node populate-fonts.mjs
import {copyFile, mkdir} from 'node:fs/promises';
import {resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const src = resolve(__dirname, '../assets/fonts');
const dst = resolve(__dirname, 'public/fonts');

const fonts = [
  'Cubic11.ttf', 'SmileySans-Oblique.woff2',
  'SourceHanSansSC-Heavy.otf', 'SourceHanSansSC-Medium.otf',
  'SourceHanSansSC-Medium.woff2', 'ZCOOLKuaiLe-Regular.ttf',
  'ZCOOLQingKeHuangYou-Regular.ttf',
];

await mkdir(dst, {recursive: true});
for (const f of fonts) {
  await copyFile(`${src}/${f}`, `${dst}/${f}`);
  console.log(`Copied ${f}`);
}
console.log('Fonts populated from assets/fonts/');
