'use strict';

// Read only the three review tables through the existing Site D1 binding.
// Values and fingerprints remain private in memory. The caller must maintain
// the real lease heartbeat while any database call is in flight and recheck D1
// again immediately before an atomic GitHub update.
const {fingerprint}=require('./d1_fingerprint.cjs');
const TABLES=Object.freeze({submissions:'review_submissions',decisions:'review_decisions',jobs:'review_jobs'});
const LIMIT=10000;

async function readStable({db,heartbeat}){
 if(!db||typeof db.prepare!=='function'||typeof db.batch!=='function'||typeof heartbeat!=='function')
  throw new Error('D1 binding and verified heartbeat are required');
 async function once(){
  const statements=[];
  for(const table of Object.values(TABLES)){
   statements.push(db.prepare('PRAGMA table_info('+table+')'));
   statements.push(db.prepare('SELECT COUNT(*) AS row_count FROM '+table));
   statements.push(db.prepare('SELECT * FROM '+table+' ORDER BY id LIMIT 10001'));
  }
  let responses;
  try{responses=await db.batch(statements);}catch{throw new Error('D1 snapshot read failed');}
  if(!Array.isArray(responses)||responses.length!==statements.length)
   throw new Error('D1 batch response is incomplete');
  const snapshot={read_evidence:{}},schemas={};
  for(const [index,key] of Object.keys(TABLES).entries()){
   const schema=responses[index*3],count=responses[index*3+1],data=responses[index*3+2];
   const columns=Array.isArray(schema?.results)?schema.results.map(x=>x?.name):[];
   if(schema?.success!==true||!columns.length||columns.some(x=>typeof x!=='string'||!x)||new Set(columns).size!==columns.length||
      count?.success!==true||data?.success!==true||!Array.isArray(count.results)||count.results.length!==1||
      !Number.isSafeInteger(count.results[0]?.row_count)||count.results[0].row_count<0||count.results[0].row_count>LIMIT||
      !Array.isArray(data.results)||data.results.length!==count.results[0].row_count)
    throw new Error('D1 table count or rows are incomplete');
   const expected=[...columns].sort();
   schemas[key]=expected;
   if(data.results.some(row=>!row||Array.isArray(row)||typeof row!=='object'||
      JSON.stringify(Object.keys(row).sort())!==JSON.stringify(expected)))
    throw new Error('D1 row columns are incomplete');
   snapshot[key]=data.results;
   snapshot.read_evidence[key]={complete:true,rows_received:data.results.length,truncated_values:0,omitted_columns:0};
  }
  // Reject unsupported cells, ambiguous row IDs and oversized data before
  // reporting complete evidence. Never log the value or its fingerprint.
  fingerprint(snapshot);
  return {snapshot,schemas};
 }
 await heartbeat();const first=await once();await heartbeat();const second=await once();await heartbeat();
 if(JSON.stringify(first.schemas)!==JSON.stringify(second.schemas)||fingerprint(first.snapshot)!==fingerprint(second.snapshot))
  throw new Error('D1 changed between complete reads');
 return {snapshot:first.snapshot,confirmed_snapshot:second.snapshot,transactional_snapshot:false};
}
module.exports={readStable};
