// The route constructs the GitHub adapter from the Site's existing secret.
// The scheduler observation in the proposal is self-reported, not a signed
// native observation; this service never claims native completion.
import leaseWriter from './github_atomic_lease.cjs';
import {inspectFence} from './d1_fence_status.mjs';

export async function startLease({db,github,input,inspect=inspectFence,commit=leaseWriter.commitLease,now=()=>Date.now()}){
 if(!db||!github||!input||typeof input!=='object'||Array.isArray(input)||
  JSON.stringify(Object.keys(input).sort())!==JSON.stringify(['owner','proposal','runId'])||
  typeof input.owner!=='string'||!/^[a-zA-Z0-9-]{1,100}$/.test(input.owner)||
  typeof input.runId!=='string'||!/^[a-zA-Z0-9-]{1,100}$/.test(input.runId)||
  !input.proposal||input.proposal.phase!=='start'||typeof inspect!=='function'||typeof commit!=='function')
  throw new Error('Invalid lease start request');
 if((await inspect(db)).status!=='idle')throw new Error('Decision fence is not idle');
 const result=await commit({api:github,linkId:'site',proposal:input.proposal,owner:input.owner,runId:input.runId,now});
 return {...result,native_observation_authenticated:false};
}
