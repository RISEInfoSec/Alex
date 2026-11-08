'use strict';

// Preserve observed source-provider cooldowns independently of the worker.
const HOST=/^[a-z0-9.-]+(?::[0-9]{1,5})?$/,REASON=/^(?:http_(?:429|5[0-9]{2})|transport_[A-Za-z][A-Za-z0-9]*)$/;
const HASH=/^[0-9a-f]{64}$/;
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const time=x=>typeof x==='string'?Date.parse(x):NaN;
function origin(url){
 if(typeof url!=='string'||/[\r\n\t]/.test(url))throw Error('Unsupported source origin');
 const m=/^https?:\/\/([^/?#]+)/.exec(url);if(!m)throw Error('Unsupported source origin');
 const host=m[1].toLowerCase();let u;try{u=new URL(url);}catch{throw Error('Unsupported source origin');}
 if(!HOST.test(host)||u.username||u.password||(u.port&&!['80','443'].includes(u.port)))throw Error('Unsupported source origin');
 return host;
}
function merge(previous,result,requestId){
 if(!obj(previous)||!obj(result)||!HASH.test(requestId||''))throw Error('Source backoff inputs invalid');
 for(const [host,value] of Object.entries(previous))if(!HOST.test(host)||!obj(value)||!Number.isFinite(time(value.retry_not_before))||!REASON.test(value.reason||''))
  throw Error('Existing source backoff invalid');
 const events=result.request_log,reported=result.origin_backoff??{};
 if(!Array.isArray(events)||!obj(reported)||Object.keys(reported).length>30)throw Error('Source backoff evidence invalid');
 const failures={};
 for(const event of events){
  if(!obj(event))throw Error('Source request event invalid');
  const status=event.http_status,error=event.error;
  const reason=Number.isSafeInteger(status)&&(status===429||status>=500&&status<=599)?'http_'+status:
   typeof error==='string'&&error?'transport_'+error:null;
  if(!reason)continue;if(!REASON.test(reason))throw Error('Source failure reason invalid');
  const host=origin(event.url),started=time(event.started_at),header=time(event.retry_not_before);
  if(!Number.isFinite(started)||Object.prototype.hasOwnProperty.call(failures,host))throw Error('Source failure timing or origin ambiguous');
  failures[host]={reason,started,header};
 }
 if(JSON.stringify(Object.keys(reported).sort())!==JSON.stringify(Object.keys(failures).sort()))throw Error('Source cooldowns do not match failure events');
 const updated=structuredClone(previous);
 for(const [host,failure] of Object.entries(failures)){
  const value=reported[host],deadline=time(value?.retry_not_before);
  if(!obj(value)||!Number.isFinite(deadline)||value.reason!==failure.reason||
   (Number.isFinite(failure.header)?deadline<failure.header:deadline<failure.started+3600000))
   throw Error('Source cooldown does not preserve provider deadline');
  const old=time(updated[host]?.retry_not_before);
  if(!Number.isFinite(old)||deadline>old)updated[host]={reason:failure.reason,retry_not_before:value.retry_not_before,source_request_id:requestId};
 }
 return updated;
}
function active(backoffs,url,now){
 if(!obj(backoffs)||!Number.isFinite(now))throw Error('Source backoff state invalid');
 const value=backoffs[origin(url)];if(value===undefined)return false;
 if(!obj(value)||!REASON.test(value.reason||'')||!Number.isFinite(time(value.retry_not_before)))throw Error('Source backoff state invalid');
 return time(value.retry_not_before)>now;
}
module.exports={merge,active,origin};
