export function processingHealth(evidence,now=Date.now()){
 const observed=Date.parse(evidence?.observed_at||'');
 const fresh=Number.isFinite(observed)&&observed<=now+300000&&now-observed<=90*60000;
 const positive=value=>typeof value==='number'&&Number.isFinite(value)&&value>0;
 const gateProgress=value=>positive(value)||(value&&typeof value==='object'&&!Array.isArray(value)&&Object.values(value).some(positive));
 let status=!fresh?'Status unknown — evidence stale or missing':positive(evidence?.publications)?'Publication reported; live receipt verification needed':positive(evidence?.newly_review_ready)?'Review readiness reported; independent verification needed':gateProgress(evidence?.downstream_gate_passes)?'Downstream gate progress reported; readiness unproven':gateProgress(evidence?.source_gate_passes)?'Source progress reported; readiness unproven':positive(evidence?.duplicate_gate_passes)?'Duplicate check reported; other gates unverified':'No candidate progress independently confirmed';
 if(fresh&&evidence?.trigger==='owner_maintenance')status='Owner maintenance: '+status;
 return {...(evidence||{}),fresh,status,counts_independently_verified:false};
}
export function displayCount(value){
 if(typeof value==='number'&&Number.isSafeInteger(value)&&value>=0)return String(value);
 if(value&&typeof value==='object'&&!Array.isArray(value)){
  const counts=Object.values(value);if(counts.length&&counts.every(v=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0))return String(counts.reduce((a,b)=>a+b,0));
 }
 return 'Unknown';
}
