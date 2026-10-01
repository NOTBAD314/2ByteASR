// The renderer may load its own immutable bundle and embedded artwork/fonts.
// Author content never grants access to a network origin or arbitrary file.
import fs from 'node:fs/promises';
import path from 'node:path';

export const LIVE_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'";
export const protectLiveHtml = (html) => '<!doctype html><meta http-equiv="Content-Security-Policy" content="'+LIVE_CSP+'">'+String(html);

export function resourceAllowed(url, policy) {
  if (url === 'about:blank') return true;
  if (/^data:(?:image\/svg\+xml,|font\/(?:ttf|otf|truetype|opentype|woff2?);base64,)/i.test(url)) return true;
  let parsed;
  try { parsed = new URL(url); } catch { return false; }
  if (policy.documentUrl) return parsed.href.split('#')[0] === policy.documentUrl;
  if (!policy.origin || parsed.origin !== policy.origin || parsed.protocol !== 'http:') return false;
  let pathname;
  try { pathname = decodeURIComponent(parsed.pathname); } catch { return false; }
  if (pathname.startsWith('/proxy') || pathname.includes('\\') || pathname.includes('\0')) return false;
  return policy.paths?.has(pathname) === true;
}

export async function installPageBoundary(page, initial = {}, onBlocked = () => {}) {
  // Mutable per-page policy also covers subsequent LIVE document replacements.
  if (page.resourceBoundary) { page.resourceBoundary.policy = initial; return; }
  const state = {policy: initial};
  page.resourceBoundary = state;
  const client = page._client();
  client.on('Fetch.requestPaused', async (event) => {
    const allowed = resourceAllowed(event.request.url, state.policy);
    if (!allowed) onBlocked({url: event.request.url.slice(0, 512), resourceType: event.resourceType});
    try {
      await client.send(allowed ? 'Fetch.continueRequest' : 'Fetch.failRequest',
        allowed ? {requestId:event.requestId} : {requestId:event.requestId,errorReason:'BlockedByClient'});
    } catch { /* Page cancellation/close releases paused requests. */ }
  });
  await client.send('Network.enable');
  await client.send('Network.setBypassServiceWorker', {bypass: true});
  await client.send('Fetch.enable', {patterns:[{urlPattern:'*',requestStage:'Request'}]});
}

export async function installBundleBoundary(browser, bundleRoot, onBlocked) {
  const paths = new Set(['/', '/index.html']);
  async function visit(folder, prefix='') {
    for (const entry of await fs.readdir(folder, {withFileTypes:true})) {
      const relative = prefix+'/'+entry.name;
      if (entry.isDirectory()) await visit(path.join(folder,entry.name),relative);
      else if (entry.isFile()) paths.add(relative);
    }
  }
  await visit(bundleRoot);
  for (const context of browser.browserContexts()) {
    const create = context.newPage.bind(context);
    context.newPage = async (options) => {
      const page = await create(options);
      await installPageBoundary(page, {}, onBlocked);
      await page._client().send('Network.setBlockedURLs', {urls:['file://*']});
      const navigate = page.goto.bind(page);
      page.goto = async (options) => {
        // Only the trusted host navigation (not frame/script navigations) can
        // grant the exact ephemeral Remotion server origin to this page.
        const url = new URL(options.url);
        if (url.protocol !== 'http:' || url.hostname !== 'localhost' || !['/','/index.html'].includes(url.pathname)) {
          throw new Error('Renderer navigation is not a local bundle');
        }
        page.resourceBoundary.policy = {origin:url.origin, paths};
        return navigate(options);
      };
      return page;
    };
  }
}
