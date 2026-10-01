// Build source; pinned ag-psd 31.0.2 is bundled in third_party/cover-psd.cjs.
const fs = require('fs'), crypto = require('crypto');
const psd = require('ag-psd');
psd.initializeCanvas(() => { throw new Error('Canvas is not used'); }, (width, height) =>
  ({ width, height, data: new Uint8ClampedArray(width * height * 4) }));
const options = { useImageData: true, skipThumbnail: true };
const fingerprint = doc => {
  const hash = crypto.createHash('sha256');
  const visit = layer => {
    const {imageData, canvas, children, ...props} = layer;
    hash.update(JSON.stringify(props));
    if (imageData) hash.update(Buffer.from(imageData.data.buffer, imageData.data.byteOffset, imageData.data.byteLength));
    for (const child of children || []) visit(child);
  };
  hash.update(JSON.stringify([doc.width,doc.height]));
  for (const layer of doc.children || []) visit(layer);
  return hash.digest('hex');
};
const convert = item => {
  if (item.imageData) item.imageData.data = new Uint8ClampedArray(Buffer.from(item.imageData.data, 'base64'));
  for (const child of item.children || []) convert(child);
};
const pack = item => {
  if (item.imageData) item.imageData.data = Buffer.from(item.imageData.data.buffer).toString('base64');
  for (const child of item.children || []) pack(child);
};
const [mode, source, target] = process.argv.slice(2);
if (mode === 'write') {
  const input = JSON.parse(fs.readFileSync(source, 'utf8'));
  const archive = input.archive; delete input.archive;
  convert(input);
  const first = psd.writePsdBuffer(input, { generateThumbnail: false });
  const read = psd.readPsd(first, options);
  const metadata = Buffer.from(JSON.stringify({ version: 1, fingerprint: fingerprint(read), archive })).toString('base64');
  input.imageResources = { xmpMetadata: '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:bc="https://2byteasr.local/cover/1" bc:data="'+metadata+'"/></rdf:RDF></x:xmpmeta>' };
  fs.writeFileSync(target, psd.writePsdBuffer(input, {generateThumbnail:false}));
} else if (mode === 'meta') {
  const read = psd.readPsd(fs.readFileSync(source), {skipLayerImageData:true,skipCompositeImageData:true,skipThumbnail:true,skipLinkedFilesData:true});
  const flatten = layers => (layers || []).map(l => ({id:l.id,name:l.name,hidden:l.hidden,opacity:l.opacity,left:l.left,top:l.top,right:l.right,bottom:l.bottom,
    text:l.text,effects:l.effects,protected:l.protected,placedLayer:l.placedLayer?{transform:l.placedLayer.transform,type:l.placedLayer.type}:undefined,children:flatten(l.children)}));
  fs.writeFileSync(target,JSON.stringify({width:read.width,height:read.height,layers:flatten(read.children)}));
} else if (mode === 'read') {
  const read = psd.readPsd(fs.readFileSync(source), options);
  const result = { fingerprint: fingerprint(read), document: read };
  pack(read);
  fs.writeFileSync(target, JSON.stringify(result));
} else throw new Error('Unsupported PSD adapter mode');
