'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSiteGithubApi}=require('../tools/content_review/github_site_api.cjs');
const repo='RISEInfoSec/Alex',branch='codex/soups-corpus-review',head='a'.repeat(40),blob='b'.repeat(40),commit='c'.repeat(40);
function fixture(){
 const calls=[];
 const fetcher=async(url,options)=>{
  calls.push({url,options});assert.ok(url.startsWith('https://api.github.com/'));
  assert.equal(options.headers.Authorization,'Bearer test-secret');assert.equal(options.redirect,'manual');
  if(url.includes('/git/commits/'))return Response.json({sha:head,tree:{sha:blob},parents:[{sha:commit}]});
  if(url.includes('/commits/'))return Response.json({sha:head});
  if(url.includes('/contents/'))return Response.json({sha:blob,encoding:'base64',content:btoa('file')});
  if(url.endsWith('/git/blobs'))return Response.json({sha:blob});
  if(url.endsWith('/git/trees'))return Response.json({sha:commit});
  if(url.endsWith('/graphql'))return Response.json({data:{createCommitOnBranch:{commit:{oid:commit}}}});
  throw Error('unexpected URL');
 };
 return {api:createSiteGithubApi({getToken:()=> 'test-secret',fetcher}),calls};
}
test('Site adapter sends exact-head atomic changes only to GitHub',async()=>{
 const {api,calls}=fixture();
 assert.equal((await api.fetchCommit({repo_full_name:repo,commit_sha:branch})).structuredContent.commit.sha,head);
 assert.deepEqual((await api.fetchCommitDetails({repository_full_name:repo,commit_sha:head})).structuredContent,
  {sha:head,tree_sha:blob,parents:[commit]});
 assert.equal((await api.fetchFile({repository_full_name:repo,path:'config/state.json',ref:head})).structuredContent.content,'file');
 assert.equal((await api.createBlob({repository_full_name:repo,encoding:'utf-8',content:'texte é'})).structuredContent.sha,blob);
 assert.equal((await api.createTree({repository_full_name:repo,base_tree_sha:head,
  tree_elements:[{path:'config/state.json',mode:'100644',type:'blob',sha:blob}]})).structuredContent.sha,commit);
 const result=await api.commitOnBranch({repository_full_name:repo,branch_name:branch,expected_sha:head,
  additions:[{path:'config/state.json',content:'texte é'}],message:'Record checkpoint'});
 assert.deepEqual(result.structuredContent,{success:true,sha:commit});
 const input=JSON.parse(calls.at(-1).options.body).variables.input;
 assert.equal(input.expectedHeadOid,head);assert.equal(input.branch.branchName,branch);
 assert.equal(Buffer.from(input.fileChanges.additions[0].contents,'base64').toString(),'texte é');
 assert.equal(JSON.stringify(result).includes('test-secret'),false);
});
test('tree creation rejects arbitrary paths, modes and duplicate additions before network',async()=>{
 const {api,calls}=fixture(),entry={path:'config/state.json',mode:'100644',type:'blob',sha:blob};
 for(const elements of [[{...entry,path:'config/../secret.json'}],[{...entry,mode:'100755'}],[entry,entry],[],[{...entry,content:'arbitrary'}]])
  assert.equal((await api.createTree({repository_full_name:repo,base_tree_sha:head,tree_elements:elements})).isError,true);
 assert.equal(calls.length,0);
});
test('scope, duplicate paths and oversized payloads fail before network',async()=>{
 const {api,calls}=fixture();
 const base={repository_full_name:repo,branch_name:branch,expected_sha:head,additions:[{path:'config/state.json',content:'ok'}],message:'Record'};
 for(const change of [{repository_full_name:'other/repo'},{branch_name:'main'},{expected_sha:'bad'},
  {additions:[{path:'config/../secrets.json',content:'x'}]},
  {additions:[{path:'config/state.json',content:'a'},{path:'config/state.json',content:'b'}]},
  {additions:[{path:'config/state.json',content:'x'.repeat(12*1024*1024+1)}]}]){
  assert.equal((await api.commitOnBranch({...base,...change})).isError,true);
 }
 assert.equal(calls.length,0);
});
test('Site adapter reads both source heads and restricts heartbeat writes',async()=>{
 const {api,calls}=fixture();
 for(const ref of ['main','codex/content-review-heartbeat'])
  assert.equal((await api.fetchCommit({repo_full_name:repo,commit_sha:ref})).structuredContent.commit.sha,head);
 assert.equal((await api.fetchCommit({repo_full_name:repo,commit_sha:'unrelated'})).isError,true);
 const base={repository_full_name:repo,branch_name:'codex/content-review-heartbeat',expected_sha:head,message:'Heartbeat'};
 assert.equal((await api.commitOnBranch({...base,additions:[{path:'config/state.json',content:'{}'}]})).isError,true);
 assert.equal((await api.commitOnBranch({...base,additions:[{path:'config/content_review_detached_heartbeat.json',content:'{}'}]})).structuredContent.sha,commit);
 assert.equal(JSON.parse(calls.at(-1).options.body).variables.input.branch.branchName,base.branch_name);
});
test('missing file, failures and ambiguous GraphQL responses are distinct and redacted',async()=>{
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async(url)=>url.includes('/contents/')?
  new Response('',{status:404}):Response.json({errors:[{message:'test-secret'}]})});
 assert.equal((await api.fetchFile({repository_full_name:repo,path:'config/missing.json',ref:head})).structuredContent.error_code,'NOT_FOUND');
 const result=await api.commitOnBranch({repository_full_name:repo,branch_name:branch,expected_sha:head,
  additions:[{path:'config/state.json',content:'{}'}],message:'Record'});
 assert.equal(result.structuredContent.error_code,'ATOMIC_COMMIT_FAILED_OR_AMBIGUOUS');
 assert.equal(JSON.stringify(result).includes('test-secret'),false);
});
test('redirects are rejected without forwarding credentials to the destination',async()=>{
 const calls=[];const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async(url,options)=>{
  calls.push({url,redirect:options.redirect});return new Response('',{status:302,headers:{Location:'https://untrusted.invalid/'}});
 }});
 const result=await api.fetchCommit({repo_full_name:repo,commit_sha:branch});
 assert.equal(result.isError,true);assert.equal(calls.length,1);assert.equal(calls[0].url.startsWith('https://api.github.com/'),true);
 assert.equal(calls[0].redirect,'manual');assert.equal(JSON.stringify(result).includes('test-secret'),false);
});
test('large GitHub contents with no inline body retain their blob identity',async()=>{
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async()=>Response.json({sha:blob,encoding:'none',content:''})});
 const result=await api.fetchFile({repository_full_name:repo,path:'config/large.json',ref:head});
 assert.equal(result.structuredContent.sha,blob);assert.equal(result.structuredContent.content,undefined);
});
test('explicit full-content reads retrieve the immutable large blob with a bounded size',async()=>{
 const content='é'.repeat(600000),calls=[];
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async url=>{
  calls.push(url);
  if(url.includes('/contents/'))return Response.json({sha:blob,encoding:'none',content:''});
  if(url.endsWith('/git/blobs/'+blob))return Response.json({sha:blob,encoding:'base64',size:Buffer.byteLength(content),content:Buffer.from(content).toString('base64')});
  throw Error('unexpected URL');
 }});
 const result=await api.fetchFile({repository_full_name:repo,path:'config/large.json',ref:head,require_content:true});
 assert.equal(result.structuredContent.sha,blob);assert.equal(result.structuredContent.content,content);
 assert.equal(calls.length,2);assert.ok(calls.every(url=>url.startsWith('https://api.github.com/')));
});
test('full-content reads reject a different identity and oversized blobs',async()=>{
 for(const value of [{sha:head,encoding:'base64',size:1,content:'YQ=='},
                     {sha:blob,encoding:'base64',size:12*1024*1024+1,content:'YQ=='}]){
  const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async url=>url.includes('/contents/')?
   Response.json({sha:blob,encoding:'none'}):Response.json(value)});
  const result=await api.fetchFile({repository_full_name:repo,path:'config/large.json',ref:head,require_content:true});
  assert.equal(result.isError,true);assert.equal(result.structuredContent.error_code,'CONTENT_UNAVAILABLE');
 }
});
test('bounded multi-megabyte changes retain every byte in the atomic payload',async()=>{
 let seen;
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async(url,options)=>{
  seen=JSON.parse(options.body).variables.input;return Response.json({data:{createCommitOnBranch:{commit:{oid:commit}}}});
 }});
 const content='é'.repeat(5*1024*1024);
 const result=await api.commitOnBranch({repository_full_name:repo,branch_name:branch,expected_sha:head,
  additions:[{path:'config/large.json',content}],message:'Record checkpoint'});
 assert.equal(result.structuredContent.sha,commit);
 assert.equal(Buffer.from(seen.fileChanges.additions[0].contents,'base64').toString(),content);
});
