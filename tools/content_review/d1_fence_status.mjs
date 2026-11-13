// Read-only inspection. This does not acquire a fence or establish worker
// health. The caller must still verify the active lease and final D1 snapshot.
const TABLE='content_review_write_fence';
const COLUMNS=['fence_id','operation_id','owner','run_id','expected_head','expected_tree','receipt_path','receipt_blob_sha','phase','acquired_at'];
const SOURCES={submissions:'review_submissions',decisions:'review_decisions',jobs:'review_jobs'};
const ACTIONS=['insert','update','delete'];
const compact=value=>typeof value==='string'?value.replace(/[`\"]/g,'').replace(/\s+/g,' ').trim().replace(/;$/,'').toLowerCase():'';
const unverified=()=>({status:'unverified',trigger_count:0,checkpoint_active:null});

export async function inspectFence(db){
 if(!db||typeof db.prepare!=='function'||typeof db.batch!=='function')return unverified();
 try{
  const queries=[`PRAGMA table_info(${TABLE})`,
   `SELECT sql FROM sqlite_master WHERE type='table' AND name='${TABLE}'`,
   `PRAGMA index_list(${TABLE})`,
   'PRAGMA index_info(content_review_write_fence_operation_id_unique)',
   "SELECT name,tbl_name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'content_review_fence_%' ORDER BY name",
   `SELECT phase FROM ${TABLE} LIMIT 2`];
  const result=await db.batch(queries.map(sql=>db.prepare(sql)));
  if(!Array.isArray(result)||result.length!==6||result.some(x=>x?.success!==true||!Array.isArray(x.results)))return unverified();
  const [table,definition,indexes,indexColumns,triggers,locks]=result.map(x=>x.results);
  const schema=compact(definition[0]?.sql);
  const checks=["check(content_review_write_fence.fence_id = 'content-review')",
   'check(length(content_review_write_fence.expected_head) = 40)',
   'check(length(content_review_write_fence.expected_tree) = 40)',
   'check(length(content_review_write_fence.receipt_blob_sha) = 40)',
   "check(content_review_write_fence.phase in ('preparing', 'committing'))"];
  if(JSON.stringify(table.map(x=>x.name))!==JSON.stringify(COLUMNS)||table[0]?.pk!==1||table[0]?.notnull!==1||
     definition.length!==1||checks.some(check=>!schema.includes(check))||
     !indexes.some(x=>x.name==='content_review_write_fence_operation_id_unique'&&x.unique===1)||
     indexColumns.length!==1||indexColumns[0]?.name!=='operation_id'||triggers.length!==9||locks.length>1)return unverified();
  const seen=new Set();
  for(const [key,target] of Object.entries(SOURCES))for(const action of ACTIONS){
   const name=`content_review_fence_${key}_${action}`;
   const found=triggers.filter(t=>t.name===name&&t.tbl_name===target);
   const expected=`CREATE TRIGGER ${name} BEFORE ${action} ON ${target} WHEN EXISTS (SELECT 1 FROM ${TABLE}) BEGIN SELECT RAISE(ABORT, 'review_checkpoint_in_progress'); END`;
   if(found.length!==1||compact(found[0].sql)!==compact(expected))return unverified();
   seen.add(name);
  }
  if(seen.size!==triggers.length||locks.some(x=>!['preparing','committing'].includes(x.phase)))return unverified();
  return {status:locks.length?'held':'idle',trigger_count:triggers.length,checkpoint_active:!!locks.length};
 }catch{return unverified();}
}
