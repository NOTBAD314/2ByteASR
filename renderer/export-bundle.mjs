// Fixed render code and public assets have independent, relocatable identities.
// The fast path imports no bundler. No subtitle/job data participates here.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash, randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const hash=data=>createHash('sha256').update(data).digest('hex');
async function inventory(folder, prefix='', runtimeOnly=false) {
  const files={};
  for(const item of (await fs.readdir(folder,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))) {
    const relative=prefix+item.name, full=path.join(folder,item.name);
    if(item.isSymbolicLink()) throw new Error('Unexpected renderer asset symlink');
    if(item.isDirectory()&&(!runtimeOnly||item.name!=='node_modules'))Object.assign(files,await inventory(full,relative+'/',runtimeOnly));
    else if(item.isFile()&&(!runtimeOnly||/\.(?:m?js|cjs|json)$/.test(item.name)))files[relative]=hash(await fs.readFile(full));
  }
  return files;
}
export async function bundleIdentity() {
  const code={schema:1,node:process.versions.node,platform:process.platform,arch:process.arch,
    src:await inventory(path.join(root,'src')),files:{},dependencies:{}};
  // Build options live in this module; changing them must not reuse an older
  // compilation even if application components and dependency versions match.
  code.files['export-bundle.mjs']=hash(await fs.readFile(fileURLToPath(import.meta.url)));
  for(const name of ['package.json','package-lock.json','tsconfig.json'])code.files[name]=hash(await fs.readFile(path.join(root,name)));
  // The install lock covers transitive dependency identities; package metadata
  // also catches a local install whose top-level version differs from the lock.
  for(const name of ['.package-lock.json','@remotion/bundler/package.json','@remotion/renderer/package.json',
      'remotion/package.json','react/package.json','react-dom/package.json','gsap/package.json']) {
    try {code.dependencies[name]=hash(await fs.readFile(path.join(root,'node_modules',name)));}
    catch(error) {if(error.code!=='ENOENT')throw error;code.dependencies[name]='missing';}
  }
  for(const name of ['@remotion/bundler','@remotion/renderer','remotion','react','react-dom','gsap']) {
    try {code.dependencies[name+'/runtime']=await inventory(path.join(root,'node_modules',name),'',true);}
    catch(error) {if(error.code!=='ENOENT')throw error;}
  }
  const assets=await inventory(path.join(root,'public'));
  return {codeKey:hash(JSON.stringify(code)),assetKey:hash(JSON.stringify(assets)),assets};
}
async function verified(folder,identity) {
  try {
    const receipt=JSON.parse(await fs.readFile(path.join(folder,'bundle.json'),'utf8'));
    if(receipt.schema!==1||receipt.codeKey!==identity.codeKey||receipt.assetKey!==identity.assetKey)return false;
    if(!receipt.files['index.html']||!receipt.files['bundle.js'])return false;
    for(const [name,digest] of Object.entries(receipt.files)) {
      if(name.includes('..')||path.isAbsolute(name)||hash(await fs.readFile(path.join(folder,name)))!==digest)return false;
    }
    return true;
  } catch {return false;}
}
async function codeSource(folder,identity) {
  try {
    const receipt=JSON.parse(await fs.readFile(path.join(folder,'bundle.json'),'utf8'));
    if(receipt.schema!==1||receipt.codeKey!==identity.codeKey)return false;
    for(const [name,digest] of Object.entries(receipt.files)) {
      if(name.startsWith('public/'))continue;
      if(name.includes('..')||path.isAbsolute(name)||hash(await fs.readFile(path.join(folder,name)))!==digest)return false;
    }
    return receipt.files['index.html']&&receipt.files['bundle.js'];
  } catch {return false;}
}
const alive=pid=>{try {process.kill(Number(pid),0);return true;}catch(error){return error.code==='EPERM';}};
async function prune(cache,keep) {
  const entries=[];
  for(const name of await fs.readdir(cache)) {
    const stage=name.match(/^\.stage-(\d+)-[a-f0-9-]+$/);
    if(stage&&!alive(stage[1])) {await fs.rm(path.join(cache,name),{recursive:true,force:true}).catch(()=>{});continue;}
    if(!/^[a-f0-9]{64}$/.test(name)||name===keep)continue;
    const folder=path.join(cache,name), names=await fs.readdir(folder).catch(()=>[]);
    if(names.some(n=>n.startsWith('.lease-')&&alive(n.slice(7))))continue;
    const receipt=await fs.readFile(path.join(folder,'bundle.json'),'utf8').then(JSON.parse).catch(()=>({}));
    entries.push({folder,mtime:(await fs.stat(folder)).mtimeMs,bytes:Number(receipt.bytes)||0});
  }
  entries.sort((a,b)=>b.mtime-a.mtime);
  // Three content-addressed views; each consists of one fixed bundle plus the
  // installed public assets. Active readers are never evicted.
  const current=JSON.parse(await fs.readFile(path.join(cache,keep,'bundle.json'),'utf8'));
  let used=Number(current.bytes)||0,count=1;
  for(const item of entries) {
    used+=item.bytes;count++;
    if(count>3||used>512*1024**2)await fs.rm(item.folder,{recursive:true,force:true}).catch(()=>{});
  }
}
export async function exportBundle(emit=()=>{}, {buildTo}={}) {
  const started=performance.now(), identity=await bundleIdentity();
  const shipped=path.join(root,'prebuilt-export');
  if(!buildTo&&await verified(shipped,identity)) {
    emit('bundle_ready',{source:'shipped',hit:true,codeKey:identity.codeKey,assetKey:identity.assetKey,seconds:(performance.now()-started)/1000});
    return {serveUrl:shipped,release:async()=>{}};
  }
  if(buildTo&&path.resolve(buildTo)!==path.join(root,'prebuilt-export'))throw new Error('Invalid packaging bundle destination');
  const cache=buildTo ? path.join(root,'tmp/export-code-build')
    : path.join(process.env.LOCALAPPDATA||os.tmpdir(),'2ByteASR/SubtitleStudio/export-code-cache');
  await fs.mkdir(cache,{recursive:true});
  const key=hash(identity.codeKey+identity.assetKey), target=buildTo||path.join(cache,key);
  const lease=path.join(target,'.lease-'+process.pid);
  if(!buildTo&&await verified(target,identity)) {
    await fs.writeFile(lease,'');
    emit('bundle_ready',{source:'persistent',hit:true,codeKey:identity.codeKey,assetKey:identity.assetKey,seconds:(performance.now()-started)/1000});
    return {serveUrl:target,release:()=>fs.unlink(lease).catch(()=>{})};
  }
  if(!buildTo) {
    const names=await fs.readdir(target).catch(()=>[]);
    if(names.length&&!names.some(n=>n.startsWith('.lease-')&&alive(n.slice(7)))) {
      const invalid=path.join(cache,'.stage-'+process.pid+'-'+randomUUID());
      await fs.rename(target,invalid).catch(()=>{});
      await fs.rm(invalid,{recursive:true,force:true}).catch(()=>{});
    }
  }
  const stage=path.join(cache,'.stage-'+process.pid+'-'+randomUUID());
  await fs.mkdir(stage);
  let source='built';
  try {
    // A font/artwork update needs a new serving view, never a code rebuild.
    const candidates=[shipped,...(await fs.readdir(cache)).filter(n=>/^[a-f0-9]{64}$/.test(n)).map(n=>path.join(cache,n))];
    const reusable=await (async()=>{for(const candidate of candidates)if(await codeSource(candidate,identity))return candidate;})();
    if(reusable) {
      const receipt=JSON.parse(await fs.readFile(path.join(reusable,'bundle.json'),'utf8'));
      for(const name of Object.keys(receipt.files).filter(n=>!n.startsWith('public/'))) {
        const destination=path.join(stage,name);await fs.mkdir(path.dirname(destination),{recursive:true});
        await fs.copyFile(path.join(reusable,name),destination);
      }
      source='code-reused-assets-refreshed';
    } else {
      const {bundle}=await import('@remotion/bundler');
      emit('bundler_loaded',{seconds:(performance.now()-started)/1000});
      const empty=path.join(stage,'.empty-public');await fs.mkdir(empty);
      await bundle({entryPoint:path.join(root,'src/index.ts'),rootDir:root,outDir:stage,
        publicDir:empty,onProgress:()=>{},gitSource:null,
        webpackOverride:config=>({...config,devtool:false})});
      await fs.rm(empty,{recursive:true,force:true});
      // Headless exports never expose Studio's local project directory. Keep
      // the shipped browser bundle relocatable and free of builder home paths.
      const htmlPath=path.join(stage,'index.html'),html=await fs.readFile(htmlPath,'utf8');
      const cwd=/window\.remotion_cwd = [^\r\n]*?;<\/script>/g;
      if([...html.matchAll(cwd)].length!==1)throw new Error('Unexpected Remotion cwd metadata');
      await fs.writeFile(htmlPath,html.replace(cwd,'window.remotion_cwd = null;</script>'));
    }
    await fs.cp(path.join(root,'public'),path.join(stage,'public'),{recursive:true});
    const files=await inventory(stage);
    const bytes=(await Promise.all(Object.keys(files).map(name=>fs.stat(path.join(stage,name))))).reduce((sum,stat)=>sum+stat.size,0);
    await fs.writeFile(path.join(stage,'bundle.json'),JSON.stringify({schema:1,...identity,files,bytes}));
    if(buildTo) {
      await fs.mkdir(path.dirname(target),{recursive:true});
      await fs.rm(target,{recursive:true,force:true});
    }
    try {await fs.rename(stage,target);} catch(error) {
      // Concurrent builders may publish identical content; accept only a fully
      // verified winner. Never overwrite a serving directory beneath a reader.
      if(!await verified(target,identity))throw error;
    }
    if(!buildTo) {await fs.writeFile(lease,'');await prune(cache,key);}
    emit('bundle_ready',{source,hit:source!=='built',codeKey:identity.codeKey,assetKey:identity.assetKey,seconds:(performance.now()-started)/1000});
    return {serveUrl:target,release:()=>fs.unlink(lease).catch(()=>{})};
  } finally {await fs.rm(stage,{recursive:true,force:true}).catch(()=>{});}
}
