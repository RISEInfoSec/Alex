import test from 'node:test';
import assert from 'node:assert/strict';
import {findLinearAncestor} from '../tools/content_review/site_linear_history.mjs';

const sha=n=>n.toString(16).padStart(40,'0'),tree='a'.repeat(40);
const chain=n=>Array.from({length:n},(_,i)=>({sha:sha(n-i),tree_sha:tree,parents:[sha(n-i-1)]}));
const ok=value=>({isError:false,structuredContent:value});
function fixture(length=125){
 const commits=chain(length);let calls=0,pulses=0;
 const github={fetchCommitHistoryPage:async({head,cursor})=>{
  assert.equal(head,commits[0].sha);calls++;const offset=cursor===null?0:Number(cursor);
  const page=commits.slice(offset,offset+50),next=offset+page.length<commits.length;
  return ok({commits:page,has_next:next,end_cursor:next?String(offset+50):null});}};
 return {commits,github,heartbeat:async()=>{pulses++},details:async()=>{throw Error('unexpected sequential fetch')},
  calls:()=>calls,pulses:()=>pulses};
}
test('locates old reservations through verified parent-linked pages',async()=>{
 const f=fixture(),ancestor=f.commits[114];
 const result=await findLinearAncestor({...f,head:f.commits[0].sha,ancestor:ancestor.sha});
 assert.deepEqual(result,ancestor);assert.equal(f.calls(),3);assert.equal(f.pulses(),3);
});
test('rejects rewritten links, merges, gaps and truncated pages',async()=>{
 for(const mode of ['wrong-head','gap','merge','truncated','repeat-cursor']){
  const f=fixture();const base=f.github.fetchCommitHistoryPage;
  f.github.fetchCommitHistoryPage=async args=>{const response=await base(args),page=response.structuredContent;
   if(mode==='wrong-head')page.commits[0]={...page.commits[0],sha:sha(900)};
   if(mode==='gap')page.commits[4]={...page.commits[4],parents:[sha(900)]};
   if(mode==='merge')page.commits[4]={...page.commits[4],parents:[page.commits[4].parents[0],sha(900)]};
   if(mode==='truncated'){page.has_next=false;page.end_cursor=null;}
   if(mode==='repeat-cursor'&&args.cursor!==null)page.end_cursor=args.cursor;
   return response;};
  await assert.rejects(findLinearAncestor({...f,head:f.commits[0].sha,ancestor:f.commits[114].sha}),undefined,mode);
 }
});
test('legacy adapters use the same strict linear checks with a bounded walk',async()=>{
 const f=fixture(30);let count=0;delete f.github.fetchCommitHistoryPage;
 f.details=async id=>{count++;return f.commits.find(x=>x.sha===id)};
 const result=await findLinearAncestor({...f,head:f.commits[0].sha,ancestor:f.commits[24].sha});
 assert.equal(result.sha,f.commits[24].sha);assert.equal(count,25);
});
