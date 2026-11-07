'use strict';
const REPO='RISEInfoSec/Alex', REF='codex/content-review-heartbeat', PATH='config/content_review_detached_heartbeat.json';
const SHA=/^[0-9a-f]{40}$/;
async function readHeartbeat({api,linkId,gitBlobSha1}){
 if(!api||!linkId||typeof api.fetchCommit!=='function'||typeof api.fetchFile!=='function'||typeof gitBlobSha1!=='function')
  throw new Error('Independent heartbeat reader is unavailable');
 const headResult=await api.fetchCommit({link_id:linkId,repo_full_name:REPO,commit_sha:REF});
 const head=!headResult?.isError&&headResult?.structuredContent?.commit?.sha;
 if(!SHA.test(head||''))throw new Error('Heartbeat ref head is unavailable');
 const file=await api.fetchFile({link_id:linkId,repository_full_name:REPO,ref:head,path:PATH,encoding:'utf-8'});
 const value=!file?.isError&&file?.structuredContent;
 if(!value||typeof value.content!=='string'||!SHA.test(value.sha||'')||gitBlobSha1(value.content)!==value.sha)
  throw new Error('Heartbeat blob is incomplete or altered');
 let record;try{record=JSON.parse(value.content);}catch{throw new Error('Heartbeat blob is not valid JSON');}
 const latest=await api.fetchCommit({link_id:linkId,repo_full_name:REPO,commit_sha:REF});
 if(latest?.isError||latest?.structuredContent?.commit?.sha!==head)throw new Error('Heartbeat ref changed during read');
 return {ref:REF,head,record,verified_blob:true};
}
module.exports={readHeartbeat};
