const SITE_URL='https://alex-hosted-staging-review.neil-schwartzm917549.chatgpt.site';
export default {
 async scheduled(event,env) {
  const id=crypto.randomUUID();
  const response=await fetch(SITE_URL+'/api/worker',{method:'POST',headers:{'Content-Type':'application/json','OAI-Sites-Authorization':'Bearer '+env.SITE_ACCESS,'x-alex-scheduler-key':env.SCHEDULER_KEY},body:JSON.stringify({id,scheduledTime:event.scheduledTime,cron:event.cron}),signal:AbortSignal.timeout(25000)});
  let receipt;try{receipt=await response.json();}catch{throw Error('staging_response_not_json');}
  console.log(JSON.stringify({kind:'alex-hosted-staging',id,scheduledTime:event.scheduledTime,cron:event.cron,httpStatus:response.status,site_receipt_id:receipt.id,status:receipt.status,completed_jobs:receipt.completed_jobs,before:receipt.before,after:receipt.after,stale_token_refused:receipt.stale_token_refused,three_replays_without_duplicates:receipt.three_replays_without_duplicates}));
  if(!response.ok)throw Error('staging_processing_request_failed');
  if(receipt.simulate_interrupted_handler)throw Error('intentional_staging_interruption_after_claim');
 }
};
