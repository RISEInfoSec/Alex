// Only the configured lease owner can produce a heartbeat matching the exact
// committed worker state; native scheduler evidence remains self-reported.
import writer from './github_atomic_heartbeat.cjs';

export async function writeHeartbeat({github,input,commit=writer.commitHeartbeat,now=()=>Date.now()}){
 if(!github||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['proposal'])||!input.proposal||
  typeof commit!=='function'||typeof now!=='function')throw new Error('Invalid heartbeat request');
 const result=await commit({api:github,linkId:'site',proposal:input.proposal,now});
 return {...result,native_observation_authenticated:false};
}
