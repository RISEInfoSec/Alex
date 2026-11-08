'use client';
import {useEffect,useRef,useState} from 'react';
import {safeLink} from '../lib/review-core.mjs';
import {refreshedEvidence} from '../lib/operations-refresh-state.mjs';
import {displayCount} from '../lib/processing-health.mjs';
import './operations-panel.css';
const date=(value:any)=>{if(!value)return 'Not recorded';const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleString():value;};
export default function OperationsPanel(){
 const [data,setData]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[stale,setStale]=useState(false);
 const retained=useRef<any>(null),generation=useRef(0),request=useRef<AbortController|null>(null);
 async function refresh(){
  const id=++generation.current;request.current?.abort();const controller=new AbortController();request.current=controller;setBusy(true);
  try{
   const r=await fetch('/api/operations?refresh='+crypto.randomUUID(),{cache:'no-store',headers:{'Cache-Control':'no-cache'},signal:controller.signal});
   if(!r.ok)throw Error();const latest=await r.json();
   if(id===generation.current){const next=refreshedEvidence(retained.current,latest);retained.current=next.data;setData(next.data);setStale(next.stale);setError(next.error);}
  }catch{if(id===generation.current){setStale(true);setError('Refresh failed. Retained evidence is stale; current worker health is unverified.');}}
  finally{if(id===generation.current)setBusy(false);}
 }
 useEffect(()=>{refresh();const timer=setInterval(refresh,30000);return()=>{clearInterval(timer);++generation.current;request.current?.abort();};},[]);
 const main=data?.workers.find((w:any)=>w.id==='content-review');
 const problems=data?.workers.filter((w:any)=>['Paused','Failed','Cancelled','Overdue','Degraded','Status unknown','Not configured'].includes(w.status))||[];
 const incidents=data?.providers.filter((p:any)=>['Failed','Degraded','Status unknown'].includes(p.status))||[];
 const displayState=stale?'Status unknown — stale evidence':main?.status||'Status unknown';
 return <section className="operations-panel" aria-label="Worker and service health" aria-busy={busy}>
  <header><div><span className="operations-eyebrow">WORKERS & SERVICES</span><h2>Content Review: <span className={'health-state state-'+(stale?'unknown':main?.status||'unknown').toLowerCase().replaceAll(' ','-')}>{busy?'Checking…':displayState}</span></h2></div><button type="button" onClick={refresh} disabled={busy}>{busy?'Checking…':'Refresh status'}</button></header>
  {error&&<p role="alert" className="health-stale">{error}</p>}
  {!data&&!error&&<p role="status">Reading current operational evidence…</p>}
  {data&&<>
   <p>{stale?'Last reported: ':''}{main?.issue}</p>
   {data.worker_scope&&<p>{stale?'Last reported worker scope':'Current worker scope'}: {data.worker_scope}</p>}
   {data.decision_write_fence?.status==='held'&&<p role="status"><strong>Review saving:</strong> Temporarily paused while a checkpoint is verified. Drafts remain available.</p>}
   {data.decision_write_fence?.status==='unverified'&&<p role="status"><strong>Review-saving protection:</strong> Its current status could not be verified.</p>}
   {data.replacement_configured&&<div className="monitor-evidence"><strong>Candidate processing: {stale?'Status unknown — stale evidence':data.processing?.status||'Status unknown'}</strong><p>Last reported pass: {displayCount(data.processing?.local_candidates)} candidates · {displayCount(data.processing?.duplicate_gate_passes)} duplicate checks · {displayCount(data.processing?.source_requests)} source requests · {displayCount(data.processing?.source_evidence_retained)} source results retained · {displayCount(data.processing?.source_holds_retained)} source holds recorded · {displayCount(data.processing?.source_gate_passes)} new source gate passes · {displayCount(data.processing?.six_gate_completions)} complete preflights · {displayCount(data.processing?.newly_review_ready)} newly review-ready.</p><p>These counts are reported; this console has not independently verified them. Scheduler completion alone does not establish candidate progress.</p>{data.processing?.scope_note&&<p>Last reported context{data.processing?.fresh?'':' (may be stale)'}: {data.processing.scope_note}</p>}<p className="health-dates">Processing evidence: {date(data.processing?.observed_at)} · {data.processing?.corrective_action}</p></div>}
   <p className="health-dates">Last successful evidence read: {date(data.checked_at)} · Worker activity observed: {date(main?.activity_observed_at)} · Native scheduler observed: {date(main?.observed_at)}</p>
   <p className="health-dates">Scheduler evidence: {main?.scheduler_evidence_source||main?.evidence_source||'Not available'} · Last attempt: {date(main?.last_attempt_at)}{main?.last_attempt_source?' ('+main.last_attempt_source+')':''}</p>
   <p className="health-dates">Verified scheduled completion: {date(main?.last_success_at)} · Next run: {date(main?.next_run_at)}{main?.next_run_source?' ('+main.next_run_source+')':''}</p>
   {(problems.length>0||incidents.length>0)&&<div className="health-alerts" role="status">{problems.filter((w:any)=>w.id!=='content-review'&&w.id!=='independent-monitor').map((w:any)=><p key={w.id}><strong>{w.name}: {stale?'Last reported ':''}{w.status}.</strong> {w.issue}</p>)}{incidents.map((p:any)=><p key={p.id}><strong>{p.name}: {stale?'Last reported ':''}{p.status}.</strong> {p.issue}{p.retry_not_before?' Retry/cooldown: '+date(p.retry_not_before)+'.':''}{p.operator_action?' Action: '+p.operator_action:''}</p>)}</div>}
   <details><summary>All workers and service evidence · {data.workers.length} workers</summary><div className="health-table"><table><thead><tr><th>Worker / purpose</th><th>State</th><th>Schedule</th><th>Last attempt</th><th>Last success</th><th>Next run / issue</th></tr></thead><tbody>{data.workers.map((w:any)=><tr key={w.id}><td><strong>{w.name}</strong><small>{w.purpose}</small></td><td>{stale?'Last reported: ':''}{w.status}</td><td>{w.schedule_label|| (w.schedule_enabled===true?'Enabled':w.schedule_enabled===false?'Disabled':w.managed_by?'Managed by hourly worker':'Unconfirmed / event driven')}</td><td>{date(w.last_attempt_at)}</td><td>{date(w.last_success_at)}</td><td>{w.next_run_at&&<p>{date(w.next_run_at)}{w.next_run_source&&<small>{w.next_run_source}</small>}</p>}{w.issue}{safeLink(w.run_url)&&<p><a href={safeLink(w.run_url)!} target="_blank" rel="noreferrer">Inspect run ↗</a></p>}</td></tr>)}</tbody></table></div>
   {data.providers.map((p:any)=><article className="provider-evidence" key={p.id}><strong>{p.name} · {stale?'Last reported: ':''}{p.status}</strong><p>{p.issue}</p><p>Impact: {p.impact||'Not recorded'} · Incident began: {date(p.first_failure_at||p.last_failure_at)} · Latest verified result: {p.last_http_status||'Unknown'} at {date(p.last_result_at||p.last_success_at)} · Retry/cooldown: {date(p.retry_not_before)}</p>{p.operator_action&&<p>Operator action: {p.operator_action}</p>}</article>)}
   </details>
   <small>Refresh reads origin evidence without a shared cache. Expected start times are calculations from the last observed schedule. Missing, expired or failed evidence is never presented as confirmed normal operation.</small>
  </>}
 </section>;
}
