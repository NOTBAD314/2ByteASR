// Applied before Remotion imports: hidden owned children, loopback-only servers.
const cp = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const {StringDecoder} = require('node:string_decoder');
const {syncBuiltinESMExports} = require('node:module');
const log = (value) => {
  try {
    if (process.env.TWOBYTEASR_CHILD_PROCESS_LOG) fs.appendFileSync(
      process.env.TWOBYTEASR_CHILD_PROCESS_LOG, JSON.stringify({timestamp:new Date().toISOString(),
        parent_pid:process.pid, action_id:process.env.TWOBYTEASR_PROCESS_ACTION || 'web-subtitle-render', ...value})+'\n');
  } catch {}
};
const originalSpawn = cp.spawn;
cp.spawn = function(command, args, options) {
  if (!Array.isArray(args)) {options=args;args=[];}
  const opts={...options,windowsHide:true,detached:false};
  if (!opts.stdio || opts.stdio==='inherit') opts.stdio=['ignore','pipe','pipe'];
  const child=originalSpawn.call(this,command,args,opts);
  const exported=!!process.env.TWOBYTEASR_EXPORT_JOB_ID;
  const isFFmpeg=/^ffmpeg(?:\.exe)?$/i.test(path.basename(String(command)));
  const purpose=exported && isFFmpeg ? 'Renderer ffmpeg media process' : 'Renderer child / Chromium CDP';
  const exportFields=exported ? {job_id:process.env.TWOBYTEASR_EXPORT_JOB_ID,
    cwd:opts.cwd || process.cwd()} : {};
  log({phase:'start',purpose,executable:command,command:[command,...args],
    child_pid:child.pid,hidden:true,stdio:opts.stdio,...exportFields});
  // Observe text diagnostics only. Never attach a listener to binary frame stdout.
  if (exported && isFFmpeg && process.env.TWOBYTEASR_EXPORT_STDERR_ROOT) {
    const filename=path.join(process.env.TWOBYTEASR_EXPORT_STDERR_ROOT,`renderer-${child.pid}.stderr.log`);
    if (child.stderr) {
      const decoder=new StringDecoder('utf8');
      const append=(text)=>{if(text)fs.appendFileSync(filename,text);};
      child.stderr.on('data',chunk=>append(decoder.write(Buffer.isBuffer(chunk)?chunk:Buffer.from(chunk))));
      child.stderr.once('end',()=>append(decoder.end()));
      log({phase:'stderr_capture',purpose,child_pid:child.pid,stderr_log:filename,...exportFields});
    } else log({phase:'stderr_unavailable',purpose,child_pid:child.pid,...exportFields});
  }
  child.once('exit',(code,signal)=>log({phase:'exit',child_pid:child.pid,returncode:code,signal,...exportFields}));
  return child;
};
// Dependency cleanup uses exec/execFile; it must also stay hidden.
for (const name of ['exec','execFile','execSync','execFileSync','spawnSync']) {
  const original=cp[name];
  cp[name]=function(command,...args) {
    let i=args.findIndex(x=>x && typeof x==='object' && !Array.isArray(x));
    if (i<0) {i=args.findIndex(x=>typeof x==='function');if(i<0)i=args.length;args.splice(i,0,{});}
    args[i]={...args[i],windowsHide:true};
    log({phase:'launch',purpose:'Renderer '+name,executable:command,hidden:true,
      command:[command,...(Array.isArray(args[0])?args[0]:[])]});
    return original.call(this,command,...args);
  };
}
const listen=net.Server.prototype.listen;
net.Server.prototype.listen=function(...args) {
  // Pipes and explicit localhost bindings are retained. Render servers never
  // need a LAN listener (which can trigger Windows network-permission UI).
  if (typeof args[0]==='object' && args[0] && 'port' in args[0]) {
    args[0]={...args[0],host:'127.0.0.1'};
  } else if (typeof args[0]==='number') {
    if (typeof args[1]==='string')args[1]='127.0.0.1';
    else args.splice(1,0,'127.0.0.1');
  }
  log({phase:'listen',purpose:'Renderer loopback server',host:'127.0.0.1'});
  return listen.apply(this,args);
};
syncBuiltinESMExports();
