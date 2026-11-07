import test from 'node:test';
import assert from 'node:assert/strict';
import {schedulerHealth} from '../lib/operations-health.mjs';

test('matching no-update result is never verified as successful work',()=>{
 const now=Date.parse('2026-11-07T12:00:00Z'),stamp=new Date(now).toISOString();
 const snapshot={scheduler:{observed_at:stamp,is_enabled:true,next_run_time:new Date(now+3600000).toISOString(),
  last_run:{id:'run',recorded_status:'no_update',started_at:stamp},
  last_verified_scheduled_success:{run_id:'run',evidence_verified:true,trigger:'schedule',receipt:'receipt.json',completed_at:stamp}}};
 const result=schedulerHealth(snapshot,now);
 assert.notEqual(result.status,'Operating normally');assert.equal(result.last_success_at,null);
});
