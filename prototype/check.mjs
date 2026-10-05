import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const root=path.dirname(fileURLToPath(import.meta.url));
const modules=fs.readdirSync(root).filter(name=>name.endsWith('.mjs'));
for(const file of modules){
 const result=spawnSync(process.execPath,['--check',path.join(root,file)],{encoding:'utf8'});
 if(result.status!==0)throw new Error(`${file}: ${result.stderr}`);
}
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const assets=[...html.matchAll(/(?:src|href)="([^"#]+)"/g)].map(match=>match[1]);
for(const asset of assets)if(!fs.existsSync(path.resolve(root,asset)))throw new Error(`Missing asset: ${asset}`);
console.log(`Validated ${modules.length} JavaScript modules and ${assets.length} entry assets. No build step or external CDN required.`);
