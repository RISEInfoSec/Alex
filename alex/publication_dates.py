"""Verified day-precision publication dates; never discovery/index/update dates."""
from __future__ import annotations
import copy,json,re
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def today():return datetime.now(ZoneInfo('America/Toronto')).date()
def exact_date(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return None
    try:return date.fromisoformat(value)
    except ValueError:return None

def crossref_publication_fields(item,as_of=None):
    dates=[]
    primary=('published-online','published-print')
    fields=primary if any((item.get(k) or {}).get('date-parts') for k in primary) else ('published','issued')
    # An earlier coarse primary date must not be replaced by a later full
    # print/issue date and make an old work appear new.
    for field in fields:
        parts=(item.get(field) or {}).get('date-parts') or []
        if parts and len(parts[0]) in (1,2):return {}
    for field in fields:
        parts=(item.get(field) or {}).get('date-parts') or []
        if not parts or len(parts[0])!=3:continue
        try:value=date(*parts[0])
        except (ValueError,TypeError):continue
        dates.append((value,field))
    if not dates:return {}
    value,field=min(dates)
    if value>(as_of or today()):return {}
    doi=str(item.get('DOI') or '').strip()
    if not doi:return {}
    return dict(publication_date=value.isoformat(),publication_date_source='https://api.crossref.org/works/'+doi,
                publication_date_status='verified',publication_date_basis='Crossref publisher metadata: '+field)

def row_publication_fields(row):
    value=exact_date(row.get('publication_date'))
    source=row.get('publication_date_source')
    if value is None or row.get('publication_date_status')!='verified' or not isinstance(source,str) or not source.startswith('https://'):return {}
    return {k:row.get(k,'') for k in ('publication_date','publication_date_source','publication_date_status','publication_date_basis')}

def apply_verified_dates(root,papers):
    path=Path(root)/'config/publication_dates.json'
    registry=json.loads(path.read_text()) if path.exists() else {'records':[]}
    entries={str(r.get('doi') or '').lower().removeprefix('https://doi.org/'):r for r in registry['records'] if r.get('doi')}
    output=[]
    for original in papers:
        row=copy.deepcopy(original);key=str(row.get('doi') or '').lower().removeprefix('https://doi.org/')
        evidence=entries.get(key,{})
        fields=row_publication_fields(evidence) or row_publication_fields(row)
        if fields:row.update(fields)
        output.append(row)
    return output

def recent_publications(papers,as_of=None):
    current=as_of or today();cutoff=current-timedelta(days=90)
    matches=[p for p in papers if row_publication_fields(p) and cutoff<=exact_date(p['publication_date'])<=current]
    return sorted(matches,key=lambda p:(p['publication_date'],str(p.get('title') or '').casefold()),reverse=True)
