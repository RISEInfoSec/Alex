// Verify every parent link from a pinned review head to a pinned ancestor.
// Batch reads avoid turning old retained artifacts into hundreds of calls.
// Merges, gaps, ambiguous pagination and incomplete proofs all fail closed.
const REPO='RISEInfoSec/Alex',SHA=/^[0-9a-f]{40}$/,MAX=500;
export async function findLinearAncestor({github,head,ancestor,heartbeat,details,
 linearError='Source reservation outside linear history',boundedError='Source reservation outside bounded history'}){
 if(!github||!SHA.test(head||'')||!SHA.test(ancestor||'')||typeof heartbeat!=='function'||typeof details!=='function')
  throw Error('Source history request invalid');
 let expected=head,seen=0;
 if(typeof github.fetchCommitHistoryPage!=='function'){
  while(seen++<MAX){await heartbeat();const item=await details(expected);
   if(!item||item.sha!==expected||!SHA.test(item.tree_sha||'')||!Array.isArray(item.parents)||item.parents.length!==1||!SHA.test(item.parents[0]||''))throw Error(linearError);
   if(expected===ancestor)return item;expected=item.parents[0];
  }
  throw Error(boundedError);
 }
 let cursor=null;const cursors=new Set();
 while(seen<MAX){
  await heartbeat();const result=await github.fetchCommitHistoryPage({repository_full_name:REPO,head,cursor});
  const page=!result?.isError&&result?.structuredContent;
  if(!page||!Array.isArray(page.commits)||!page.commits.length||page.commits.length>50||typeof page.has_next!=='boolean')throw Error(boundedError);
  for(const item of page.commits){
   if(++seen>MAX)throw Error(boundedError);
   if(!item||item.sha!==expected||!SHA.test(item.tree_sha||'')||!Array.isArray(item.parents)||item.parents.length!==1||!SHA.test(item.parents[0]||''))throw Error(linearError);
   if(expected===ancestor)return item;expected=item.parents[0];
  }
  if(!page.has_next||typeof page.end_cursor!=='string'||!page.end_cursor||page.end_cursor.length>512||cursors.has(page.end_cursor))throw Error(boundedError);
  cursors.add(page.end_cursor);cursor=page.end_cursor;
 }
 throw Error(boundedError);
}
