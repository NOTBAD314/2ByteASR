// Take the official-site screenshots of 「申请与设置 API」 again (2026-10-18).
// usage: tools/node/node.exe scripts/capture_api_setup_shots.mjs [out-dir]   (default assets/api-setup)
//
// Only pages anyone can see without signing in (the MOSI home page with its
// daily-credit pop-up). Pages behind a login are captured by hand and their
// keys, phone numbers and balances blurred before they go into assets/.
// Loads each page in the bundled headless Chromium at 1280×800, 2×, Chinese,
// and writes 1280×800 JPEGs cropped to the parts the walkthrough shows; the
// ring positions in api_setup_catalog.Shot assume these crops, so check them
// (and the capture date there) after a site redesign.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.resolve(process.argv[2] || path.join(root, 'assets', 'api-setup'));
const {openBrowser} = await import(pathToFileURL(path.join(root, 'renderer/node_modules/@remotion/renderer/dist/esm/index.mjs')));
const shell = path.join(root, 'renderer/node_modules/.remotion/chrome-headless-shell/win64/chrome-headless-shell-win64/chrome-headless-shell.exe');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// file, page, CSS-pixel crop of the 1280×800 page (16:10). Not here: the signed-in pictures
// (mosi-2-api-keys, deepseek-2-topup, deepseek-3-api-keys, bailian-api-keys, spark-credentials),
// taken in the user's own session on 2026-10-18, and openai-1-quickstart, whose page shows this
// headless browser a bot check (taken in the app's built-in browser). Crops avoid cookie banners.
const SHOTS = [
  ['mosi-1-login.jpg', 'https://platform.mosi.cn/', {x: 520, y: 44, width: 752, height: 470}],
  ['deepseek-1-signin.jpg', 'https://platform.deepseek.com/sign_in', {x: 520, y: 180, width: 700, height: 437.5}],
  ['bailian-1-register.jpg', 'https://account.aliyun.com/register/qr_register.htm', {x: 250, y: 210, width: 780, height: 487.5}],
  ['qwencloud-1-home.jpg', 'https://home.qwencloud.com/', {x: 260, y: 0, width: 1020, height: 637.5}],
  ['qianwen-1-home.jpg', 'https://platform.qianwenai.com/home', {x: 260, y: 0, width: 1020, height: 637.5}],
  ['spark-1-quickguide.jpg', 'https://www.xfyun.cn/doc/platform/quickguide.html', {x: 290, y: 60, width: 800, height: 500}],
  ['spark-2-product.jpg', 'https://www.xfyun.cn/services/spark_asr_zh_en_v2.0', {x: 0, y: 141, width: 760, height: 475}],
  ['groq-1-login.jpg', 'https://console.groq.com/', {x: 420, y: 286, width: 680, height: 425}],
  ['claude-1-login.jpg', 'https://platform.claude.com/', {x: 260, y: 96, width: 760, height: 475}],
  ['gemini-1-google.jpg', 'https://aistudio.google.com/apikey', {x: 190, y: 110, width: 920, height: 575}],
  ['xai-1-console.jpg', 'https://console.x.ai/', {x: 0, y: 295, width: 720, height: 450}],
  ['openrouter-1-home.jpg', 'https://openrouter.ai/', {x: 220, y: 0, width: 1060, height: 662.5}],
  ['azure-1-account.jpg', 'https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account', {x: 0, y: 170, width: 760, height: 475}],
  ['azure-2-whisper.jpg', 'https://learn.microsoft.com/en-us/azure/foundry/openai/whisper-quickstart', {x: 280, y: 106, width: 990, height: 618.75}],
];

await fs.mkdir(out, {recursive: true});
const browser = await openBrowser('chrome', {browserExecutable: shell, logLevel: 'error'});
try {
  const page = await browser.newPage({context: null, logLevel: 'error', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {}});
  const client = page._client();
  await client.send('Emulation.setDeviceMetricsOverride', {width: 1280, height: 800, deviceScaleFactor: 2, mobile: false});
  await client.send('Network.enable');
  await client.send('Network.setUserAgentOverride', {
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    acceptLanguage: 'zh-CN,zh;q=0.9'});
  let loaded = '';
  for (const [file, url, crop] of SHOTS) {
    if (loaded !== url) {
      await client.send('Page.navigate', {url});
      await sleep(8000);   // client-rendered pages; MOSI's daily-credit pop-up appears after load
      loaded = url;
    }
    // 2× device pixels scaled so every picture comes out 1280 wide.
    const scale = 1280 / (crop.width * 2);
    const shot = await client.send('Page.captureScreenshot', {format: 'jpeg', quality: 88, fromSurface: true,
      clip: {...crop, scale}});
    const data = shot?.data ?? shot?.value?.data;
    if (!data) throw new Error(`no screenshot data for ${file}`);
    await fs.writeFile(path.join(out, file), Buffer.from(data, 'base64'));
    console.log('saved', path.join(out, file));
  }
} finally {
  await browser.close({silent: true}).catch(() => {});
}
