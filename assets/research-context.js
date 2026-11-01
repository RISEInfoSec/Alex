/* Explicit historical status and calendar age are independent presentation facts. */
const ResearchContext = (() => {
  const notice = 'This work reflects the evidence and technical environment at the time of publication. Its methods and insights may remain valuable, while some findings or practical guidance may have been refined or superseded by subsequent research and developments. Please consult more recent sources before applying it to current research or investigations.';
  const historical = p => String(p.historical_only ?? '').trim().toLowerCase() === 'true';
  function earlier(p, now = new Date()) {
    const raw = String(p.publication_date || '');
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
    if (match) {
      const [y,m,d] = match.slice(1).map(Number);
      const parsed = new Date(Date.UTC(y,m-1,d));
      if (y >= 1000 && parsed.getUTCFullYear() === y && parsed.getUTCMonth() === m-1 && parsed.getUTCDate() === d) {
        const lastDay = new Date(Date.UTC(y+5,m,0)).getUTCDate();
        const anniversary = Date.UTC(y+5,m-1,Math.min(d,lastDay));
        return now.getTime() >= anniversary;
      }
    }
    const year = Number(p.year);
    return Number.isInteger(year) && year > 0 && year <= now.getUTCFullYear()-5;
  }
  function marker(p) {
    if (historical(p)) return '<span class="context-marker context-historical" title="Historical reference" aria-label="Historical reference">H</span>';
    if (earlier(p)) return '<span class="context-marker context-earlier" title="Earlier research: five years or older" aria-label="Earlier research: five years or older">5+</span>';
    return '';
  }
  function detail(p) {
    if (!earlier(p) && !historical(p)) return '';
    return `<aside class="research-context" aria-label="Research context"><strong>Research context</strong>${historical(p) ? '<p><strong>Historical reference.</strong> Included for its historical contribution. Technical details and recommendations should be read in the context of the period in which the work was published.</p>' : ''}<p>${notice}</p></aside>`;
  }
  return {historical, earlier, marker, detail};
})();
