import {staticFile} from 'remotion';

export const cssFontStack = (family: unknown) => {
  const generic = new Set(['serif','sans-serif','monospace','cursive','fantasy','system-ui','ui-serif','ui-sans-serif','ui-monospace','ui-rounded','emoji','math','fangsong']);
  return String(family || '').split(',').map(n=>n.trim().replace(/^["']|["']$/g,''))
    .filter(Boolean).map(n=>generic.has(n.toLowerCase())?n.toLowerCase():JSON.stringify(n)).join(', ') || 'sans-serif';
};

// Trusted assets only. Model-authored CSS cannot choose an asset URL.
const faces: Record<string, [string,string]> = {
  'Cubic 11':['Cubic11.ttf','truetype'],
  'Source Han Sans SC':['SourceHanSansSC-Medium.woff2','woff2'],
  'Source Han Sans SC Heavy':['SourceHanSansSC-Heavy.otf','opentype'],
  '思源黑体 Heavy':['SourceHanSansSC-Heavy.otf','opentype'],
  'Source Han Sans SC Medium':['SourceHanSansSC-Medium.otf','opentype'],
  'Smiley Sans':['SmileySans-Oblique.woff2','woff2'],
  'ZCOOL KuaiLe':['ZCOOLKuaiLe-Regular.ttf','truetype'],
  'ZCOOL QingKe HuangYou':['ZCOOLQingKeHuangYou-Regular.ttf','truetype'],
};
export const bundledThemeFontCss = (family='') => family.split(',')
  .map(name=>name.trim().replace(/^['"]|['"]$/g,''))
  .filter(name=>Object.prototype.hasOwnProperty.call(faces,name))
  .map(name=>{
    const [file,format]=faces[name];
    return `@font-face{font-family:"${name}";src:url("${staticFile('fonts/'+file)}") format("${format}");font-weight:100 900;font-style:normal;font-display:block;}`;
  }).join('\n');
