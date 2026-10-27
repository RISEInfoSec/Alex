// Source-independent Content Review rule. This is a resource-usefulness
// assessment, not a replacement for research-paper quality scores.
export function resourceUsefulness(row){
 const type=row.document_type||'';
 const presentation=type!=='research_paper'&&/presentation|slides|deck|talk|keynote|panel|recording|video|transcript/.test(type);
 if(!presentation)return {deduction:'not_applicable',status:'not_applicable',automatic_acceptance_allowed:null,reason:'Presentation/audio rule does not apply to this material type.'};
 const media=row.recording_verification;
 let validUrl=false;try{validUrl=['https:','http:'].includes(new URL(media?.url).protocol);}catch{}
 const verified=media?.status==='verified'&&media.matching_presentation===true&&media.substantively_complete===true&&media.usable_audio===true&&validUrl&&Number.isFinite(Date.parse(media.verified_at));
 if(verified)return {deduction:'none',status:'verified_audio',automatic_acceptance_allowed:null,reason:'Matching substantive recording with usable audio verified. Other relevance and quality checks still apply.'};
 const absent=row.audio_status==='verified_absent';
 return {deduction:'major',status:absent?'applied':'provisional_media_check_pending',automatic_acceptance_allowed:false,
  reason:absent?'Major resource-usefulness deduction: no substantive presentation audio is available.':'Provisional major resource-usefulness deduction: a matching complete recording with usable audio has not been verified. Media verification is required.'};
}
