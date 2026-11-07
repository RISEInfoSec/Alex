"""Normalize APWG review identities exactly as the current private Site does.

This is for decision matching only: it does not process candidates, alter the
source manifest, infer permission, or approve a publication. Unsupported or
ambiguous source values fail closed rather than inventing a hash or batch.
"""
from copy import deepcopy
import hashlib
import json
import re


def normalize(manifest):
    if not isinstance(manifest, dict) or not isinstance(manifest.get('records'), list):
        raise ValueError('Complete APWG manifest is required')
    if len(manifest['records']) > 10000:
        raise ValueError('APWG inventory exceeds the bounded adapter')
    pending=[]
    for row in manifest['records']:
        if not isinstance(row,dict):raise ValueError('Invalid APWG source row')
        decision=row.get('editorial_decision') or ''
        if not isinstance(decision,str):raise ValueError('Invalid APWG editorial decision')
        if decision in ('approved_quality_hold','approved','rejected') or decision.startswith('approved'):
            continue
        pending.append(row)
    result=[];seen=set()
    for index,original in enumerate(pending):
        row=deepcopy(original);number=row.get('review_number');year=row.get('year')
        if type(number) is not int or not 1 <= number <= 9007199254740991 or number in seen:
            raise ValueError('Invalid or duplicate APWG review number')
        seen.add(number)
        if not isinstance(row.get('title'),str) or not row['title']:
            raise ValueError('APWG title is unavailable')
        if not (isinstance(year,str) or type(year) is int) or not re.fullmatch(r'[0-9]+',str(year).strip()):
            raise ValueError('APWG source year is invalid')
        if not 0 <= int(str(year).strip()) <= 9999:raise ValueError('APWG source year is out of range')
        for name in ('authors','author','apwg_paper_url','source_url','abstract'):
            if row.get(name) is not None and not isinstance(row[name],str):
                raise ValueError('APWG source field has an unsupported type')
        authors=row.get('authors') or row.get('author') or ''
        source=row.get('apwg_paper_url') or row.get('source_url') or ''
        abstract=row.get('abstract') or ''
        content={'title':row['title'],'authors':authors,'year':year,'source_url':source,'abstract':abstract}
        try:
            encoded=json.dumps(content,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        except (UnicodeEncodeError,ValueError) as exc:
            raise ValueError('APWG source text cannot be normalized') from exc
        batch=row.get('review_batch') or index//20+1
        if type(batch) is not int or batch < 1:raise ValueError('Invalid APWG batch')
        row.update(candidate_id='apwg-'+str(number),content_sha256=hashlib.sha256(encoded).hexdigest(),
                   authors=authors,source_url=source,year=int(str(year).strip()),batch=batch,
                   decision='pending',document_type='research_paper',
                   recommendation=row.get('recommendation') if row.get('recommendation') in ('include','exclude','discuss') else 'discuss',
                   review_reason=row.get('review_reason') or row.get('next_action') or 'Editorial recommendation pending.')
        result.append(row)
    return {'records':result}
