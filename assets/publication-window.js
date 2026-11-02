// Progressive date-window refresh. The bibliography remains usable without JS.
(function(){
  const end=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Toronto',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const startDate=new Date(end+'T00:00:00Z');startDate.setUTCDate(startDate.getUTCDate()-90);
  const start=startDate.toISOString().slice(0,10);let count=0;
  document.querySelectorAll('[data-publication-date]').forEach(item=>{
    const value=item.getAttribute('data-publication-date');
    const visible=value>=start&&value<=end;item.hidden=!visible;item.style.display=visible?'':'none';if(visible)count++;
  });
  document.getElementById('new-publication-count').textContent=String(count);
  document.getElementById('new-publications-empty').hidden=count>0;
  document.getElementById('publication-window').textContent='Publication window: '+start+' to '+end+'.';
})();
