'use strict';

// A manual run is a one-time, owner-authorized test, never a scheduler run.
// Site callers independently compare the committed permit with the lease.
function authorized(config,run,owner,runId,now,requiredScope=null){
 const permit=config?.manual_run_authorization,s=run?.scheduler;
 if(!permit||typeof permit!=='object'||Array.isArray(permit)||
    JSON.stringify(Object.keys(permit).sort())!==JSON.stringify(['expires_at','owner','run_id','scope'])||
    !s||s.kind!=='manual'||s.authorization!=='owner_request'||s.id!==config?.target_automation_id||
    permit.run_id!==runId||permit.owner!==owner||permit.scope!=='duplicate_only'||
    (requiredScope!==null&&permit.scope!==requiredScope)||run?.scheduled_for!==null||
    !Number.isFinite(now))return false;
 const until=Date.parse(permit.expires_at||''),started=Date.parse(run.started_at||'');
 return Number.isFinite(until)&&Number.isFinite(started)&&started<=now&&until>now&&until-started<=900000;
}
module.exports={authorized};
