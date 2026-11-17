import {build} from 'esbuild';
import {mkdirSync,readFileSync,writeFileSync,copyFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const hash=createHash('sha256');for(const name of ['checks.mjs','core.mjs','source-adapters.mjs','source-pilot.mjs','package-lock.json','data/policy.json','data/casefold.json','data/scenario.json','data/standard-fonts.json'])hash.update(name+'\0'+readFileSync(name));
mkdirSync('data',{recursive:true});writeFileSync('data/build-meta.json',JSON.stringify({implementation_hash:hash.digest('hex'),python_reference:'7e87077a0d4f13eb0b062829f9bea2d9dc25a9d0'})+'\n');
mkdirSync('dist/server',{recursive:true});mkdirSync('dist/.openai',{recursive:true});
copyFileSync('THIRD_PARTY_NOTICES.txt','dist/server/THIRD_PARTY_NOTICES.txt');
await build({entryPoints:['worker.mjs'],outfile:'dist/server/index.js',bundle:true,format:'esm',platform:'browser',target:'es2022',external:['node:*'],minify:true,legalComments:'none',define:{'process.env.NODE_ENV':'"production"'}});
try{copyFileSync('.openai/hosting.json','dist/.openai/hosting.json');}catch{}
console.log('Built the hosted core and private staging interface.');
