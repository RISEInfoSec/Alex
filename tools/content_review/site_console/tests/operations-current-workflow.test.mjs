import test from 'node:test';
import assert from 'node:assert/strict';
import {workflowHealth,operationsSummary} from '../lib/operations-health.mjs';

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
