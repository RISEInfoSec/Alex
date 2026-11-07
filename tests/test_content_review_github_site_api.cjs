'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSiteGithubApi}=require('../tools/content_review/github_site_api.cjs');
const repo='RISEInfoSec/Alex',branch='codex/soups-corpus-review',head='a'.repeat(40),blob='b'.repeat(40),commit='c'.repeat(40);
function fixture(){
 const calls=[];
 const fetcher=async(url,options)=>{
  calls.push({url,options});assert.ok(url.startsWith('https://api.github.com/'));
  assert.equal(options.headers.Authorization,'Bearer test-secret');assert.equal(options.redirect,'error');
  if(url.includes('/commits/'))return Response.json({sha:head});
  if(url.includes('/contents/'))return Response.json({sha:blob,encoding:'base64',content:btoa('file')});
  if(url.endsWith('/git/blobs'))return Response.json({sha:blob});
  if(url.endsWith('/graphql'))return Response.json({data:{createCommitOnBranch:{commit:{oid:commit}}}});
  throw Error('unexpected URL');
 };
 return {api:createSiteGithubApi({getToken:()=> 'test-secret',fetcher}),calls};
}
test('Site adapter sends exact-head atomic changes only to GitHub',async()=>{
 const {api,calls}=fixture();
 assert.equal((await api.fetchCommit({repo_full_name:repo,commit_sha:branch})).structuredContent.commit.sha,head);
 assert.equal((await api.fetchFile({repository_full_name:repo,path:'config/state.json',ref:head})).structuredContent.content,'file');
 assert.equal((await api.createBlob({repository_full_name:repo,encoding:'utf-8',content:'texte é'})).structuredContent.sha,blob);
 const result=await api.commitOnBranch({repository_full_name:repo,branch_name:branch,expected_sha:head,
  additions:[{path:'config/state.json',content:'texte é'}],message:'Record checkpoint'});
 assert.deepEqual(result.structuredContent,{success:true,sha:commit});
 const input=JSON.parse(calls.at(-1).options.body).variables.input;
 assert.equal(input.expectedHeadOid,head);assert.equal(input.branch.branchName,branch);
 assert.equal(Buffer.from(input.fileChanges.additions[0].contents,'base64').toString(),'texte é');
 assert.equal(JSON.stringify(result).includes('test-secret'),false);
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
test('missing file, failures and ambiguous GraphQL responses are distinct and redacted',async()=>{
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async(url)=>url.includes('/contents/')?
  new Response('',{status:404}):Response.json({errors:[{message:'test-secret'}]})});
 assert.equal((await api.fetchFile({repository_full_name:repo,path:'config/missing.json',ref:head})).structuredContent.error_code,'NOT_FOUND');
 const result=await api.commitOnBranch({repository_full_name:repo,branch_name:branch,expected_sha:head,
  additions:[{path:'config/state.json',content:'{}'}],message:'Record'});
 assert.equal(result.structuredContent.error_code,'ATOMIC_COMMIT_FAILED_OR_AMBIGUOUS');
 assert.equal(JSON.stringify(result).includes('test-secret'),false);
});
test('large GitHub contents with no inline body retain their blob identity',async()=>{
 const api=createSiteGithubApi({getToken:()=> 'test-secret',fetcher:async()=>Response.json({sha:blob,encoding:'none',content:''})});
 const result=await api.fetchFile({repository_full_name:repo,path:'config/large.json',ref:head});
 assert.equal(result.structuredContent.sha,blob);assert.equal(result.structuredContent.content,undefined);
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
