'use strict';

// Adapter for a private Site runtime with the existing repository-scoped token.
// Use only through github_atomic_checkpoint's proof and final D1/lease fence;
// this adapter by itself does not authorize any worker or candidate mutation.
const REPOSITORY='RISEInfoSec/Alex', REVIEW='codex/soups-corpus-review', HEARTBEAT='codex/content-review-heartbeat';
const HEARTBEAT_PATH='config/content_review_detached_heartbeat.json';
const BASE='https://api.github.com', SHA=/^[0-9a-f]{40}$/;
const MAX_FILES=5, MAX_TOTAL_BYTES=12*1024*1024;

function base64Utf8(text){
 const bytes=new TextEncoder().encode(text);let binary='';
 for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
 return btoa(binary);
}
function failure(code){return {isError:true,structuredContent:{error_code:code}};}
function success(value){return {isError:false,structuredContent:value};}

function createSiteGithubApi({getToken,fetcher=fetch,timeoutMs=20000}={}){
 if(typeof getToken!=='function'||typeof fetcher!=='function'||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)
  throw new Error('Existing Site credential and bounded fetch are required');
 async function request(path,{method='GET',body}={}){
  const token=getToken();
  if(typeof token!=='string'||!token)return {status:0};
  // The hostname and redirect policy are fixed in code; the token is never
  // sent to a caller-supplied URL or included in errors, output or source.
  try{
   const result=await fetcher(BASE+path,{method,headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json',
    'User-Agent':'ALEX-Review-Worker',...(body?{'Content-Type':'application/json'}:{})},
    ...(body?{body:JSON.stringify(body)}:{}),redirect:'error',cache:'no-store',signal:AbortSignal.timeout(timeoutMs)});
   if(!result.ok)return {status:result.status};
   return {status:result.status,data:await result.json()};
  }catch{return {status:0};}
 }
 function validPath(path){return typeof path==='string'&&/^config\/[a-zA-Z0-9_./-]+\.json$/.test(path)&&!path.includes('..');}
 function pathFor(path){return path.split('/').map(encodeURIComponent).join('/');}
 const repoPath='/repos/'+REPOSITORY;
 return {
  async fetchCommit({repo_full_name,commit_sha}){
   if(repo_full_name!==REPOSITORY||![REVIEW,HEARTBEAT,'main'].includes(commit_sha))return failure('INVALID_SCOPE');
   const result=await request(repoPath+'/commits/'+encodeURIComponent(commit_sha));
   return SHA.test(result.data?.sha||'')?success({commit:{sha:result.data.sha}}):failure('READ_FAILED');
  },
  async fetchFile({repository_full_name,path,ref}){
   if(repository_full_name!==REPOSITORY||!validPath(path)||!SHA.test(ref||''))return failure('INVALID_SCOPE');
   const result=await request(repoPath+'/contents/'+pathFor(path)+'?ref='+encodeURIComponent(ref));
   if(result.status===404)return failure('NOT_FOUND');
   if(!SHA.test(result.data?.sha||''))return failure('READ_FAILED');
   let content;
   if(result.data.encoding==='base64'&&typeof result.data.content==='string'){
    try{const raw=atob(result.data.content.replace(/\s/g,''));content=new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(raw,c=>c.charCodeAt(0)));}
    catch{return failure('INVALID_CONTENT');}
   }
   return success({sha:result.data.sha,...(content===undefined?{}:{content})});
  },
  async createBlob({repository_full_name,content,encoding}){
   if(repository_full_name!==REPOSITORY||encoding!=='utf-8'||typeof content!=='string'||new TextEncoder().encode(content).length>MAX_TOTAL_BYTES)
    return failure('INVALID_SCOPE');
   const result=await request(repoPath+'/git/blobs',{method:'POST',body:{content,encoding:'utf-8'}});
   return SHA.test(result.data?.sha||'')?success({sha:result.data.sha}):failure('BLOB_FAILED');
  },
  async commitOnBranch({repository_full_name,branch_name,expected_sha,additions,message}){
   if(repository_full_name!==REPOSITORY||![REVIEW,HEARTBEAT].includes(branch_name)||!SHA.test(expected_sha||'')||
      !Array.isArray(additions)||additions.length<1||additions.length>MAX_FILES||
      typeof message!=='string'||!message||message.length>100||
      additions.some(x=>!x||!validPath(x.path)||typeof x.content!=='string')||
      (branch_name===HEARTBEAT&&(additions.length!==1||additions[0].path!==HEARTBEAT_PATH))||
      new Set(additions.map(x=>x.path)).size!==additions.length)return failure('INVALID_SCOPE');
   let total=0;for(const item of additions)total+=new TextEncoder().encode(item.content).length;
   if(total>MAX_TOTAL_BYTES)return failure('CONTENT_LIMIT');
   const query='mutation($input:CreateCommitOnBranchInput!){createCommitOnBranch(input:$input){commit{oid}}}';
   const variables={input:{branch:{repositoryNameWithOwner:REPOSITORY,branchName:branch_name},expectedHeadOid:expected_sha,
    message:{headline:message},fileChanges:{additions:additions.map(x=>({path:x.path,contents:base64Utf8(x.content)}))}}};
   const result=await request('/graphql',{method:'POST',body:{query,variables}});
   const sha=result.data?.data?.createCommitOnBranch?.commit?.oid;
   if(result.data?.errors?.length||!SHA.test(sha||''))return failure('ATOMIC_COMMIT_FAILED_OR_AMBIGUOUS');
   return success({success:true,sha});
  },
 };
}
module.exports={createSiteGithubApi};
