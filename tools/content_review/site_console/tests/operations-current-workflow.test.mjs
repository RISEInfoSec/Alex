import test from 'node:test';
import assert from 'node:assert/strict';
import {workflowHealth,operationsSummary} from '../lib/operations-health.mjs';
import {readOperations} from '../lib/operations-source.mjs';

const now=Date.parse('2026-11-08T14:00:00Z');
test('cancelled weekly run remains an attention item without being mislabeled',()=>{
 const w=workflowHealth({id:'pipeline',scheduled:true},{state:'active'},[{head_branch:'main',status:'completed',
  conclusion:'cancelled',created_at:'2026-11-08T13:00:00Z'}],now);
 assert.equal(w.status,'Cancelled');assert.match(w.issue,/no successful completion/i);
 assert.equal(operationsSummary([w],[]).problems,1);
});
test('draft source regression evidence is visible but not claimed as worker processing',()=>{
 const run={head_branch:'codex/unattended-review-replacement-20261106',event:'pull_request',status:'completed',conclusion:'success',
  created_at:'2026-11-08T13:00:00Z',updated_at:'2026-11-08T13:01:00Z',html_url:'https://github.com/example/run'};
 const w=workflowHealth({id:'source-regression'},{state:'active'},[run],now);
 assert.equal(w.run_url,run.html_url);assert.match(w.issue,/draft pull request regression: success/i);
 assert.match(w.issue,/does not establish worker processing/i);
 assert.match(workflowHealth({id:'other'},{state:'active'},[run],now).issue,/no relevant execution/i);
});
test('a fresh reported pause retains the prior failed application and verification caveat',async()=>{
 const target='Automation_new',encoded=value=>Response.json({encoding:'base64',content:Buffer.from(JSON.stringify(value)).toString('base64')});
 const fetcher=async url=>{
  if(url.includes('content_review_operations.json'))return encoded({scheduler:{id:target,observed_at:'2026-11-08T13:59:00Z',is_enabled:false,last_run:{id:'latest',recorded_status:'completed'}}});
  if(url.includes('content_review_worker_status.json'))return encoded({current_run:{run_id:'earlier',scheduler:{id:target},application_status:'failed'}});
  if(url.includes('content_review_monitor_config.json'))return encoded({target_automation_id:target});
  if(url.includes('content_review_processing_health.json'))return encoded({});
  if(url.includes('openalex_request_policy.json'))return encoded({requests_enabled:true});
  return Response.json({workflows:[]});
 };
 const value=(await readOperations({now,cache:false,fetcher})).workers.find(x=>x.id==='content-review');
 assert.equal(value.status,'Paused');assert.equal(value.native_evidence_verified,false);
 assert.match(value.issue,/worker-reported.*paused/i);assert.match(value.issue,/last worker application failed/i);
 assert.match(value.issue,/cannot independently verify/i);
});
