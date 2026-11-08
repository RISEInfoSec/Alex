import test from 'node:test';
import assert from 'node:assert/strict';
import {coordinatorHealth} from '../lib/operations-health.mjs';

test('a failed worker without a receipt does not suggest one exists',()=>{
 const now=Date.parse('2026-11-08T12:00:00Z'),at=new Date(now).toISOString();
 const scheduler={id:'Automation_worker',is_enabled:true,observed_at:at,last_run:{id:'run',recorded_status:'in_progress',started_at:at}};
 const checkpoint={lease:null,current_run:{run_id:'run',application_status:'failed',observed_at:at,scheduler}};
 const result=coordinatorHealth({scheduler},checkpoint,now);
 assert.equal(result.status,'Failed');assert.match(result.issue,/no completion receipt is recorded/);
 checkpoint.current_run.receipt='config/content_review_run_receipts/run.json';
 assert.match(coordinatorHealth({scheduler},checkpoint,now).issue,/receipt is referenced but not independently verified/);
});
