// Preserve the installed Chromium's generic font choices in Headless Shell.
// A fresh Chinese Chrome uses NSimSun for monospace; Shell defaults to Courier.
// Read a synthetic page, never a user browser profile or authored theme text.
import {openBrowser} from '@remotion/renderer';
import fs from 'node:fs/promises';
import path from 'node:path';

export async function existingExecutable(executable) {
  if (!executable) return false;
  try { return (await fs.stat(executable)).isFile(); } catch { return false; }
}

export async function localBrowserExecutable(root, configured) {
  const tag=process.platform === 'win32' ? 'win64' : process.platform === 'darwin'
    ? (process.arch === 'arm64' ? 'mac-arm64' : 'mac-x64')
    : (process.arch === 'arm64' ? 'linux-arm64' : 'linux64');
  const executable=tag === 'win64' ? 'chrome-headless-shell.exe' : tag === 'linux-arm64' ? 'headless_shell' : 'chrome-headless-shell';
  const bundled=path.join(root,'node_modules/.remotion/chrome-headless-shell',tag,'chrome-headless-shell-'+tag,executable);
  const system=process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    : process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/chromium';
  for (const candidate of [configured, bundled, system]) {
    if (await existingExecutable(candidate)) return path.resolve(candidate);
  }
  throw new Error('Local renderer browser is missing; repair the bundled Chromium installation (automatic download is disabled).');
}

export async function openExportBrowser(executable, referenceExecutable) {
  if (!await existingExecutable(executable)) throw new Error('Local renderer browser is missing: '+executable);
  let reference;
  let referencePage;
  let fontFamilies;
  let fontSource='bundled-defaults';
  if (referenceExecutable !== executable && await existingExecutable(referenceExecutable)) try {
    reference=await openBrowser('chrome',{browserExecutable:referenceExecutable,logLevel:'error'});
    const page=await reference.newPage({context:null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
    referencePage=page;
    const client=page._client();
    await client.send('DOM.enable');await client.send('CSS.enable');
    const families={standard:'initial',fixed:'monospace',serif:'serif',sansSerif:'sans-serif',cursive:'cursive',fantasy:'fantasy'};
    await page.evaluate((entries)=>{document.documentElement.lang='zh-CN';document.body.innerHTML='';for(const [id,family] of Object.entries(entries)){const p=document.createElement('p');p.id=id;p.style.fontFamily=family;p.textContent='Abc012';document.body.append(p);}},families);
    // An about:blank reference tab may not receive animation frames until a
    // screenshot activates its compositor. Font readiness plus the capture
    // below is sufficient; waiting for rAF here can leave a timed-out CDP job.
    await page.evaluate(async()=>{document.body.getBoundingClientRect();await document.fonts.ready;});
    await client.send('Page.captureScreenshot',{format:'png'});
    const documentNode=(await client.send('DOM.getDocument')).value.root.nodeId;
    fontFamilies={};
    for(const key of Object.keys(families)){
      const nodeId=(await client.send('DOM.querySelector',{nodeId:documentNode,selector:'#'+key})).value.nodeId;
      const fonts=(await client.send('CSS.getPlatformFontsForNode',{nodeId})).value.fonts;
      const selected=fonts.sort((a,b)=>b.glyphCount-a.glyphCount)[0];
      if(!selected?.familyName)throw new Error('Cannot resolve reference generic font: '+key);
      fontFamilies[key]=selected.familyName;
    }
    fontSource='installed-reference';
  } catch {
    fontFamilies=undefined;
  } finally {
    if(referencePage) await referencePage.close().catch(()=>{});
    if(reference) await reference.close({silent:true}).catch(()=>{});
  }
  const browser=await openBrowser('chrome',{browserExecutable:executable,logLevel:'error'});
  // Remotion's public page factory is invoked once per worker. CDP preferences
  // are installed before navigation, without rewriting any authored font stack.
  for(const context of browser.browserContexts()){
    const create=context.newPage.bind(context);
    context.newPage=async(options)=>{
      const page=await create(options);
      if(fontFamilies) await page._client().send('Page.setFontFamilies',{fontFamilies,forScripts:[{script:'Hans',fontFamilies},{script:'Latn',fontFamilies}]});
      return page;
    };
  }
  browser.exportFontFamilies=fontFamilies;
  browser.exportFontSource=fontSource;
  browser.exportExecutable=executable;
  return browser;
}
