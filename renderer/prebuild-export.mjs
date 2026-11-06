// Invoked by packaging, or explicitly by a source developer. No browser/job.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {exportBundle} from './export-bundle.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const result=await exportBundle((type,data)=>process.stdout.write(JSON.stringify({type,...data})+'\n'),
  {buildTo:path.join(root,'prebuilt-export')});
await result.release();
