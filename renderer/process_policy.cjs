// Applied before Remotion imports: hidden owned children, loopback-only servers.
const cp = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
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
  log({phase:'start',purpose:'Renderer child / Chromium CDP',executable:command,command:[command,...args],
    child_pid:child.pid,hidden:true,stdio:opts.stdio});
  child.once('exit',(code,signal)=>log({phase:'exit',child_pid:child.pid,returncode:code,signal}));
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
